"""
StemsToGo - Streamlit App for YouTube Audio Stem Extraction
Uses Demucs htdemucs_ft model for 4-stem separation (vocals, drums, bass, other)
"""

import os
import re
import sys
import subprocess
import tempfile
import threading
import logging
from queue import Queue
from pathlib import Path
from datetime import datetime

import streamlit as st
import yt_dlp


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

# Add handlers to logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

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
        'yt-dlp': 'yt_dlp',
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

# --- URL Validation ---
def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None


def validate_url(url: str) -> bool:
    """Validate that the input is a YouTube URL."""
    if not url:
        return False
    # Check for common YouTube URL patterns
    youtube_patterns = [
        r'youtube\.com/watch',
        r'youtu\.be/',
        r'youtube\.com/shorts/',
        r'youtube\.com/embed/',
        r'youtube\.com/live/',
    ]
    return any(re.search(pattern, url) for pattern in youtube_patterns)


# --- Pipeline Steps ---
def download_audio(youtube_url: str, output_path: str) -> bool:
    """Download audio from YouTube using yt-dlp."""
    logger.info(f"Downloading audio from: {youtube_url}")
    
    ydl_opts = {
        'format': 'bestaudio',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
            'preferredquality': '192',
        }],
        'outtmpl': output_path,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        
        logger.info(f"Audio downloaded successfully to: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to download audio: {e}")
        return False


def convert_to_wav(m4a_path: str, wav_path: str) -> bool:
    """Convert M4A to WAV using ffmpeg."""
    logger.info(f"Converting {m4a_path} to WAV format")
    
    cmd = [
        'ffmpeg', '-y',
        '-i', m4a_path,
        '-acodec', 'pcm_s16le',
        '-ar', '44100',
        '-ac', '2',
        wav_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            st.error(f"FFmpeg error: {result.stderr}")
            return False
        
        logger.info(f"WAV conversion successful: {wav_path}")
        return True
    except Exception as e:
        logger.error(f"FFmpeg execution error: {e}")
        st.error(f"FFmpeg execution error: {e}")
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
        
        # Stream output for progress feedback and logging
        for line in process.stdout:
            logger.debug(line.strip())
            st.write(line, end='')
        
        process.wait()
        
        if process.returncode != 0:
            logger.error(f"Demucs failed with return code {process.returncode}")
            st.error(f"Demucs failed with return code {process.returncode}")
            return False
        
        logger.info("Demucs separation completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Demucs execution error: {e}")
        st.error(f"Demucs execution error: {e}")
        return False


def get_stem_paths(output_dir: str) -> dict[str, str]:
    """Get paths to all 4 stem MP3 files."""
    stem_paths = {}
    for stem in STEMS:
        path = os.path.join(output_dir, stem + OUTPUT_SUFFIX)
        if os.path.exists(path):
            stem_paths[stem] = path
        else:
            st.warning(f"Missing stem file: {path}")
    
    return stem_paths


# --- Background Pipeline ---
def run_pipeline(youtube_url: str, q: Queue):
    """Run the full extraction pipeline in a background thread."""
    logger.info(f"Starting pipeline for URL: {youtube_url}")
    
    try:
        # Extract video ID
        q.put(("progress", 0.05, "Extracting video ID..."))
        video_id = extract_video_id(youtube_url)
        if not video_id:
            logger.error("Invalid YouTube URL - could not extract video ID")
            q.put(("error", 0, "Invalid YouTube URL. Please check the link and try again."))
            return
        
        logger.info(f"Extracted video ID: {video_id}")
        
        # Create temp directories
        temp_base = tempfile.mkdtemp(prefix=f"stem_{video_id}_")
        m4a_path = os.path.join(temp_base, f"stem_{video_id}.m4a")
        wav_path = os.path.join(temp_base, f"stem_{video_id}.wav")
        output_dir = os.path.join(temp_base, f"output_{video_id}")
        
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Created temp directory: {temp_base}")
        
        # Step 1: Download audio
        q.put(("progress", 0.1, "Downloading audio from YouTube..."))
        if not download_audio(youtube_url, m4a_path):
            q.put(("error", 0, "Failed to download audio from YouTube."))
            return
        
        # Step 2: Convert to WAV
        q.put(("progress", 0.3, "Converting audio to WAV format..."))
        if not convert_to_wav(m4a_path, wav_path):
            q.put(("error", 0, "Failed to convert audio format."))
            return
        
        # Step 3: Separate stems with Demucs (LONGEST STEP)
        q.put(("progress", 0.5, "Separating stems with Demucs (this may take a few minutes)..."))
        if not run_demucs(wav_path, output_dir):
            q.put(("error", 0, "Failed to separate stems with Demucs."))
            return
        
        # Step 4: Get results
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
    st.markdown("Extract vocals, drums, bass, and other stems from any YouTube video.")
    
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
            "**❌ This app cannot run on Streamlit Cloud free tier.**\n\n"
            "The `torchcodec` library requires FFmpeg shared libraries "
            "(`libavutil.so.*`) which are not available on Streamlit Cloud's "
            "free hosting tier.\n\n"
            "**Working deployment options:**\n\n"
            "### 1. Local Deployment (Recommended for Testing)\n"
            "```bash\n"
            "conda create -n stemstogo python=3.10 -y && conda activate stemstogo\n"
            "pip install -r requirements.txt\n"
            "streamlit run app.py --server.port 8501\n"
            "```\n\n"
            "### 2. Docker Deployment (Production)\n"
            "```bash\n"
            "docker build -t stemstogo .\n"
            "docker run -p 8501:8501 stemstogo\n"
            "```\n\n"
            "### 3. Streamlit Cloud Paid Tier\n"
            "If you need cloud hosting, consider Streamlit Cloud's paid plans "
            "which may support system package installation.\n\n"
            "**Why this happens:**\n"
            "Streamlit Cloud free tier uses a minimal container that doesn't "
            "include FFmpeg shared libraries. The `torchcodec` package (required "
            "by Demucs for audio saving) needs these libraries to function.\n\n"
            "For more information, see: "
            "[Streamlit Cloud Documentation](https://docs.streamlit.io/deploy)"
        )
        return
    
    # URL input
    youtube_url = st.text_input(
        "Paste a YouTube URL",
        placeholder="https://www.youtube.com/watch?v=... or https://youtu.be/..."
    )
    
    # Validate URL
    if youtube_url and not validate_url(youtube_url):
        st.error("Please enter a valid YouTube URL.")
    
    # Extract button
    if st.button("Extract Stems", type="primary", disabled=not youtube_url or not validate_url(youtube_url)):
        if not youtube_url:
            st.warning("Please enter a YouTube URL.")
        elif not validate_url(youtube_url):
            st.error("Invalid YouTube URL format.")
        else:
            # Create progress container
            progress_container = st.container()
            
            with progress_container:
                # Status messages
                status_text = st.empty()
                progress_bar = st.progress(0)
                
                # Create queue for background thread communication
                q = Queue()
                
                # Start background pipeline
                thread = threading.Thread(
                    target=run_pipeline,
                    args=(youtube_url, q),
                    daemon=True
                )
                thread.start()
                
                # Monitor progress
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
                            
                    except Exception as e:
                        if "Empty" in str(e):
                            continue
                        st.error(f"Progress monitoring error: {e}")
                        break
                
                # If thread finished without queue message
                if not stem_paths and not q.empty():
                    task, percent, *args = q.get()
                    if task == "done":
                        stem_paths = args[0]
                        output_dir = args[1]
                    elif task == "error":
                        st.error(f"**Error:** {args[0]}")
            
            # Display results
            if stem_paths:
                st.success("Your stems are ready for download!")
                
                # Show file info
                st.subheader("Download Your Stems")
                
                for stem in STEMS:
                    if stem in stem_paths:
                        file_size = os.path.getsize(stem_paths[stem]) / (1024 * 1024)  # MB
                        st.markdown(f"**{stem.capitalize()}** ({file_size:.2f} MB)")
                        with open(stem_paths[stem], "rb") as f:
                            st.download_button(
                                label=f"Download {stem.capitalize()}",
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
                    label="Download All as ZIP",
                    data=zip_buffer,
                    file_name=f"stems_{extract_video_id(youtube_url)}.zip",
                    mime="application/zip"
                )
                
                # Cleanup option
                if st.button("Clean up temp files"):
                    import shutil
                    if output_dir and os.path.exists(output_dir):
                        shutil.rmtree(os.path.dirname(output_dir))
                    st.success("Temp files cleaned up.")


if __name__ == "__main__":
    main()
