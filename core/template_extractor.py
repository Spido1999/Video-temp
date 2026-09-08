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
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector

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


def detect_segments(video_path: str, min_scene_len_sec: float = 0.6) -> list[Segment]:
    """Split the reel into visual segments based on scene cuts. Falls back to a
    single segment spanning the whole clip when no cuts are detected."""
    info = get_video_info(video_path)
    min_scene_len = max(1, int(min_scene_len_sec * info.fps))

    video = open_video(video_path, backend="pyav")
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=min_scene_len))
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        return [Segment(index=0, start=0.0, end=info.duration)]

    segments = []
    for i, (start_tc, end_tc) in enumerate(scene_list):
        segments.append(Segment(index=i, start=start_tc.get_seconds(), end=end_tc.get_seconds()))
    return segments
