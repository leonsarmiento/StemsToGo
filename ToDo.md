# StemsToGo — Streamlit App PRD

**Author:** J. Leon | **Date:** 2026-07-01
**Status:** Draft

---

## 1. Overview

StemsToGo is a lightweight Streamlit web application that lets any user paste a YouTube video URL and receive isolated audio stems (vocals, drums, bass, other) as downloadable MP3 files — powered by the Demucs `htdemucs_ft` model.

**Single user flow:** Paste URL → Click "Extract" → Wait → Download 4 MP3 files.

---

## 2. User Flow

```
[User opens app]
    │
    ├── Step 1: Paste YouTube URL in text input
    │   ├── Accepts: standard URLs, youtu.be short links, shorts, embeds, live links
    │   ├── Client-side URL validation (regex check) before submission
    │   └── Show friendly error message if invalid format
    │
    ├── Step 2: Click "Extract Stems" button
    │   ├── Extract video ID from URL (server-side with sed-compatible regex)
    │   ├── Show progress UI: status messages + animated spinner
    │   ├── Execute pipeline:
    │   │   ├── Download audio from YouTube (yt-dlp) → stem_<ID>.m4a
    │   │   ├── Convert to WAV (ffmpeg) → stem_<ID>.wav
    │   │   ├── Run Demucs htdemucs_ft on WAV
    │   │   └── Output: vocals.mp3, drums.mp3, bass.mp3, other.mp3
    │   └── Background task execution (cannot block Streamlit main thread)
    │
    ├── Step 3: Display results
    │   ├── Show stem names, approximate durations, file sizes
    │   ├── Provide individual download buttons (or ZIP archive option)
    │   └── Option to delete intermediate temp files
    │
    └── Step 4: User downloads MP3 files or ZIP
```

---

## 3. Technical Architecture

### 3.1 Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Streamlit (Python) |
| Audio Download | yt-dlp |
| Format Conversion | ffmpeg |
| Stem Separation | Demucs (htdemucs_ft model) |
| Deployment | Streamlit Community Cloud (or local) |
| Python Env | Hermes conda environment (`/opt/anaconda3/envs/Hermes`) |

### 3.2 Python Dependencies

```
yt-dlp
ffmpeg-python (optional, for programmatic ffmpeg calls)
demucs
torchcodec  # REQUIRED — crashes Demucs saving without it
```

### 3.3 Model Details

**Model:** `htdemucs_ft` (Hybrid Transformer Demucs, fine-tuned)

| Attribute | Value |
|-----------|-------|
| Stems output | 4: vocals, drums, bass, other |
| Output format | MP3 (via `--mp3` flag in Demucs CLI) |
| Model size (first download) | ~80MB |
| Processing speed (Apple Silicon CPU) | ~3 min per 4-min song; ~5-15s per 17s clip |
| Sub-models averaged | 4 sub-models (smoother separation) |

### 3.4 Architecture Diagram

```
┌─────────────────┐
│   Streamlit UI  │
│  (Web Browser)  │
└────────┬────────┘
         │ user pastes URL, clicks button
         ▼
┌─────────────────┐
│  Streamlit App  │
│  (Python)       │
│  ┌───────────┐  │
│  │ URL Input │  │
│  └─────┬─────┘  │
│        │        │
│  ┌─────▼─────┐  │
│  │ yt-dlp    │  │  (1) Download audio → stem_<ID>.m4a
│  │ (download)│  │
│  └─────┬─────┘  │
│        │        │
│  ┌─────▼─────┐  │
│  │ ffmpeg    │  │  (2) Convert → stem_<ID>.wav
│  │ (convert) │  │
│  └─────┬─────┘  │
│        │        │
│  ┌─────▼─────┐  │
│  │ Demucs    │  │  (3) Separate into 4 stems → *.mp3
│  │ (ML model)│  │
│  └─────┬─────┘  │
│        │        │
│  ┌─────▼─────┐  │
│  │ Download  │  │  (4) Serve MP3 files for user download
│  │ buttons   │  │
│  └───────────┘  │
└─────────────────┘
         ▲
         │ temp files cleaned up after download
```

---

## 4. Core Features (MVP)

### 4.1 URL Input & Validation
- Single text input field accepting any YouTube URL format
- Server-side video ID extraction using sed-compatible regex:
  ```python
  import re
  def extract_video_id(url):
      pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
      match = re.search(pattern, url)
      return match.group(1) if match else None
  ```
- Display friendly error if URL is invalid or not a YouTube link

### 4.2 Audio Extraction Pipeline
All steps must be wrapped in `st.status()` for user feedback, executing sequentially:

```python
# Pseudocode
def extract_stems(youtube_url):
    # 1. Extract video ID
    video_id = extract_video_id(youtube_url)

    # 2. Download audio from YouTube
    download_path = f"temp/stem_{video_id}.m4a"
    run_yt_dlp(youtube_url, download_path)

    # 3. Convert to WAV
    wav_path = f"temp/stem_{video_id}.wav"
    convert_to_wav(download_path, wav_path)  # ffmpeg: pcm_s16le, 44100Hz, stereo

    # 4. Separate stems with Demucs htdemucs_ft
    output_dir = f"output/stem_{video_id}"
    run_demucs(wav_path, output_dir, model="htdemucs_ft", mp3=True)

    # 5. Return paths to 4 stem MP3 files
    return get_stem_paths(output_dir)
```

### 4.3 Download Options
- Individual download buttons for each stem (vocals, drums, bass, other)
- **ZIP archive** option: compress all 4 stems + metadata (video ID, track name)
- File naming convention: `{stem}_stems.mp3` (e.g., `vocals_stems.mp3`)

### 4.4 User Feedback
- `st.status()` or `st.progress()` showing each pipeline step (downloading → converting → separating)
- Estimated remaining time per step
- Animated processing indicator while Demucs runs (longest step)

---

## 5. Output File Specifications

### 5.1 File Format
| Attribute | Value |
|-----------|-------|
| Format | MP3 |
| Encoding | 128-192 kbps (Demucs default) |
| Sample rate | 44100 Hz (original audio source) |
| Channels | Stereo (2ch) |

### 5.2 Output Structure

```
<app_temp_dir>/stem_<VIDEO_ID>/
├── vocals_stems.mp3      # Lead + backing vocals
├── drums_stems.mp3       # Percussion, drums
├── bass_stems.mp3        # Bass guitar, bass synth
└── other_stems.mp3       # Everything else (guitars, synths, piano, etc.)
```

### 5.3 Naming Convention
- All output files include `_stems` suffix for easy identification
- No video ID in filename (since app is stateless — each request generates its own temp folder)

---

## 6. Constraints & Pitfalls (Must Address)

### 6.1 Hard Requirements
| # | Constraint | Mitigation |
|---|-----------|------------|
| 1 | `torchcodec` REQUIRED for Demucs save | Install in Docker/env image or verify on startup |
| 2 | Demucs runs slowly (~3 min/song) | Must run in background thread; never on main Streamlit process |
| 3 | Model downloads first time (~80MB) | Cache model files; show progress on first run |
| 4 | temp.wav must be deleted after use | Auto-cleanup; never reuse generic `temp.wav` filenames |
| 5 | Output directories must be unique per request | Use UUID or video ID to name each output folder |
| 6 | Cannot block Streamlit main thread | Use Python threading or `concurrent.futures` |
| 7 | macOS `grep -P` not available | Use Python `re.search()` with proper regex instead of shell grep |
| 8 | yt-dlp doesn't support webm format | Force `--audio-format m4a` in download command |

### 6.2 Streaming Considerations
```python
import threading
from queue import Queue

def run_background_pipeline(youtube_url):
    """Run Demucs pipeline in background thread, push progress updates via queue."""
    def _pipeline():
        q.put(("progress", 0.1, "Downloading audio from YouTube..."))
        # yt-dlp step
        q.put(("progress", 0.3, "Converting to WAV..."))
        # ffmpeg step
        q.put(("progress", 0.5, "Separating stems with Demucs (this may take a few minutes)..."))
        # demucs step — LONGEST STEP
        q.put(("progress", 0.9, "Stems ready! Generating download links..."))
        # cleanup & return paths
        q.put(("done", paths))

    thread = threading.Thread(target=_pipeline, daemon=True)
    thread.start()
    return q

# In Streamlit main loop:
q = run_background_pipeline(url)
while not q.empty():
    task, percent, message = q.get()
    st.progress(percent)
    st.write(message)
    if task == "done":
        break
```

### 6.3 Streaming Audio vs. Waiting for Full File
- **Do NOT use `--mp3` with `--two-stems`** — the CLI requires full 4-stem separation before MP3 encoding
- Demucs outputs WAV internally → converts to MP3 at end of process
- For streaming, consider: extract stems as WAV, convert each to MP3 in parallel at end

---

## 7. Optional Enhancements (Post-MVP)

| Feature | Priority | Description |
|---------|----------|-------------|
| Two-stem mode | High | `--two-stems vocals` → get vocals + karaoke backing only (faster) |
| Model selection | Medium | Dropdown: htdemucs_ft / htdemucs / hdemucs_mmi (compare quality) |
| Audio preview | High | Play 30s clip of each stem directly in browser using HTML5 `<audio>` |
| ZIP download | Medium | Compress all 4 stems + track metadata into single downloadable archive |
| Track title display | Low | Use yt-dlp metadata to show song name + artist |
| Batch mode | Low | Accept multiple URLs in one session |
| Key/Pitch detection | Low | Run pitch analysis on "other" stem to show musical key |

---

## 8. Deployment Options

### 8.1 Local Development
```bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate Hermes
pip install streamlit yt-dlp demucs torchcodec ffmpeg-python
streamlit run app.py --server.port 8501
```

### 8.2 Streamlit Community Cloud (Recommended for Sharing)
- Deploy to [share.streamlit.io](https://share.streamlit.io)
- Add `requirements.txt`:
  ```
  streamlit
  yt-dlp
  demucs
  torchcodec
  ```
- Set GPU if available (optional, significantly faster)
- **Caveat:** Model file caching must persist across deployment restarts

### 8.3 Docker Alternative (if GPU needed)
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
COPY requirements.txt .
RUN pip install -r requirements.txt
WORKDIR /app
COPY app.py .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

---

## 9. Testing Plan (Post-MVP)

| Test Case | Expected Behavior |
|-----------|-------------------|
| Valid youtu.be URL | Process completes, 4 stems downloaded |
| Valid standard YouTube URL | Same as above |
| Invalid/malformed URL | Error message, no crash |
| Non-YouTube URL (e.g., Vimeo) | Error message from yt-dlp |
| Very long song (>10 min) | Completes without timeout (background thread handles it) |
| Duplicate URL in same session | New temp folder created, no cross-contamination |
| App restart during processing | Thread completes or is killed on stream rerun |
| torchcodec missing | App shows clear "install torchcodec" error on startup |

---

## 10. Implementation Order (Recommended)

1. **Phase 1:** Scaffold Streamlit app with URL input + validation
2. **Phase 2:** Integrate yt-dlp download + ffmpeg conversion
3. **Phase 3:** Integrate Demucs pipeline (background thread)
4. **Phase 4:** Add download buttons + UI polish (progress, status)
5. **Phase 5:** ZIP archive option + audio preview player
6. **Phase 6:** Deployment (local → cloud)

---

## 11. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **htdemucs_ft as default model** | Best vocal separation (our established preference) |
| **MP3 output, not WAV** | Smaller files for web download, adequate quality |
| **Background thread processing** | Streamlit main loop cannot be blocked (Demucs takes 2-5 min) |
| **Unique temp folders per request** | Prevents cross-contamination between requests |
| **`--mp3` flag in Demucs CLI** | Avoids separate ffmpeg MP3 conversion step (single tool chain) |
| **No user accounts / stateless** | App is ephemeral — no session persistence needed |

---

## 12. Open Questions

- [ ] Should we offer `--two-stems` mode as a toggle? (faster, fewer files)
- [ ] Will we cache the Demucs model in the app's deployment to avoid re-downloading?
- [ ] Should we support non-YouTube audio URLs (SoundCloud, etc.) or stay YouTube-only?
- [ ] Is there a max file-size/time constraint for the free app?
