"""Optional OpenAI-powered helpers: smarter scene-cut merging and matching the
user's uploaded clips to the template's segments by visual similarity.

Every function here is a pure enhancement — if it raises AIAssistError, the
caller is expected to fall back to the non-AI behavior (raw scene-detect
segments / manual per-segment uploads) rather than break the app.
"""
from __future__ import annotations

import base64
import io
import json

import av
from openai import OpenAI
from PIL import Image

from core.video_builder import IMAGE_EXTS

DEFAULT_VISION_MODEL = "gpt-4o-mini"
# Roughly in order of increasing accuracy/cost; gpt-4o-mini is fastest & cheapest.
AVAILABLE_VISION_MODELS = {
    "Fast & cheap (gpt-4o-mini)": "gpt-4o-mini",
    "More accurate (gpt-4o)": "gpt-4o",
    "Newer, strong reasoning (gpt-4.1)": "gpt-4.1",
}


class AIAssistError(RuntimeError):
    """Raised when an AI-assisted step can't produce a usable result."""


def _is_image(path: str) -> bool:
    return path.lower().endswith(tuple(IMAGE_EXTS))


def _client(api_key: str) -> OpenAI:
    if not api_key:
        raise AIAssistError("No OpenAI API key provided.")
    return OpenAI(api_key=api_key)


def _grab_frames_at(video_path: str, times: list[float]) -> list[Image.Image]:
    """Decode video_path once and return the frame closest to each requested
    timestamp (order of `times` is preserved in the returned list)."""
    order = sorted(range(len(times)), key=lambda i: times[i])
    results: list = [None] * len(times)

    container = av.open(video_path)
    try:
        stream = container.streams.video[0]
        pos = 0
        last_frame = None
        for frame in container.decode(stream):
            t = float(frame.time) if frame.time is not None else 0.0
            while pos < len(order) and t >= times[order[pos]]:
                results[order[pos]] = frame.to_image()
                pos += 1
            last_frame = frame
            if pos >= len(order):
                break
        if last_frame is not None:
            for i in range(len(results)):
                if results[i] is None:
                    results[i] = last_frame.to_image()
    finally:
        container.close()

    missing = [i for i, r in enumerate(results) if r is None]
    if missing:
        raise AIAssistError(f"Could not decode frames for timestamps: {missing}")
    return results


def _thumbnail(path: str, at_seconds: float = 0.3) -> Image.Image:
    if _is_image(path):
        return Image.open(path).convert("RGB")
    return _grab_frames_at(path, [at_seconds])[0]


def _frame_to_data_uri(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=70)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _image_content(image: Image.Image) -> dict:
    # detail="high" lets the model examine finer detail per frame (more accurate,
    # slightly more expensive) instead of the low-res default.
    return {"type": "image_url", "image_url": {"url": _frame_to_data_uri(image), "detail": "high"}}


def refine_segments_ai(api_key: str, video_path: str, segments: list, model: str = DEFAULT_VISION_MODEL) -> list:
    """Ask a GPT vision model to look at each segment's thumbnail and merge boundaries
    that are false-positive cuts (camera shake, flash, tiny motion) rather than
    genuine scene changes."""
    if len(segments) < 2:
        return segments

    client = _client(api_key)
    mid_times = [seg.start + seg.duration / 2 for seg in segments]
    frames = _grab_frames_at(video_path, mid_times)
    content = [{
        "type": "text",
        "text": (
            "Below are thumbnail frames from candidate video segments, in order, "
            "each with its duration. Some adjacent segments may actually be the same "
            "continuous shot that got falsely split (camera shake, flash, small motion). "
            "For each boundary between consecutive segments, decide if it is a real cut "
            "(different shot) or a false split (should be merged). "
            'Respond ONLY with JSON: {"keep_boundary": [true, false, ...]} '
            "with exactly (number_of_segments - 1) entries, in order."
        ),
    }]
    for seg, frame in zip(segments, frames):
        content.append({"type": "text", "text": f"Segment {seg.index}: {seg.duration:.2f}s"})
        content.append(_image_content(frame))

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        keep = json.loads(resp.choices[0].message.content)["keep_boundary"]
        if len(keep) != len(segments) - 1:
            raise ValueError(f"Expected {len(segments) - 1} boundary decisions, got {len(keep)}")
    except Exception as exc:
        raise AIAssistError(f"AI scene refinement failed: {exc}") from exc

    merged = [segments[0]]
    for i, keep_this in enumerate(keep, start=1):
        if keep_this:
            merged.append(segments[i])
        else:
            prev = merged[-1]
            merged[-1] = type(prev)(
                index=prev.index, start=prev.start, end=segments[i].end,
                speed=prev.speed, speed_label=prev.speed_label,
            )
    return [
        type(seg)(index=new_idx, start=seg.start, end=seg.end, speed=seg.speed, speed_label=seg.speed_label)
        for new_idx, seg in enumerate(merged)
    ]


def match_clips_to_segments_ai(api_key: str, video_path: str, segments: list,
                                clip_paths: list[str], model: str = DEFAULT_VISION_MODEL) -> dict[int, str]:
    """Ask a GPT vision model to assign each uploaded clip to the template segment it
    visually fits best (subject, framing, color, mood). Returns
    {segment_index: clip_path}; segments with no good match are omitted."""
    if not clip_paths:
        return {}

    client = _client(api_key)
    mid_times = [seg.start + seg.duration / 2 for seg in segments]
    seg_frames = _grab_frames_at(video_path, mid_times)
    content = [{
        "type": "text",
        "text": (
            "You are matching a user's raw clips/photos to slots (S0, S1, ...) in a "
            "video template, based on visual similarity (subject, framing, color, mood). "
            "Each clip (C0, C1, ...) can be used at most once; leave a slot unmatched if "
            "nothing fits well. Maximize good coverage overall. "
            'Respond ONLY with JSON: {"assignments": {"<segment_index>": <clip_index>}} '
            "using the 0-based indices shown below."
        ),
    }]
    for seg, frame in zip(segments, seg_frames):
        content.append({"type": "text", "text": f"S{seg.index} (slot, {seg.duration:.2f}s)"})
        content.append(_image_content(frame))
    for i, path in enumerate(clip_paths):
        content.append({"type": "text", "text": f"C{i} (user clip)"})
        content.append(_image_content(_thumbnail(path)))

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw_assignments = json.loads(resp.choices[0].message.content)["assignments"]
    except Exception as exc:
        raise AIAssistError(f"AI clip matching failed: {exc}") from exc

    valid_segment_indices = {seg.index for seg in segments}
    used_clips: set[int] = set()
    assignments: dict[int, str] = {}
    for seg_idx_str, clip_idx in raw_assignments.items():
        try:
            seg_idx, clip_idx = int(seg_idx_str), int(clip_idx)
        except (TypeError, ValueError):
            continue
        if seg_idx not in valid_segment_indices or clip_idx in used_clips:
            continue
        if not (0 <= clip_idx < len(clip_paths)):
            continue
        assignments[seg_idx] = clip_paths[clip_idx]
        used_clips.add(clip_idx)
    return assignments


def classify_speed_ai(api_key: str, video_path: str, segments: list,
                       model: str = DEFAULT_VISION_MODEL) -> dict[int, tuple[str, float]]:
    """Ask a GPT vision model to judge each segment's apparent playback pacing
    (slow-motion, normal, or sped-up/timelapse) from its start/mid/end frames, using
    motion blur and how much changes between them relative to the duration. Returns
    {segment_index: (label, multiplier)}; segments it couldn't judge are omitted."""
    if not segments:
        return {}

    client = _client(api_key)
    times: list[float] = []
    for seg in segments:
        times.append(seg.start + 0.1 * seg.duration)
        times.append(seg.start + 0.5 * seg.duration)
        times.append(seg.start + 0.9 * seg.duration)
    frames = _grab_frames_at(video_path, times)

    content = [{
        "type": "text",
        "text": (
            "For each video segment below, you'll see three frames (start, middle, "
            "end), plus its duration. Judge whether the segment looks like it plays "
            "in slow-motion, is sped-up/timelapse, or is normal speed, based on motion "
            "blur and how much changes between the frames relative to the duration. "
            'Respond ONLY with JSON: {"speeds": {"<segment_index>": '
            '{"label": "slow-motion|normal|fast", "multiplier": <float>}}}, '
            "where multiplier is a suggested playback-speed factor for replacement "
            "footage (e.g. 0.5 for slow-motion, 1.0 for normal, 1.75 for fast/sped-up)."
        ),
    }]
    for i, seg in enumerate(segments):
        content.append({"type": "text", "text": f"Segment {seg.index}: {seg.duration:.2f}s, start frame"})
        content.append(_image_content(frames[i * 3]))
        content.append({"type": "text", "text": f"Segment {seg.index}: middle frame"})
        content.append(_image_content(frames[i * 3 + 1]))
        content.append({"type": "text", "text": f"Segment {seg.index}: end frame"})
        content.append(_image_content(frames[i * 3 + 2]))

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)["speeds"]
    except Exception as exc:
        raise AIAssistError(f"AI speed classification failed: {exc}") from exc

    valid_indices = {seg.index for seg in segments}
    results: dict[int, tuple[str, float]] = {}
    for seg_idx_str, entry in raw.items():
        try:
            seg_idx = int(seg_idx_str)
            label = str(entry["label"])
            multiplier = max(0.1, min(4.0, float(entry["multiplier"])))
        except (TypeError, ValueError, KeyError):
            continue
        if seg_idx in valid_indices:
            results[seg_idx] = (label, multiplier)
    return results
