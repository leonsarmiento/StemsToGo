# StemsToGo

A lightweight Streamlit web application that lets any user paste a YouTube video URL and receive isolated audio stems (vocals, drums, bass, other) as downloadable MP3 files — powered by the Demucs `htdemucs_ft` model.

## Features

- **Single user flow:** Paste URL → Click "Extract" → Wait → Download 4 MP3 files
- **4-stem separation:** vocals, drums, bass, other
- **Background processing:** Never blocks the Streamlit main thread
- **Progress tracking:** Real-time status updates during extraction
- **Flexible downloads:** Individual stem buttons or ZIP archive
- **Comprehensive logging:** Initialization and runtime logs for debugging

## Prerequisites

- **Python 3.10** (recommended) or higher
- **ffmpeg** (system dependency for audio conversion)

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

## Running Locally

```bash
streamlit run app.py --server.port 8501
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

## How It Works

1. **URL Input:** Paste any YouTube URL (standard, short links, shorts, embeds, live)
2. **Audio Download:** yt-dlp extracts audio from YouTube → `stem_<ID>.m4a`
3. **Format Conversion:** ffmpeg converts to WAV → `stem_<ID>.wav`
4. **Stem Separation:** Demucs `htdemucs_ft` model separates into 4 stems → `*.mp3`
5. **Download:** Individual download buttons or ZIP archive

## Model Download

The Demucs `htdemucs_ft` model (~80MB) is downloaded automatically on first use and cached locally. Subsequent runs use the cached model.

## Deployment to Streamlit Cloud

**⚠️ Important:** Streamlit Cloud has limited system package support. This app requires FFmpeg shared libraries (`libavutil.so.*`) which may not be available on Streamlit Cloud's free tier.

**Recommended deployment methods:**

### Option 1: Local Deployment (Easiest)
```bash
conda create -n stemstogo python=3.10 -y && conda activate stemstogo
pip install -r requirements.txt
streamlit run app.py --server.port 8501
```

### Option 2: Docker Deployment (Production Recommended)
```bash
# Build the image
docker build -t stemstogo .

# Run the container
docker run -p 8501:8501 stemstogo
```

### Option 3: Streamlit Cloud (Limited Support)
1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repository
4. Streamlit will attempt to install dependencies from `requirements.txt` and `bindep.txt`
5. **Note:** FFmpeg shared libraries may not be available, causing torchcodec to fail

**For production use, Docker deployment is strongly recommended.**

## Debugging & Logging

The app includes comprehensive logging for troubleshooting:

- **Initialization logs:** View dependency status and system info in the app UI
- **Runtime logs:** Detailed pipeline execution logs saved to `/tmp/stemstogo_app.log`
- **Error tracking:** Full tracebacks captured for all pipeline failures

To view logs:
1. Open the app and expand "📋 View Initialization Logs" section
2. Check `/tmp/stemstogo_app.log` for detailed runtime logs

## Constraints & Considerations

- **Processing time:** ~3 minutes per 4-minute song on CPU
- **File format:** MP3 at 128-192 kbps, 44100 Hz, stereo
- **Temp files:** Auto-generated per request, cleanup available after download
- **No user accounts:** Stateless app — each request is independent

## Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| streamlit | >=1.28.0 | Web UI framework |
| yt-dlp | >=2023.12.30 | YouTube audio extraction |
| demucs | >=4.0.0 | Audio stem separation |
| torchcodec | >=0.6.0 | Required by Demucs for audio saving |
| ffmpeg-python | >=0.2.0 | Programmatic ffmpeg control |

## License

Private project.
