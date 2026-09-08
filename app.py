import os
import tempfile

import streamlit as st

from core.ai_assist import AIAssistError, match_clips_to_segments_ai, refine_segments_ai
from core.downloader import download_reel
from core.template_extractor import detect_segments, extract_audio, get_video_info
from core.video_builder import build_final_video

st.set_page_config(page_title="Reel Template Remixer", page_icon="🎬", layout="centered")
st.title("🎬 Reel Template Remixer")
st.caption(
    "Paste an Instagram Reel link to grab its timing template and music, "
    "then drop in your own clips/photos to render a new video with the same structure."
)
st.info(
    "Only use reels you own or have permission to reuse — respect Instagram's "
    "Terms of Use and the original creator's rights.",
    icon="⚠️",
)

if "work_dir" not in st.session_state:
    st.session_state.work_dir = tempfile.mkdtemp(prefix="reel_")

WORK_DIR = st.session_state.work_dir

with st.expander("🤖 AI enhancements (optional, needs an OpenAI API key)"):
    default_key = st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key = st.text_input(
        "OpenAI API key",
        value=st.session_state.get("openai_api_key", default_key),
        type="password",
        help="Used only for this session to call OpenAI; never written to disk.",
    )
    st.session_state.openai_api_key = api_key
    refine_with_ai = st.checkbox(
        "Refine scene detection with AI (merges false-positive cuts)",
        value=False, disabled=not api_key,
    )
    automatch_with_ai = st.checkbox(
        "Auto-match my uploaded clips to segments with AI",
        value=False, disabled=not api_key,
    )
    st.session_state.refine_with_ai = refine_with_ai
    st.session_state.automatch_with_ai = automatch_with_ai

st.header("1. Fetch the template")
url = st.text_input("Instagram Reel URL", placeholder="https://www.instagram.com/reel/xxxxxxxxx/")

if st.button("Download & analyze", type="primary", disabled=not url):
    with st.spinner("Downloading reel..."):
        try:
            result = download_reel(url, WORK_DIR)
        except Exception as exc:
            st.error(f"Could not download that reel: {exc}")
            st.stop()

    with st.spinner("Extracting music and scene timing..."):
        try:
            info = get_video_info(result.video_path)
            audio_path = extract_audio(result.video_path, os.path.join(WORK_DIR, "template_audio.m4a"))
            segments = detect_segments(result.video_path)
        except Exception as exc:
            st.error(f"Could not analyze that reel: {exc}")
            st.stop()

        if st.session_state.get("refine_with_ai") and st.session_state.get("openai_api_key"):
            try:
                segments = refine_segments_ai(st.session_state.openai_api_key, result.video_path, segments)
            except AIAssistError as exc:
                st.warning(f"AI scene refinement skipped, using raw scene detection: {exc}")

    st.session_state.template = {
        "video_path": result.video_path,
        "title": result.title,
        "info": info,
        "audio_path": audio_path,
        "segments": segments,
    }
    st.session_state.pop("output_path", None)
    st.session_state.pop("uploads", None)
    st.success(f"Found {len(segments)} segment(s) in '{result.title}'.")

template = st.session_state.get("template")

if template:
    info = template["info"]
    segments = template["segments"]

    st.video(template["video_path"])
    st.write(
        f"Resolution: {info.width}x{info.height} · {info.fps:.1f} fps · "
        f"Total duration: {info.duration:.1f}s"
    )
    if template["audio_path"]:
        st.audio(template["audio_path"])
    else:
        st.info("This reel has no separate audio track.")

    st.header("2. Fill each segment with your media")

    uploads: dict = st.session_state.get("uploads", {})

    if st.session_state.get("automatch_with_ai") and api_key:
        st.caption("Upload a pool of clips/photos — AI will assign the best one to each segment.")
        pool_files = st.file_uploader(
            "Your clips/photos pool",
            type=["mp4", "mov", "m4v", "jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True, key="pool_uploader",
        )
        pool_paths = []
        for f in pool_files or []:
            dest = os.path.join(WORK_DIR, f"pool_{f.name}")
            with open(dest, "wb") as out:
                out.write(f.getbuffer())
            pool_paths.append(dest)

        if st.button("Run AI auto-match", disabled=not pool_paths):
            with st.spinner("Matching your clips to segments..."):
                try:
                    uploads = match_clips_to_segments_ai(api_key, template["video_path"], segments, pool_paths)
                    st.session_state.uploads = uploads
                    st.success(f"AI matched {len(uploads)} of {len(segments)} segment(s).")
                except AIAssistError as exc:
                    st.error(f"AI matching failed: {exc}")

        if uploads:
            st.write("Current assignment (override any slot manually below if needed):")
            for seg in segments:
                path = uploads.get(seg.index)
                st.write(f"- Segment {seg.index + 1}: {os.path.basename(path) if path else '— unmatched —'}")

    st.caption("Manual — upload/replace media for any segment individually. Shorter clips are looped, longer ones trimmed to fit.")
    for seg in segments:
        file = st.file_uploader(
            f"Segment {seg.index + 1} — {seg.duration:.1f}s",
            type=["mp4", "mov", "m4v", "jpg", "jpeg", "png", "webp"],
            key=f"upload_{seg.index}",
        )
        if file is not None:
            dest = os.path.join(WORK_DIR, f"user_{seg.index}_{file.name}")
            with open(dest, "wb") as f:
                f.write(file.getbuffer())
            uploads[seg.index] = dest
    st.session_state.uploads = uploads

    st.header("3. Generate")
    ready = len(uploads) > 0
    if st.button("Render final video", type="primary", disabled=not ready):
        with st.spinner("Rendering..."):
            try:
                out_path = build_final_video(
                    segment_media=uploads,
                    segments=segments,
                    width=info.width,
                    height=info.height,
                    fps=info.fps,
                    audio_path=template["audio_path"],
                    out_path=os.path.join(WORK_DIR, "final_output.mp4"),
                    work_dir=WORK_DIR,
                )
                st.session_state.output_path = out_path
            except Exception as exc:
                st.error(f"Rendering failed: {exc}")

if st.session_state.get("output_path"):
    st.header("Result")
    st.video(st.session_state.output_path)
    with open(st.session_state.output_path, "rb") as f:
        st.download_button("Download final video", f, file_name="final_reel.mp4", mime="video/mp4")
