# 🎬 Reel Template Remixer

Paste an Instagram Reel link, and this app will:

1. Download the reel and pull out its **background music** and the **timing of
   each visual segment** (scene cuts) — this is the "template".
2. Let you upload your **own videos/photos**, one per segment slot.
3. Render a **final video** that follows the same segment timing and reuses the
   original music, but with your media instead of the original clips.

> ⚠️ Only use reels you own or have permission to reuse. Respect Instagram's
> Terms of Use and the original creator's rights — this tool is for personal/
> educational remixing of your own content, not for redistributing others' work.

## How it works

| Step | File | What it does |
|---|---|---|
| Download | `core/downloader.py` | Uses `yt-dlp` to fetch the reel's video file. |
| Analyze | `core/template_extractor.py` | Uses OpenCV + PySceneDetect to find scene-cut timings, and `ffmpeg` to extract the audio track. |
| Build | `core/video_builder.py` | Uses `ffmpeg` to trim/loop/scale your uploaded media to each segment's duration, concatenates the segments, then re-attaches the extracted audio. |
| UI | `app.py` | Streamlit app tying it all together. |

## Run locally

Requires Python 3.10+ and `ffmpeg`/`ffprobe` on your `PATH`.

```powershell
# Windows: install ffmpeg first, e.g. via winget
winget install --id Gyan.FFmpeg -e

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## Free hosting

### Option A — Streamlit Community Cloud (recommended, simplest)

1. Push this folder to a public (or private) GitHub repo.
2. Go to https://share.streamlit.io → **New app** → pick your repo/branch and
   set the main file to `app.py`.
3. Streamlit Cloud automatically reads `requirements.txt` for Python packages
   and `packages.txt` for system packages — `packages.txt` already lists
   `ffmpeg` so it gets installed on the server.
4. Deploy. You'll get a free `*.streamlit.app` URL with the UI live.

Notes:
- Free tier has limited CPU/RAM and the app sleeps when idle (wakes on visit).
- Large/long reels or many segments may be slow to render on the free tier.

### Option B — Hugging Face Spaces (Streamlit SDK)

1. Create a new Space at https://huggingface.co/spaces → SDK: **Streamlit**.
2. Upload/push the same files (`app.py`, `core/`, `requirements.txt`,
   `packages.txt` — Spaces also honors `packages.txt` for apt packages).
3. The Space builds and serves the app at a free `*.hf.space` URL.

Both options are free, git-based, and need no server management.

## Project structure

```
app.py                    # Streamlit UI
core/
  downloader.py            # Instagram reel download (yt-dlp)
  template_extractor.py     # scene/segment detection + audio extraction
  video_builder.py           # ffmpeg-based clip building, concat, audio mux
requirements.txt          # Python deps
packages.txt              # apt deps for hosted deployments (ffmpeg)
```

## Limitations

- Segment detection is based on visual scene cuts, not Instagram's internal
  "template" metadata (which isn't publicly accessible outside the app), so
  it works best on reels with clear cuts between clips.
- Very short segments (<0.6s) are merged to avoid unusable micro-slots; tune
  `min_scene_len_sec` in `core/template_extractor.py` if needed.
