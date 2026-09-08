"""Resolve a self-contained ffmpeg binary via the `imageio-ffmpeg` package so the
app never depends on `apt-get install ffmpeg` (and the Debian mirror issues that
can come with it) at deploy time."""
from __future__ import annotations

import imageio_ffmpeg

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
