"""Copy dependency license notices and the bundled FFmpeg's own license/build details."""

import importlib.metadata
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

destination = Path(__file__).resolve().parents[1] / "dist" / "MCPaint" / "third-party"
destination.mkdir(parents=True, exist_ok=True)
for dist in importlib.metadata.distributions():
    name = dist.metadata.get("Name", "unknown")
    for entry in dist.files or []:
        if any(
            token in Path(str(entry)).name.lower()
            for token in ("license", "licence", "copying", "notice")
        ):
            source = Path(dist.locate_file(entry))
            if source.is_file() and source.stat().st_size < 2_000_000:
                target = destination / name / str(entry).replace("..", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
for flag, filename in (
    ("-L", "LICENSE.txt"),
    ("-buildconf", "BUILD-CONFIG.txt"),
    ("-version", "VERSION.txt"),
):
    result = subprocess.run([ffmpeg, flag], capture_output=True, check=True)
    target = destination / "ffmpeg" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.stdout + result.stderr)
