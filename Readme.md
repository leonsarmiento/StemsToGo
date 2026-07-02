# StemsToGo

A lightweight Streamlit web application that separates any uploaded audio or video file into isolated stems (vocals, drums, bass, other) as downloadable MP3 files — powered by the Demucs `htdemucs_ft` model.

## Features

- **Upload-based flow:** Upload audio/video → Click "Extract" → Preview & download 4 MP3 stems
- **4-stem separation:** vocals, drums, bass, other
- **Audio & video input:** MP3, WAV, M4A, OGG/Opus (WhatsApp/Telegram voice notes), FLAC, AIFF, MP4, MOV (incl. iPhone HEVC), MKV, AVI, and more. ffmpeg extracts the audio track from video files automatically.
- **In-browser preview:** Audio/video player for the input; audio player for each extracted stem
- **Background processing:** Never blocks the Streamlit main thread
- **Progress tracking:** Real-time status updates during extraction
- **Flexible downloads:** Individual stem buttons or ZIP archive
- **Automatic storage management:**
  - Uploaded input is deleted immediately after stems are extracted
  - Background reaper deletes any temp files older than 1 hour
  - Manual cleanup button for immediate temp file removal
- **Comprehensive logging:** Initialization and runtime logs for debugging

## Prerequisites

- **Python 3.10** (recommended) or higher
- **ffmpeg** with shared libraries (`libavutil.so.*`) for audio conversion and torchcodec

## Installation

### Using Conda (Recommended)

```bash
# Create and activate Python 3.10 environment
conda create -n stemstogo python=3.10 -y
conda activate stemstogo

# Install dependencies
pip install -r requirements.txt
```

### Using System Python

```bash
# Ensure Python 3.10+ is installed
python3 --version  # Should show 3.10.x or higher

# Install dependencies
pip install -r requirements.txt
```

On macOS, install ffmpeg with shared libraries:

```bash
brew install ffmpeg
```

On Debian/Ubuntu:

```bash
sudo apt-get install ffmpeg
```

## Running Locally

```bash
streamlit run app.py --server.port 8501
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

## How It Works

1. **Upload:** User uploads an audio or video file
2. **Format Conversion:** ffmpeg decodes the file (extracting the audio track from video containers) and converts to WAV → `input.wav`
3. **Stem Separation:** Demucs `htdemucs_ft` model separates the WAV into 4 stems → `vocals.mp3`, `drums.mp3`, `bass.mp3`, `other.mp3`
4. **Preview & Download:** In-browser audio preview of each stem; individual download buttons or ZIP archive

## Model Download

The Demucs `htdemucs_ft` model (~80MB, 4 averaged sub-models) is downloaded automatically on first use and cached locally at `~/.cache/torch/hub/checkpoints/`. Subsequent runs use the cached model.

## Storage Management

The app manages temporary files automatically to prevent disk fill-up:

- **Immediate cleanup:** The uploaded input file is deleted as soon as stem extraction completes (the stems live in a separate temp directory).
- **Reaper daemon:** A background thread scans every 5 minutes and deletes any `stem_upload_*` temp directory older than 1 hour. This catches files from abandoned requests, browser disconnects, crashes, or users who don't click cleanup.
- **Manual cleanup:** A "Clean up temp files" button removes the current session's temp files on demand.

## Deployment to Streamlit Cloud

StemsToGo runs on Streamlit Community Cloud. The `packages.txt` file declares `ffmpeg` as a system dependency, which Streamlit Cloud installs via apt — providing the shared libraries (`libavutil.so.*`) that torchcodec needs.

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repository, set the main file to `app.py`
4. Streamlit Cloud installs Python deps from `requirements.txt` and system deps from `packages.txt`
5. First run downloads the Demucs model (~80MB), so the first extraction takes longer

## Debugging & Logging

The app includes comprehensive logging for troubleshooting:

- **Initialization logs:** View dependency status and system info in the app UI
- **Runtime logs:** Detailed pipeline execution logs saved to `/tmp/stemstogo_app.log`
- **Error tracking:** Full tracebacks captured for all pipeline failures

To view logs:
1. Open the app and expand "📋 View Initialization Logs" section
2. Check `/tmp/stemstogo_app.log` for detailed runtime logs

## Constraints & Considerations

- **Processing time:** ~1 minute per 2.5 minutes of audio on CPU (varies by hardware)
- **Output format:** MP3 at 128-192 kbps, 44100 Hz, stereo
- **File size:** Streamlit's default upload limit is 200MB
- **No user accounts:** Stateless app — each request is independent
- **First run:** Downloads the Demucs model (~80MB), so the first extraction takes longer

## Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| streamlit | >=1.28.0 | Web UI framework |
| demucs | >=4.0.0 | Audio stem separation |
| torch | >=2.11.0 | PyTorch runtime required by Demucs and TorchCodec |
| torchcodec | >=0.14.0 | Required by Demucs for audio saving |

**System dependency:** `ffmpeg` (declared in `packages.txt` for Streamlit Cloud)

## Project Structure

```
StemsToGo/
├── app.py            # Main Streamlit application
├── requirements.txt  # Python dependencies
├── packages.txt      # System dependencies (ffmpeg) for Streamlit Cloud
└── Readme.md         # This file
```

## License

Private project.
