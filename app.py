"""
StemsToGo - Streamlit App for Audio Stem Extraction
Upload any audio file and Demucs htdemucs_ft separates it into
4 stems (vocals, drums, bass, other).
"""

import os
import sys
import subprocess
import tempfile
import threading
import logging
from queue import Queue, Empty
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


# --- Background Pipeline ---
def run_pipeline(input_audio_path: str, q: Queue):
    """Run the extraction pipeline in a background thread.

    Converts the uploaded audio to WAV, then runs Demucs to produce 4 stems.
    """
    logger.info(f"Starting pipeline for uploaded file: {input_audio_path}")

    try:
        # Create temp directories
        temp_base = tempfile.mkdtemp(prefix="stem_upload_")
        wav_path = os.path.join(temp_base, "input.wav")
        output_dir = os.path.join(temp_base, "output")
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Created temp directory: {temp_base}")

        # Step 1: Convert uploaded audio to WAV
        q.put(("progress", 0.1, "Converting audio to WAV format..."))
        if not convert_to_wav(input_audio_path, wav_path):
            q.put(("error", 0, "Failed to convert audio. Is the file a valid audio format?"))
            return

        # Step 2: Separate stems with Demucs (LONGEST STEP)
        q.put(("progress", 0.3, "Separating stems with Demucs (this may take a few minutes)..."))
        if not run_demucs(wav_path, output_dir):
            q.put(("error", 0, "Failed to separate stems with Demucs."))
            return

        # Step 3: Collect results
        q.put(("progress", 0.9, "Stems ready! Generating download links..."))
        stem_paths = get_stem_paths(output_dir)

        if not stem_paths:
            logger.error("No stem files were generated")
            q.put(("error", 0, "No stem files were generated."))
            return

        logger.info(f"Pipeline completed successfully. Generated {len(stem_paths)} stem files")
        q.put(("done", 1.0, stem_paths, output_dir))

    except Exception as e:
        logger.error(f"Pipeline error: {str(e)}", exc_info=True)
        q.put(("error", 0, f"Pipeline error: {str(e)}"))


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
        st.audio(uploaded_file)

    # Clear previous results if a new file is uploaded
    if uploaded_file is not None:
        current_file = uploaded_file.name
        if st.session_state.get("source_file") != current_file:
            st.session_state.pop("results", None)
            st.session_state["source_file"] = current_file

    # Extract button
    if st.button("Extract Stems", type="primary", disabled=uploaded_file is None):
        if uploaded_file is None:
            st.warning("Please upload an audio file first.")
        else:
            # Persist the uploaded file to disk so the background thread can read it
            temp_base = tempfile.mkdtemp(prefix="stem_upload_")
            file_ext = Path(uploaded_file.name).suffix or ".audio"
            input_path = os.path.join(temp_base, f"input{file_ext}")
            with open(input_path, "wb") as f:
                f.write(uploaded_file.getvalue())
            logger.info(f"Saved uploaded file '{uploaded_file.name}' to {input_path}")

            # Create progress container
            progress_container = st.container()

            with progress_container:
                status_text = st.empty()
                progress_bar = st.progress(0)

                q = Queue()
                thread = threading.Thread(
                    target=run_pipeline,
                    args=(input_path, q),
                    daemon=True
                )
                thread.start()

                stem_paths = None
                output_dir = None

                while thread.is_alive() or not q.empty():
                    try:
                        task, percent, *args = q.get(timeout=1)

                        if task == "progress":
                            message = args[0]
                            status_text.write(f"**{message}**")
                            progress_bar.progress(percent)

                        elif task == "done":
                            stem_paths = args[0]
                            output_dir = args[1]
                            progress_bar.progress(1.0)
                            status_text.write("**✓ Extraction complete!**")
                            break

                        elif task == "error":
                            error_msg = args[0]
                            progress_bar.progress(0)
                            status_text.error(f"**Error:** {error_msg}")
                            break

                    except Empty:
                        continue

                if not stem_paths and not q.empty():
                    task, percent, *args = q.get()
                    if task == "done":
                        stem_paths = args[0]
                        output_dir = args[1]
                    elif task == "error":
                        st.error(f"**Error:** {args[0]}")

            # Delete the uploaded input file now that stems are extracted
            import shutil
            try:
                shutil.rmtree(temp_base, ignore_errors=True)
                logger.info(f"Deleted uploaded input temp dir: {temp_base}")
            except Exception as e:
                logger.warning(f"Could not delete input temp dir: {e}")

            # Store results in session_state so they survive reruns
            if stem_paths:
                st.session_state["results"] = {
                    "stem_paths": stem_paths,
                    "output_dir": output_dir,
                    "base_name": Path(uploaded_file.name).stem or "stems",
                }
                st.rerun()

    # Display results from session_state (persists across reruns)
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
            st.success("Temp files cleaned up. You can upload a new file.")


if __name__ == "__main__":
    main()
