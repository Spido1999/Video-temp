"""Analyze a downloaded reel: pull out its background audio and the timing of
each visual segment (scene) so a new video can later be built using the same
structure (same slot durations, same music).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

import av
import numpy as np

from core.ffmpeg_bin import FFMPEG_BIN


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float


@dataclass
class Segment:
    index: int
    start: float
    end: float
    speed: float = 1.0
    speed_label: str = "normal"

    @property
    def duration(self) -> float:
        return self.end - self.start


def get_video_info(video_path: str) -> VideoInfo:
    container = av.open(video_path)
    try:
        stream = container.streams.video[0]
        width, height = stream.width, stream.height
        fps = float(stream.average_rate) if stream.average_rate else 30.0
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = float(container.duration / av.time_base)
        else:
            duration = 0.0
    finally:
        container.close()
    return VideoInfo(width=width, height=height, fps=fps, duration=duration)


def extract_audio(video_path: str, out_audio_path: str) -> Optional[str]:
    """Extract the audio track to out_audio_path (AAC). Returns None if the
    source clip has no audio stream at all (or ffmpeg otherwise can't extract one)."""
    cmd = [
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vn", "-acodec", "aac", "-b:a", "192k", out_audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_audio_path):
        return None
    return out_audio_path


def _classify_speed(ratio: float) -> tuple[str, float]:
    """Map a segment's motion-energy ratio (vs. the reel's median) to an
    apparent pacing label + a suggested playback-speed multiplier to reapply
    to replacement footage."""
    if ratio < 0.65:
        return "slow-motion", 0.5
    if ratio > 1.6:
        return "fast", 1.75
    return "normal", 1.0


def detect_segments(video_path: str, min_scene_len_sec: float = 0.6, threshold: float = 30.0) -> list[Segment]:
    """Split the reel into visual segments by diffing consecutive downsampled
    frames (a lightweight, dependency-free stand-in for PySceneDetect's
    ContentDetector). Falls back to a single segment spanning the whole clip
    when no cuts are found. Each segment's `speed`/`speed_label` is a rough
    guess at whether that shot looks like slow-motion or sped-up/timelapse,
    based on how much it moves relative to the rest of the reel."""
    info = get_video_info(video_path)

    boundaries: list[float] = []
    frame_diffs: list[tuple[float, float]] = []  # (time, diff from previous frame)
    container = av.open(video_path)
    try:
        stream = container.streams.video[0]
        prev_arr = None
        last_cut_time = 0.0
        for frame in container.decode(stream):
            t = float(frame.time) if frame.time is not None else 0.0
            arr = np.asarray(
                frame.to_image().convert("RGB").resize((64, 36)), dtype=np.float32
            )
            if prev_arr is not None:
                diff = float(np.abs(arr - prev_arr).mean())
                frame_diffs.append((t, diff))
                if diff > threshold and (t - last_cut_time) >= min_scene_len_sec:
                    boundaries.append(t)
                    last_cut_time = t
            prev_arr = arr
    finally:
        container.close()

    bounds = [0.0] + boundaries + [info.duration]
    raw_bounds = [
        (bounds[i], bounds[i + 1])
        for i in range(len(bounds) - 1)
        if bounds[i + 1] > bounds[i]
    ] or [(0.0, info.duration)]

    def _avg_motion(start: float, end: float) -> Optional[float]:
        vals = [d for t, d in frame_diffs if start <= t < end]
        return sum(vals) / len(vals) if vals else None

    segment_avgs = [_avg_motion(start, end) for start, end in raw_bounds]
    known_avgs = sorted(v for v in segment_avgs if v is not None)
    baseline = known_avgs[len(known_avgs) // 2] if known_avgs else None

    segments = []
    for i, (start, end) in enumerate(raw_bounds):
        avg = segment_avgs[i]
        if baseline and avg is not None:
            label, speed = _classify_speed(avg / baseline)
        else:
            label, speed = "normal", 1.0
        segments.append(Segment(index=i, start=start, end=end, speed=speed, speed_label=label))
    return segments
