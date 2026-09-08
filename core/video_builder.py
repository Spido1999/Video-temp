"""Build the final video by filling each timing slot of the reel template with
the user's own photos/videos, then re-attaching the reel's original music.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from core.ffmpeg_bin import FFMPEG_BIN

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def build_segment_clip(media_path: str, duration: float, width: int, height: int,
                        fps: float, out_path: str, speed: float = 1.0,
                        start_offset: float = 0.0) -> None:
    """Render media_path into a silent clip of exactly `duration` seconds, scaled
    and center-cropped to fill width x height (like CSS `object-fit: cover`).
    `speed` re-creates the template's pacing (e.g. 0.5 = slow-motion, 1.75 = sped
    up); ignored for still images, which have no motion to speed up. `start_offset`
    skips into the source video before looping/trimming, letting the user pick
    which part of a longer clip to use."""
    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    is_image = _is_image(media_path)
    if not is_image and speed != 1.0:
        filters.append(f"setpts=PTS/{speed:.4f}")
    filters.append(f"fps={fps}")
    scale_filter = ",".join(filters)

    if is_image:
        cmd = [
            FFMPEG_BIN, "-y", "-loop", "1", "-i", media_path,
            "-t", f"{duration:.3f}", "-vf", scale_filter,
            "-an", "-pix_fmt", "yuv420p", "-c:v", "libx264", out_path,
        ]
    else:
        # -stream_loop -1 repeats the input so clips shorter than the slot still
        # fill it; the -t cut below trims longer clips down to size.
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1"]
        if start_offset > 0:
            cmd += ["-ss", f"{start_offset:.3f}"]
        cmd += [
            "-i", media_path,
            "-t", f"{duration:.3f}", "-vf", scale_filter,
            "-an", "-pix_fmt", "yuv420p", "-c:v", "libx264", out_path,
        ]
    subprocess.run(cmd, check=True, capture_output=True)


def concat_clips(clip_paths: list[str], out_path: str, work_dir: str) -> None:
    list_file = os.path.join(work_dir, "concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [
        FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy", out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def mux_audio(silent_video_path: str, audio_path: Optional[str], out_path: str,
              total_duration: float) -> None:
    if not audio_path:
        subprocess.run(
            [FFMPEG_BIN, "-y", "-i", silent_video_path, "-c", "copy", out_path],
            check=True, capture_output=True,
        )
        return
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", silent_video_path,
        "-stream_loop", "-1", "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac",
        "-t", f"{total_duration:.3f}",
        "-shortest",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def build_final_video(segment_media: dict, segments: list, width: int, height: int,
                       fps: float, audio_path: Optional[str], out_path: str,
                       work_dir: str, start_offsets: Optional[dict] = None,
                       progress_cb=None) -> str:
    """segment_media maps segment index -> path to the user's replacement media.
    Segments without an entry are skipped (kept out of the final render).
    `start_offsets` optionally maps segment index -> seconds to skip into that
    clip before use. `progress_cb`, if given, is called as progress_cb(done, total)
    after each segment is rendered."""
    start_offsets = start_offsets or {}
    targets = [seg for seg in segments if segment_media.get(seg.index)]
    if not targets:
        raise ValueError("No media provided for any segment.")

    clip_paths = []
    for done, seg in enumerate(targets, start=1):
        media_path = segment_media[seg.index]
        clip_out = os.path.join(work_dir, f"clip_{seg.index}.mp4")
        build_segment_clip(
            media_path, seg.duration, width, height, fps, clip_out,
            speed=getattr(seg, "speed", 1.0),
            start_offset=start_offsets.get(seg.index, 0.0),
        )
        clip_paths.append(clip_out)
        if progress_cb:
            progress_cb(done, len(targets))

    concat_out = os.path.join(work_dir, "concat_silent.mp4")
    concat_clips(clip_paths, concat_out, work_dir)

    total_duration = sum(seg.duration for seg in segments if seg.index in segment_media)
    mux_audio(concat_out, audio_path, out_path, total_duration)
    return out_path
