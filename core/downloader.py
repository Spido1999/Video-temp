"""Download an Instagram Reel (video + metadata) using yt-dlp."""
from __future__ import annotations

import os
from dataclasses import dataclass

import yt_dlp


@dataclass
class DownloadResult:
    video_path: str
    title: str


def download_reel(url: str, out_dir: str) -> DownloadResult:
    """Download the given Instagram Reel URL into out_dir and return the video path.

    Raises whatever exception yt-dlp raises (e.g. yt_dlp.utils.DownloadError) if
    the URL is invalid, private, or unavailable.
    """
    os.makedirs(out_dir, exist_ok=True)
    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "mp4/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_path = ydl.prepare_filename(info)
        if not os.path.exists(video_path):
            # yt-dlp may have merged/remuxed into a different extension.
            base, _ = os.path.splitext(video_path)
            for ext in (".mp4", ".mkv", ".webm"):
                candidate = base + ext
                if os.path.exists(candidate):
                    video_path = candidate
                    break
        if not os.path.exists(video_path):
            raise FileNotFoundError("Download reported success but the output file was not found.")
        return DownloadResult(video_path=video_path, title=info.get("title") or info.get("id") or "reel")
