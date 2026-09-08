"""Optional OpenAI-powered helpers: smarter scene-cut merging and matching the
user's uploaded clips to the template's segments by visual similarity.

Every function here is a pure enhancement — if it raises AIAssistError, the
caller is expected to fall back to the non-AI behavior (raw scene-detect
segments / manual per-segment uploads) rather than break the app.
"""
from __future__ import annotations

import base64
import json

import cv2
from openai import OpenAI

from core.video_builder import IMAGE_EXTS

_VISION_MODEL = "gpt-4o-mini"


class AIAssistError(RuntimeError):
    """Raised when an AI-assisted step can't produce a usable result."""


def _is_image(path: str) -> bool:
    return path.lower().endswith(tuple(IMAGE_EXTS))


def _client(api_key: str) -> OpenAI:
    if not api_key:
        raise AIAssistError("No OpenAI API key provided.")
    return OpenAI(api_key=api_key)


def _grab_frame(video_path: str, at_seconds: float):
    cap = cv2.VideoCapture(video_path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, at_seconds) * 1000)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise AIAssistError(f"Could not read a frame at {at_seconds:.2f}s from {video_path}")
    return frame


def _thumbnail(path: str, at_seconds: float = 0.3):
    return cv2.imread(path) if _is_image(path) else _grab_frame(path, at_seconds)


def _frame_to_data_uri(frame) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        raise AIAssistError("Could not encode a frame to JPEG for the AI request.")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def refine_segments_ai(api_key: str, video_path: str, segments: list) -> list:
    """Ask GPT-4o-mini to look at each segment's thumbnail and merge boundaries
    that are false-positive cuts (camera shake, flash, tiny motion) rather than
    genuine scene changes."""
    if len(segments) < 2:
        return segments

    client = _client(api_key)
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
    for seg in segments:
        frame = _grab_frame(video_path, seg.start + seg.duration / 2)
        content.append({"type": "text", "text": f"Segment {seg.index}: {seg.duration:.2f}s"})
        content.append({"type": "image_url", "image_url": {"url": _frame_to_data_uri(frame)}})

    try:
        resp = client.chat.completions.create(
            model=_VISION_MODEL,
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
            merged[-1] = type(prev)(index=prev.index, start=prev.start, end=segments[i].end)
    return [type(seg)(index=new_idx, start=seg.start, end=seg.end) for new_idx, seg in enumerate(merged)]


def match_clips_to_segments_ai(api_key: str, video_path: str, segments: list,
                                clip_paths: list[str]) -> dict[int, str]:
    """Ask GPT-4o-mini to assign each uploaded clip to the template segment it
    visually fits best (subject, framing, color, mood). Returns
    {segment_index: clip_path}; segments with no good match are omitted."""
    if not clip_paths:
        return {}

    client = _client(api_key)
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
    for seg in segments:
        frame = _grab_frame(video_path, seg.start + seg.duration / 2)
        content.append({"type": "text", "text": f"S{seg.index} (slot, {seg.duration:.2f}s)"})
        content.append({"type": "image_url", "image_url": {"url": _frame_to_data_uri(frame)}})
    for i, path in enumerate(clip_paths):
        content.append({"type": "text", "text": f"C{i} (user clip)"})
        content.append({"type": "image_url", "image_url": {"url": _frame_to_data_uri(_thumbnail(path))}})

    try:
        resp = client.chat.completions.create(
            model=_VISION_MODEL,
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
