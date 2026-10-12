"""Replay the journal including partial strokes, layer edits, undo and redo."""

from itertools import chain
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt

from .engine import Document, number


def replay_frames(doc, max_frames=240, max_size=800):
    max_frames = int(number(max_frames, 2, 360, "max_frames"))
    max_size = int(number(max_size, 64, 960, "max_size"))
    events = doc.timeline
    weights = []
    for event in events:
        c = event.get("command", {})
        weights.append(
            max(150, min(2500, c["points"][-1]["t_ms"])) if c.get("op") == "stroke" else 150
        )
    total = sum(weights) or 1
    # Allocate samples over a compact playback timeline. Every sampled frame reconstructs
    # all prior events, so unsampled edits still affect the eventual result.
    state = Document(doc.width, doc.height, doc.background, doc.base_id)
    index = 0
    start = 0
    for i in range(max_frames):
        moment = total * i / (max_frames - 1)
        while index < len(events) and start + weights[index] <= moment:
            event = events[index]
            if event["action"] == "execute":
                state.execute(event["command"], record=False)
            elif event["action"] == "undo":
                state.undo(record=False)
            else:
                state.redo(record=False)
            start += weights[index]
            index += 1
        frame = state.composite()
        if i > 0 and index < len(events):
            event = events[index]
            c = event.get("command", {})
            if c.get("op") == "stroke":
                layer = state.layer(c["layer_id"])
                saved = layer.image
                layer.image = saved.copy()
                state._apply(c, (moment - start) / weights[index])
                frame = state.composite()
                layer.image = saved
        frame = frame.scaled(
            max_size,
            max_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        rgba = frame.convertToFormat(frame.Format.Format_RGBA8888)
        yield Image.frombytes(
            "RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits())
        ).convert("RGB")


def export_timelapse(doc, path, fps=20, max_frames=240, max_size=800):
    fps = int(number(fps, 1, 60, "fps"))
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".gif":
        frames = [f.quantize(colors=128) for f in replay_frames(doc, max_frames, max_size)]
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=round(1000 / fps),
            loop=0,
            disposal=2,
            optimize=False,
        )
    elif path.suffix.lower() == ".mp4":
        import imageio_ffmpeg

        frames = iter(replay_frames(doc, max_frames, max_size))
        first = next(frames)
        # H.264 requires even dimensions. Pad, preserving the entire canvas.
        w, h = first.size
        size = (w + w % 2, h + h % 2)
        writer = imageio_ffmpeg.write_frames(
            str(path),
            size,
            fps=fps,
            codec="libx264",
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            macro_block_size=1,
            ffmpeg_log_level="error",
        )
        writer.send(None)
        try:
            for frame in chain([first], frames):
                padded = Image.new("RGB", size, doc.background)
                padded.paste(frame)
                writer.send(padded.tobytes())
        finally:
            writer.close()
    else:
        raise ValueError("タイムラプスは .gif または .mp4 を指定してください")
    return str(path)
