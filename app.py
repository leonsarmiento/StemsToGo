"""
StemsToGo - Streamlit App for Audio Stem Extraction
Upload any audio file and Demucs htdemucs_ft separates it into
4 stems (vocals, drums, bass, other).
"""

import os
import sys
import time
import random
import subprocess
import tempfile
import threading
import logging
from pathlib import Path

import streamlit as st


# --- Configuration ---
MODEL_NAME = "htdemucs_ft"
STEMS = ["vocals", "drums", "bass", "other"]
OUTPUT_SUFFIX = "_stems.mp3"

# --- Logging Setup ---
# Create a logger for the app
logger = logging.getLogger("StemsToGo")
logger.setLevel(logging.DEBUG)

# Create console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Create file handler for persistent logs
log_file = Path(tempfile.gettempdir()) / "stemstogo_app.log"
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Add handlers to logger (only once per process — Streamlit reruns this module)
if not logger.handlers:
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

# Capture stderr for error logging
class StderrCapture:
    """Capture stderr output for logging."""
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
        self.buffer = []
    
    def write(self, text):
        self.buffer.append(text)
        self.original_stderr.write(text)
    
    def flush(self):
        self.original_stderr.flush()
    
    def get_and_clear(self):
        captured = ''.join(self.buffer)
        self.buffer.clear()
        return captured


# --- Temp File Cleanup ---
TEMP_MAX_AGE_SECONDS = 60 * 60  # delete temp dirs older than 1 hour
REAPER_SCAN_INTERVAL = 5 * 60   # scan every 5 minutes


def _cleanup_reaper():
    """Background daemon that deletes stale stem_upload_* temp dirs.

    Runs forever, scanning every REAPER_SCAN_INTERVAL. Any temp dir with
    the app's prefix older than TEMP_MAX_AGE_SECONDS is removed. This is
    the storage safety net — it catches dirs left behind by abandoned
    requests, crashes, or users who never click cleanup.
    """
    import time
    import shutil
    import glob

    tmp_dir = tempfile.gettempdir()
    logger.info(f"Cleanup reaper started (max age {TEMP_MAX_AGE_SECONDS}s, "
                f"scan interval {REAPER_SCAN_INTERVAL}s)")

    while True:
        try:
            now = time.time()
            for path in glob.glob(os.path.join(tmp_dir, "stem_upload_*")):
                try:
                    age = now - os.path.getmtime(path)
                    if age > TEMP_MAX_AGE_SECONDS:
                        shutil.rmtree(path, ignore_errors=True)
                        logger.info(f"Reaper deleted stale temp dir: {path} (age {int(age)}s)")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Reaper scan error: {e}")

        time.sleep(REAPER_SCAN_INTERVAL)


def start_cleanup_reaper():
    """Start the cleanup reaper daemon thread (once)."""
    thread = threading.Thread(target=_cleanup_reaper, daemon=True)
    thread.start()


# --- Initialization Logging ---
def log_initialization():
    """Log initialization status and dependency checks."""
    logger.info("=" * 60)
    logger.info("StemsToGo Application Initialization")
    logger.info("=" * 60)
    
    # Log Python version
    logger.info(f"Python version: {sys.version}")
    
    # Log Streamlit version
    try:
        import streamlit as st
        logger.info(f"Streamlit version: {st.__version__}")
    except Exception as e:
        logger.error(f"Failed to import Streamlit: {e}")
    
    # Check critical dependencies
    dependencies = {
        'torchcodec': 'torchcodec',
        'demucs': 'demucs',
    }

    logger.info("Checking dependencies...")
    for pkg_name, import_name in dependencies.items():
        try:
            __import__(import_name)
            logger.info(f"✓ {pkg_name} is available")
        except (ImportError, RuntimeError) as e:
            logger.error(f"✗ {pkg_name} failed to load/is missing: {e}")
        except Exception as e:
            logger.error(f"✗ Unexpected error loading {pkg_name}: {e}")

    # Check ffmpeg
    try:
        result = subprocess.run(['ffmpeg', '-version'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ffmpeg_version = result.stdout.split('\n')[0]
            logger.info(f"✓ ffmpeg is available: {ffmpeg_version}")
        else:
            logger.error("✗ ffmpeg is not available or not in PATH")
    except FileNotFoundError:
        logger.error("✗ ffmpeg is not installed or not in PATH")
    except Exception as e:
        logger.error(f"✗ Error checking ffmpeg: {e}")

    try:
        import ctypes.util
        avutil_library = ctypes.util.find_library("avutil")
        if avutil_library:
            logger.info(f"✓ FFmpeg shared library avutil found: {avutil_library}")
        else:
            logger.warning("⚠ FFmpeg shared library avutil was not found. torchcodec may fail to load.")
    except Exception as e:
        logger.warning(f"⚠ Could not check FFmpeg shared libraries: {e}")

    logger.info("=" * 60)
    logger.info("Initialization complete")
    logger.info("=" * 60)


# Run initialization logging
log_initialization()

# Start background cleanup reaper (storage safety net)
start_cleanup_reaper()

# --- Pipeline Steps ---
def convert_to_wav(input_path: str, wav_path: str) -> bool:
    """Convert any audio or video file to WAV using ffmpeg.

    For video files, ffmpeg extracts the audio track automatically.
    Handles MP3, WAV, M4A, OGG/Opus, FLAC, MP4, MOV (incl. HEVC), MKV, etc.
    """
    logger.info(f"Converting {input_path} to WAV format")

    cmd = [
        'ffmpeg', '-y',
        '-i', input_path,
        '-acodec', 'pcm_s16le',
        '-ar', '44100',
        '-ac', '2',
        wav_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False

        logger.info(f"WAV conversion successful: {wav_path}")
        return True
    except Exception as e:
        logger.error(f"FFmpeg execution error: {e}")
        return False


def run_demucs(wav_path: str, output_dir: str) -> bool:
    """Run Demucs htdemucs_ft model for stem separation."""
    logger.info(f"Running Demucs with model {MODEL_NAME}")
    logger.info(f"Input: {wav_path}")
    logger.info(f"Output directory: {output_dir}")
    
    cmd = [
        'demucs',
        '--name', MODEL_NAME,
        '--mp3',
        '--out', output_dir,
        wav_path
    ]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Log Demucs output (cannot write to Streamlit from this background thread)
        for line in process.stdout:
            logger.debug(line.strip())

        process.wait()

        if process.returncode != 0:
            logger.error(f"Demucs failed with return code {process.returncode}")
            return False

        logger.info("Demucs separation completed successfully")
        return True

    except Exception as e:
        logger.error(f"Demucs execution error: {e}")
        return False


def get_stem_paths(output_dir: str) -> dict[str, str]:
    """Find all 4 stem MP3 files produced by Demucs.

    Demucs nests its output as <output_dir>/<model>/<track>/<stem>.mp3,
    so we search recursively rather than assuming a fixed path.
    """
    stem_paths = {}
    out_root = Path(output_dir)
    for stem in STEMS:
        matches = list(out_root.rglob(f"{stem}.mp3"))
        if matches:
            stem_paths[stem] = str(matches[0])
            logger.info(f"Found {stem} stem: {matches[0]}")
        else:
            logger.warning(f"Missing stem file: {stem}.mp3 under {output_dir}")

    return stem_paths


# --- Job Persistence (survives mobile disconnects) ---
# Job state lives on disk keyed by job_id, NOT in session state, so that a
# fresh session (after a phone sleep/reconnect) can still find the results.
import json
import uuid


def job_dir_for(job_id: str) -> str:
    """Return the on-disk working dir for a job.

    Uses the stem_upload_ prefix so the existing 1-hour reaper cleans it up.
    """
    return os.path.join(tempfile.gettempdir(), f"stem_upload_{job_id}")


def write_manifest(job_id: str, data: dict):
    """Merge-update the job's manifest.json atomically-ish."""
    path = os.path.join(job_dir_for(job_id), "manifest.json")
    current = {}
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                current = json.load(f)
    except Exception:
        current = {}
    current.update(data)
    try:
        jdir = job_dir_for(job_id)
        with open(path, "w") as f:
            json.dump(current, f)
        # Bump dir mtime so the reaper never removes a still-running job
        os.utime(jdir, None)
    except Exception as e:
        logger.warning(f"Could not write manifest for job {job_id}: {e}")


def read_manifest(job_id: str) -> dict | None:
    """Read a job's manifest, or None if the job dir is gone (reaped/never existed)."""
    path = os.path.join(job_dir_for(job_id), "manifest.json")
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read manifest for job {job_id}: {e}")
        return None


# --- Background Pipeline ---
def run_pipeline(input_audio_path: str, job_id: str):
    """Run the extraction pipeline in a background thread.

    Writes durable status updates to manifest.json (keyed by job_id) so the
    UI can recover after a mobile disconnect. The job's working dir is the
    same dir that holds the uploaded input file.
    """
    job_dir = os.path.dirname(input_audio_path)
    logger.info(f"Starting pipeline job {job_id} for: {input_audio_path}")

    write_manifest(job_id, {"status": "converting"})

    try:
        wav_path = os.path.join(job_dir, "input.wav")
        output_dir = os.path.join(job_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Step 1: Convert uploaded audio/video to WAV
        if not convert_to_wav(input_audio_path, wav_path):
            write_manifest(job_id, {"status": "error",
                                    "message": "Failed to convert audio. Is the file a valid format?"})
            return

        # Step 2: Separate stems with Demucs (LONGEST STEP)
        write_manifest(job_id, {"status": "separating"})
        if not run_demucs(wav_path, output_dir):
            write_manifest(job_id, {"status": "error",
                                    "message": "Failed to separate stems with Demucs."})
            return

        # Step 3: Collect results
        stem_paths = get_stem_paths(output_dir)
        if not stem_paths:
            write_manifest(job_id, {"status": "error", "message": "No stem files were generated."})
            return

        logger.info(f"Pipeline job {job_id} completed: {len(stem_paths)} stems")
        write_manifest(job_id, {
            "status": "done",
            "stem_paths": stem_paths,
            "output_dir": output_dir,
        })

        # Drop the original uploaded input now that stems are extracted
        try:
            os.remove(input_audio_path)
            logger.info(f"Removed input file {input_audio_path}")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Pipeline error job {job_id}: {str(e)}", exc_info=True)
        write_manifest(job_id, {"status": "error", "message": f"Pipeline error: {str(e)}"})


# --- Status Messages (shown randomly during long waits) ---
FUNNY_MESSAGES = [
    "Separating the singers from the shouters...",
    "Asking the bass to step forward...",
    "Convincing the drums they're the main character...",
    "Teaching the vocals to fly solo...",
    "Politely asking the guitar to leave the room...",
    "Petting le chat...",
    "Defragmenting memory, both RAM and personal...",
    "Untangling the frequencies like old Christmas lights...",
    "Giving the bass guitar its own apartment...",
    "Negotiating custody of the chorus...",
    "Sorting the loud from the proud...",
    "Asking the hi-hat to speak up...",
    "Teaching the snare drum some independence...",
    "Isolating the isolates...",
    "Convincing the reverb it's not wanted here...",
    "Untying the sonic shoelaces...",
    "Giving each stem a name and a backstory...",
    "Separating the signal from the shenanigans...",
    "Asking the vocals to use their indoor voice...",
    "Polishing the cymbals... with a soft cloth...",
    "Counting every single sample... 1, 2, 3...",
    "Rearranging the furniture in the frequency domain...",
    "Convincing the bass and kick they're not the same person...",
    "Sending the drums to obedience school...",
    "Explaining personal space to the synths...",
    "Bribing the algorithm with coffee...",
    "Consulting the neural network's horoscope...",
    "Petting le chat (it helps the math)...",
    "Aligning the chakras of the mix...",
    "Asking the ghost of the producer for permission...",
    "Defragmenting the drummer's sense of time...",
    "Teaching the AI to appreciate jazz...",
    "Counting frequencies on fingers and toes...",
    "Untangling the bass from the mud...",
    "Asking the vocals nicely... twice...",
    "Separating the groove from the goop...",
    "Washing the stems in spring water...",
    "Convincing the model this song is worth it...",
    "Polishing the vocals until they sparkle...",
    "Knocking on the door of the latent space...",
    "Whispering encouragement to the tensors...",
    "Asking the GPU to stop sweating...",
    "Convincing the CPU it can do this...",
    "Separating the music from the mayhem...",
    "Giving the silence some breathing room...",
    "Counting the parameters... there's a lot...",
    "Calibrating the vibes...",
    "Tuning the universal resonator...",
    "Asking the chorus to form an orderly queue...",
    "Dusting off the spectrogram...",
    "Teaching the frequencies to share nicely...",
    "Convincing the track it wants to be separated...",
    "Separating the beat from the beast...",
    "Asking the rhythm to hold still...",
    "Polishing the harmonics to a shine...",
    "Petting le chat once more, for good luck...",
    "Defragmenting the singer's emotions...",
    "Untangling the melody from the memory...",
    "Giving the drums a stern talking-to...",
    "Asking the bass to stop hogging the low end...",
    "Separating the wheat from the waveform...",
    "Consulting the great spectrogram in the sky...",
    "Aligning the phases of the moon...",
    "Counting the beats per minute... slowly...",
    "Teaching the stems to stand on their own...",
    "Convincing the vocals they don't need autotune...",
    "Separating the artists from the artifacts...",
    "Polishing the transients...",
    "Asking the reverb to kindly leave...",
    "Untying the knot in the midrange...",
    "Defragmenting the song's sense of self...",
    "Giving each note a little pep talk...",
    "Separating the magic from the math...",
    "Asking the hi-hat to stop being so ticky...",
    "Convincing the bass line it's not the melody...",
    "Petting le chat's neural networks...",
    "Counting grains of sand in the reverb tail...",
    "Separating the song from its shadows...",
    "Polishing the kick drum's shoe...",
    "Asking the synths to file in single file...",
    "Teaching the AI the meaning of 'groove'...",
    "Convincing the model to trust its instincts...",
    "Separating the chorus from the chaos...",
    "Untangling the cord that powers the soul...",
    "Giving the vocals a pep rally...",
    "Asking the drums to find their inner peace...",
    "Defragmenting the chorus's feelings...",
    "Polishing every sample by hand...",
    "Separating the hits from the misses...",
    "Asking the bass to whisper, just once...",
    "Convincing the frequencies they're all special...",
    "Petting le chat one final time...",
    "Counting the ways this song can be split...",
    "Separating the rhythm from the rubble...",
    "Polishing the stereo field with a chamois...",
    "Asking the lead vocal to take a solo...",
    "Defragmenting the band's group chat...",
    "Untangling the harmony from the hype...",
    "Giving the outro a moment to breathe...",
    "Convincing every stem it's the main event...",
    "Separating the bangers from the bungles...",
    "Asking the compressor to take a deep breath...",
    "Petting le chat's cousin, le dog...",
    "Defragmenting the cat's commitment issues...",
    "Untangling the last 1% of the waveform...",
    "Convincing the final stem to come out of hiding...",
]


# --- Streamlit UI ---
def main():
    st.set_page_config(
        page_title="StemsToGo",
        page_icon="🎵",
        layout="centered"
    )

    st.title("🎵 StemsToGo")
    st.markdown(
        "Upload an audio file and Demucs will separate it into **vocals**, "
        "**drums**, **bass**, and **other** stems."
    )

    # Display initialization logs (collapsible)
    with st.expander("📋 View Initialization Logs", expanded=False):
        try:
            with open(log_file, 'r') as f:
                logs = f.read()
            st.code(logs, language='text')
        except FileNotFoundError:
            st.info("No initialization logs found.")

        st.caption(f"Log file location: `{log_file}`")

    # Check for required dependencies
    torchcodec_available = False
    try:
        import torchcodec
        torchcodec_available = True
        logger.info("torchcodec loaded successfully")
    except (ImportError, RuntimeError) as e:
        logger.warning(f"torchcodec not available: {e}")

    if not torchcodec_available:
        st.error(
            "**❌ A required dependency (`torchcodec`) failed to load.**\n\n"
            "Demucs needs `torchcodec` (which depends on FFmpeg shared libraries) "
            "to save MP3 stems.\n\n"
            "**If running on Streamlit Cloud:** ensure `packages.txt` with `ffmpeg` "
            "is present in the repo.\n\n"
            "**If running locally:**\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            "```\n"
            "and install FFmpeg on your system."
        )
        return

    # Supported formats (anything ffmpeg can decode — audio or video)
    audio_extensions = ["mp3", "wav", "m4a", "aac", "ogg", "opus", "flac", "wma", "aiff", "webm"]
    video_extensions = ["mp4", "mov", "m4v", "avi", "mkv", "wmv", "flv", "3gp", "mts"]
    accepted_types = list(set(audio_extensions + video_extensions))

    uploaded_file = st.file_uploader(
        "Upload an audio or video file",
        type=accepted_types,
        help="Audio: MP3, WAV, M4A, OGG/Opus (WhatsApp/Telegram voice notes), FLAC, AIFF, etc. "
             "Video: MP4, MOV/M4V (incl. iPhone HEVC), MKV, AVI, WEBM, WMV, 3GP — the audio track "
             "is extracted automatically."
    )

    if uploaded_file is not None:
        file_suffix = Path(uploaded_file.name).suffix.lower().lstrip(".")
        if file_suffix in video_extensions:
            st.video(uploaded_file)
        else:
            st.audio(uploaded_file)

    # --- Track the active job across reruns and reconnects ---
    # A new upload forgets any previous job/results so we don't auto-restore
    # a finished extraction over a fresh file.
    if uploaded_file is not None:
        if st.session_state.get("source_file") != uploaded_file.name:
            st.session_state.pop("results", None)
            st.session_state["source_file"] = uploaded_file.name
            if "job" in st.query_params:
                del st.query_params["job"]

    # Restore finished results from the URL job id (survives mobile sleep/reconnect).
    # session_state dies with the WebSocket; the job id in the URL does not.
    job_id_in_url = st.query_params.get("job")
    if job_id_in_url and "results" not in st.session_state:
        m = read_manifest(job_id_in_url)
        if m and m.get("status") == "done":
            st.session_state["results"] = {
                "stem_paths": m["stem_paths"],
                "output_dir": m["output_dir"],
                "base_name": m.get("base_name", "stems"),
            }

    # --- Extract button: start a new job ---
    started_job_id = None
    if st.button("Extract Stems", type="primary", disabled=uploaded_file is None):
        if uploaded_file is None:
            st.warning("Please upload an audio file first.")
        else:
            started_job_id = uuid.uuid4().hex
            job_dir = job_dir_for(started_job_id)
            os.makedirs(job_dir, exist_ok=True)
            file_ext = Path(uploaded_file.name).suffix or ".audio"
            input_path = os.path.join(job_dir, f"input{file_ext}")
            with open(input_path, "wb") as f:
                f.write(uploaded_file.getvalue())
            base_name = Path(uploaded_file.name).stem or "stems"
            write_manifest(started_job_id, {"status": "pending", "base_name": base_name})
            st.query_params["job"] = started_job_id
            logger.info(f"Saved upload '{uploaded_file.name}' -> {input_path} (job {started_job_id})")
            thread = threading.Thread(target=run_pipeline, args=(input_path, started_job_id), daemon=True)
            thread.start()

    # --- Live progress poll: works for a just-started job OR a reconnected running job ---
    active_job = started_job_id or job_id_in_url
    if active_job and "results" not in st.session_state:
        m = read_manifest(active_job)
        if m is None:
            st.warning("This extraction has expired or was not found. "
                       "Temp files are cleared after 1 hour — please upload and run again.")
        elif m.get("status") == "done":
            st.session_state["results"] = {
                "stem_paths": m["stem_paths"],
                "output_dir": m["output_dir"],
                "base_name": m.get("base_name", "stems"),
            }
            st.rerun()
        elif m.get("status") == "error":
            st.error(f"**Error:** {m.get('message', 'unknown error')}")
            if "job" in st.query_params:
                del st.query_params["job"]
        else:
            # Running — poll the durable manifest and render progress.
            status_text = st.empty()
            progress_bar = st.progress(0)
            last_rotation = time.time()
            last_status = None
            while True:
                m = read_manifest(active_job)
                if m is None:
                    status_text.warning("This extraction has expired. Temp files are cleared after 1 hour.")
                    break
                status = m.get("status")
                if status == "done":
                    st.session_state["results"] = {
                        "stem_paths": m["stem_paths"],
                        "output_dir": m["output_dir"],
                        "base_name": m.get("base_name", "stems"),
                    }
                    progress_bar.progress(1.0)
                    status_text.write("**✓ Extraction complete!**")
                    time.sleep(0.5)
                    st.rerun()
                    break
                if status == "error":
                    progress_bar.progress(0)
                    status_text.error(f"**Error:** {m.get('message', 'unknown error')}")
                    break
                # running: show real sub-status, then rotate funny messages after 20s idle
                label = {"pending": "Starting...",
                         "converting": "Converting audio to WAV...",
                         "separating": "Separating stems with Demucs (this may take a few minutes)..."}.get(status, "Processing...")
                pct = {"pending": 0.05, "converting": 0.2, "separating": 0.5}.get(status, 0.1)
                progress_bar.progress(pct)
                if status != last_status:
                    status_text.write(f"**{label}**")
                    last_status = status
                    last_rotation = time.time()
                elif time.time() - last_rotation > 20:
                    status_text.write(f"*{random.choice(FUNNY_MESSAGES)}*")
                    last_rotation = time.time()
                time.sleep(2)

    # --- Results display (from session_state: just-finished OR restored from URL) ---
    results = st.session_state.get("results")
    if results:
        stem_paths = results["stem_paths"]
        output_dir = results["output_dir"]
        base_name = results["base_name"]

        st.success("Your stems are ready!")
        st.subheader("Preview & Download")

        for stem in STEMS:
            if stem in stem_paths:
                file_size = os.path.getsize(stem_paths[stem]) / (1024 * 1024)  # MB
                st.markdown(f"**{stem.capitalize()}** ({file_size:.2f} MB)")

                # Audio preview
                with open(stem_paths[stem], "rb") as f:
                    st.audio(f, format="audio/mpeg")

                # Download button
                with open(stem_paths[stem], "rb") as f:
                    st.download_button(
                        label=f"⬇ Download {stem.capitalize()}",
                        data=f,
                        file_name=f"{stem}{OUTPUT_SUFFIX}",
                        mime="audio/mpeg",
                        key=f"download_{stem}"
                    )

        # ZIP download option
        import zipfile
        import io

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for stem, path in stem_paths.items():
                with open(path, "rb") as f:
                    zip_file.writestr(f"{stem}{OUTPUT_SUFFIX}", f.read())

        zip_buffer.seek(0)
        st.download_button(
            label="📦 Download All as ZIP",
            data=zip_buffer,
            file_name=f"stems_{base_name}.zip",
            mime="application/zip",
            key="download_zip"
        )

        # Cleanup option
        if st.button("🗑 Clean up temp files"):
            import shutil
            if output_dir and os.path.exists(output_dir):
                shutil.rmtree(os.path.dirname(output_dir))
            st.session_state.pop("results", None)
            if "job" in st.query_params:
                del st.query_params["job"]
            st.success("Temp files cleaned up. You can upload a new file.")


if __name__ == "__main__":
    main()
