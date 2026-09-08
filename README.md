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
| Analyze | `core/template_extractor.py` | Uses OpenCV + PySceneDetect to find scene-cut timings, and a bundled `ffmpeg` binary to extract the audio track. |
| Build | `core/video_builder.py` | Uses the bundled `ffmpeg` binary to trim/loop/scale your uploaded media to each segment's duration, concatenates the segments, then re-attaches the extracted audio. |
| AI (optional) | `core/ai_assist.py` | Uses the OpenAI API (GPT-4o-mini vision) to (a) merge false-positive scene cuts and (b) auto-match your uploaded clips to the best-fitting segment. |
| UI | `app.py` | Streamlit app tying it all together. |

## Optional AI enhancements

Expand **"🤖 AI enhancements"** in the app and paste an OpenAI API key to unlock:

- **Refine scene detection with AI** — sends a thumbnail of each detected segment
  to GPT-4o-mini and merges boundaries that look like the same continuous shot
  falsely split by camera shake/flash/motion, instead of a real cut.
- **Auto-match my uploaded clips to segments with AI** — upload a pool of your
  clips/photos (instead of one per slot) and GPT-4o-mini assigns each one to
  the segment it visually fits best (subject/framing/color/mood). You can still
  override any assignment manually afterward.

Both features are pure enhancements: if the API key is missing or a call
fails, the app falls back to the plain scene-detection/manual-upload flow
automatically — nothing breaks.

**Never commit an API key.** For local runs, paste it into the app's password
field each session (kept only in memory, never written to disk). For a hosted
deployment, use the platform's secrets manager:

- Streamlit Community Cloud: App settings → **Secrets** → add
  `OPENAI_API_KEY = "sk-..."`. The app reads it automatically via `st.secrets`.
- Hugging Face Spaces: Space settings → **Repository secrets** → add
  `OPENAI_API_KEY`.

## Run locally

Requires Python 3.10+. `ffmpeg` itself is **not** required on your system —
the `imageio-ffmpeg` package (in `requirements.txt`) bundles a static binary.

```powershell
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
3. Streamlit Cloud reads `requirements.txt` for Python packages — that's all
   that's needed; there's no `packages.txt`/apt step, so it isn't affected by
   the base image's Debian mirror issues.
4. Deploy. You'll get a free `*.streamlit.app` URL with the UI live.

Notes:
- Free tier has limited CPU/RAM and the app sleeps when idle (wakes on visit).
- Large/long reels or many segments may be slow to render on the free tier.

### Option B — Hugging Face Spaces (Streamlit SDK)

1. Create a new Space at https://huggingface.co/spaces → SDK: **Streamlit**.
2. Upload/push the same files (`app.py`, `core/`, `requirements.txt`).
3. The Space builds and serves the app at a free `*.hf.space` URL.

Both options are free, git-based, and need no server management.

## Project structure

```
app.py                    # Streamlit UI
core/
  downloader.py            # Instagram reel download (yt-dlp)
  template_extractor.py     # scene/segment detection + audio extraction
  video_builder.py           # ffmpeg-based clip building, concat, audio mux
  ai_assist.py                # optional OpenAI-powered refinement + matching
  ffmpeg_bin.py                # resolves the bundled static ffmpeg binary
requirements.txt          # Python deps (includes imageio-ffmpeg, no system ffmpeg needed)
```

## Push to GitHub

```powershell
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

Then point Streamlit Community Cloud / Hugging Face Spaces at that repo (see
"Free hosting" above).

## Limitations

- Segment detection is based on visual scene cuts, not Instagram's internal
  "template" metadata (which isn't publicly accessible outside the app), so
  it works best on reels with clear cuts between clips.
- Very short segments (<0.6s) are merged to avoid unusable micro-slots; tune
  `min_scene_len_sec` in `core/template_extractor.py` if needed.
