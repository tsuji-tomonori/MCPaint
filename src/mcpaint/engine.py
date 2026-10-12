"""Deterministic raster painting backed by an editable, replayable command journal."""

from __future__ import annotations

import copy
import json
import math
import os
import random
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QRadialGradient

BRUSHES = ("pen", "pencil", "marker", "airbrush", "eraser", "watercolor", "spray", "blur", "smudge")
MAX_POINTS = 20000


def number(value, low, high, name):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: {low}..{high} の有限値が必要です")
    return value


def color(value):
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ValueError("色は #RRGGBB 形式です")
    c = QColor(value)
    if not c.isValid():
        raise ValueError("無効な色です")
    return c.name()


def transparent(width, height):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return image


def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise OSError("PNGへの変換に失敗しました")
    return bytes(data)


@dataclass
class Layer:
    id: str
    name: str
    image: QImage
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    kind: str = "paint"
    group_id: str | None = None
    blend_mode: str = "normal"
    clipping: bool = False
    alpha_lock: bool = False
    mask: object = None
    layer_color: str | None = None
    adjustment: dict | None = None


def draw_stroke(image: QImage, stroke: dict, progress: float = 1.0):
    """Draw in logical canvas pixels; render a time-based partial stroke for replay."""
    points = stroke["points"]
    if progress < 1.0:
        finish = points[-1]["t_ms"] * max(0, progress)
        partial = [points[0]]
        for a, b in zip(points, points[1:], strict=False):
            if b["t_ms"] <= finish:
                partial.append(b)
            else:
                amount = (finish - a["t_ms"]) / max(1e-9, b["t_ms"] - a["t_ms"])
                partial.append({k: a[k] + (b[k] - a[k]) * amount for k in a})
                break
        points = partial
    brush = stroke["brush"]
    width = stroke["size"]
    c = QColor(stroke["color"])
    if brush in ("blur", "smudge"):
        from PIL import Image, ImageDraw, ImageStat

        from .operations import filter_image, pil, qimage

        source = pil(image)
        if brush == "blur":
            mask = transparent(image.width(), image.height())
            draw_stroke(mask, {**stroke, "brush": "airbrush", "color": "#ffffff"}, progress)
            blurred = pil(filter_image(image, {"kind": "blur", "radius": max(0.5, width * 0.2)}))
            image.swap(qimage(Image.composite(blurred, source, pil(mask).getchannel("A"))))
        else:
            carry = None
            for a, b in list(zip(points, points[1:], strict=False)) or [(points[0], points[0])]:
                steps = max(
                    1, math.ceil(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) / max(1, width / 5))
                )
                for j in range(steps + 1):
                    t = j / steps
                    x, y = (
                        round(a["x"] + (b["x"] - a["x"]) * t),
                        round(a["y"] + (b["y"] - a["y"]) * t),
                    )
                    sample = tuple(
                        round(v)
                        for v in ImageStat.Stat(
                            source.crop(
                                (
                                    max(0, x - 1),
                                    max(0, y - 1),
                                    min(source.width, x + 2),
                                    min(source.height, y + 2),
                                )
                            )
                        ).mean
                    )
                    carry = (
                        sample
                        if carry is None
                        else tuple(
                            round(u * 0.75 + v * 0.25) for u, v in zip(carry, sample, strict=True)
                        )
                    )
                    radius = max(
                        1, width * (a["pressure"] + (b["pressure"] - a["pressure"]) * t) / 2
                    )
                    stamp = Image.new("L", source.size)
                    ImageDraw.Draw(stamp).ellipse(
                        (x - radius, y - radius, x + radius, y + radius),
                        fill=round(128 * stroke["opacity"]),
                    )
                    if carry[3]:
                        source = Image.composite(
                            Image.new("RGBA", source.size, carry), source, stamp
                        )
            image.swap(qimage(source))
        return
    # Draw a stroke on its own surface to keep marker opacity independent of sample density.
    target = transparent(image.width(), image.height())
    p = QPainter(target)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if brush in ("airbrush", "watercolor", "spray"):
        rng = random.Random(stroke.get("seed", 0))
        pairs = list(zip(points, points[1:], strict=False)) or [(points[0], points[0])]
        for a, b in pairs:
            distance = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            count = max(1, math.ceil(distance / max(1, width * 0.16)))
            for j in range(count):
                t = j / count
                x, y = a["x"] + (b["x"] - a["x"]) * t, a["y"] + (b["y"] - a["y"]) * t
                radius = width * max(0.1, a["pressure"] + (b["pressure"] - a["pressure"]) * t) / 2
                if brush == "spray":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(c)
                    for _ in range(12):
                        angle = rng.random() * math.tau
                        distance = math.sqrt(rng.random()) * radius
                        dot = max(0.5, width * 0.018 * rng.uniform(0.5, 1.5))
                        p.drawEllipse(
                            QPointF(x + math.cos(angle) * distance, y + math.sin(angle) * distance),
                            dot,
                            dot,
                        )
                    continue
                gradient = QRadialGradient(QPointF(x, y), radius)
                center = QColor(c)
                center.setAlpha(70 if brush == "watercolor" else 100)
                edge = QColor(c)
                edge.setAlpha(0)
                gradient.setColorAt(0, center)
                gradient.setColorAt(1, edge)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(gradient)
                p.drawEllipse(QPointF(x, y), radius, radius)
    else:
        for a, b in list(zip(points, points[1:], strict=False)) or [(points[0], points[0])]:
            pressure = max(0.05, (a["pressure"] + b["pressure"]) / 2)
            size = width * (0.35 + 0.65 * pressure) if brush == "marker" else width * pressure
            pen = QPen(
                c, size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            p.setPen(pen)
            p.setBrush(c)
            if a["x"] == b["x"] and a["y"] == b["y"]:
                p.drawEllipse(QPointF(a["x"], a["y"]), size / 2, size / 2)
            else:
                p.drawLine(QPointF(a["x"], a["y"]), QPointF(b["x"], b["y"]))
        if brush == "pencil":
            # Stable fine-grain gaps: replay and saved projects render exactly the same pixels.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            p.setPen(QPen(QColor(0, 0, 0, 100), 0.65))
            left = max(0, int(min(a["x"] for a in points) - width))
            right = min(image.width(), int(max(a["x"] for a in points) + width))
            top = max(0, int(min(a["y"] for a in points) - width))
            bottom = min(image.height(), int(max(a["y"] for a in points) + width))
            for y in range(top, bottom, 3):
                for x in range(left, right, 3):
                    if (x * 17 + y * 31) % 7 < 2:
                        p.drawPoint(QPointF(x + 0.4, y + 0.2))
    p.end()
    p = QPainter(image)
    if brush == "eraser":
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    p.setOpacity(
        stroke["opacity"] * (0.36 if brush == "marker" else 0.75 if brush == "pencil" else 1)
    )
    p.drawImage(0, 0, target)
    p.end()


class Document:
    def __init__(self, width=1280, height=800, background="#ffffff", base_id=None):
        self.width = int(number(width, 1, 4096, "width"))
        self.height = int(number(height, 1, 4096, "height"))
        self.background = color(background)
        self.base_id = base_id or uuid.uuid4().hex
        self.history = []
        self.cursor = 0
        self.timeline = []
        self.revision = 0
        self.started = time.monotonic()
        self._reset_layers()

    def _reset_layers(self):
        self.layers = [Layer(self.base_id, "レイヤー 1", transparent(self.width, self.height))]
        self.active_id = self.base_id
        self.selection = None

    def layer(self, layer_id=None):
        for layer in self.layers:
            if layer.id == (layer_id or self.active_id):
                return layer
        raise ValueError("レイヤーが見つかりません")

    def normalize(self, command):
        from .operations import BLEND_MODES, OPS, drawable, normalize_filter, unlocked

        c = copy.deepcopy(command)
        op = c.get("op")
        if op in OPS:
            from .operations import normalize

            return normalize(self, c)
        if op == "stroke":
            c["layer_id"] = self.layer(c.get("layer_id")).id
            drawable(self, self.layer(c["layer_id"]))
            if c.get("brush") not in BRUSHES:
                raise ValueError(f"brush は {BRUSHES} から選択してください")
            c["color"] = color(c.get("color", "#24334a"))
            c["size"] = number(c.get("size", 4), 0.5, 300, "size")
            c["opacity"] = number(c.get("opacity", 1), 0, 1, "opacity")
            c["smoothing"] = number(c.get("smoothing", 0), 0, 1, "smoothing")
            c["seed"] = int(number(c.get("seed", 0), 0, 2**32 - 1, "seed"))
            points = c.get("points")
            if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
                raise ValueError(f"点数は 1..{MAX_POINTS} です")
            previous = 0
            clean_points = []
            for i, point in enumerate(points):
                point["x"] = number(point["x"], 0, self.width - 1, "x")
                point["y"] = number(point["y"], 0, self.height - 1, "y")
                point["pressure"] = number(point.get("pressure", 1), 0, 1, "pressure")
                point["t_ms"] = number(point.get("t_ms", i * 16), previous, 120000, "t_ms")
                previous = point["t_ms"]
                clean_points.append({key: point[key] for key in ("x", "y", "pressure", "t_ms")})
            points = clean_points
            c["points"] = points
            # Times are relative to the first point of the stroke.
            offset = points[0]["t_ms"]
            for point in points:
                point["t_ms"] -= offset
        elif op == "add_layer":
            if len(self.layers) >= 64:
                raise ValueError("レイヤー数の上限は64です")
            c["id"] = c.get("id") or uuid.uuid4().hex
            if any(layer.id == c["id"] for layer in self.layers):
                raise ValueError("レイヤーIDが重複しています")
            c["name"] = str(c.get("name", f"レイヤー {len(self.layers) + 1}"))[:100]
            c["kind"] = c.get("kind", "paint")
            if c["kind"] not in ("paint", "group", "adjustment"):
                raise ValueError("レイヤー種別が不正です")
            c["group_id"] = c.get("group_id")
            if c["group_id"]:
                parent = self.layer(c["group_id"])
                unlocked(self, parent)
                if parent.kind != "group":
                    raise ValueError("親はフォルダーを指定してください")
            if c["kind"] == "adjustment":
                c["adjustment"] = normalize_filter(
                    c.get("adjustment", {"kind": "brightness_contrast"})
                )
        elif op in ("update_layer", "delete_layer", "move_layer", "clear_layer"):
            c["layer_id"] = self.layer(c.get("layer_id")).id
            if op == "update_layer":
                c["changes"] = {
                    k: v
                    for k, v in c.get("changes", {}).items()
                    if k
                    in (
                        "name",
                        "visible",
                        "locked",
                        "opacity",
                        "blend_mode",
                        "clipping",
                        "alpha_lock",
                        "group_id",
                        "layer_color",
                        "adjustment",
                    )
                }
                if "opacity" in c["changes"]:
                    c["changes"]["opacity"] = number(c["changes"]["opacity"], 0, 1, "opacity")
                for key in ("visible", "locked", "clipping", "alpha_lock"):
                    if key in c["changes"] and not isinstance(c["changes"][key], bool):
                        raise ValueError(f"{key} は真偽値です")
                if "name" in c["changes"]:
                    c["changes"]["name"] = str(c["changes"]["name"])[:100]
                changes = c["changes"]
                if changes.get("blend_mode", "normal") not in BLEND_MODES:
                    raise ValueError("無効な合成モードです")
                if "layer_color" in changes and changes["layer_color"]:
                    changes["layer_color"] = color(changes["layer_color"])
                if "adjustment" in changes:
                    if self.layer(c["layer_id"]).kind != "adjustment":
                        raise ValueError("補正レイヤーを指定してください")
                    changes["adjustment"] = normalize_filter(changes["adjustment"])
                if "group_id" in changes and changes["group_id"]:
                    parent = self.layer(changes["group_id"])
                    if parent.kind != "group":
                        raise ValueError("親はフォルダーを指定してください")
                    while parent:
                        if parent.id == c["layer_id"]:
                            raise ValueError("フォルダーを循環させることはできません")
                        parent = self.layer(parent.group_id) if parent.group_id else None
            if op == "delete_layer":
                unlocked(self, self.layer(c["layer_id"]))
                removed = self.descendants(c["layer_id"]) | {c["layer_id"]}
                if not any(x.kind == "paint" and x.id not in removed for x in self.layers):
                    raise ValueError("最後の描画レイヤーは削除できません")
            if op == "clear_layer":
                drawable(self, self.layer(c["layer_id"]))
            if op == "move_layer":
                c["index"] = int(number(c["index"], 0, len(self.layers) - 1, "index"))
        else:
            raise ValueError("未知の操作です")
        return c

    def _apply(self, c, progress=1.0):
        from .operations import OPS, apply, restrict_edit

        op = c["op"]
        if op in OPS:
            apply(self, c, progress)
        elif op == "stroke":
            layer = self.layer(c["layer_id"])
            before = layer.image.copy()
            points = c["points"]
            if c.get("smoothing") and len(points) > 2:
                amount = c["smoothing"] * 0.45
                pts = (
                    [points[0]]
                    + [
                        dict(
                            b,
                            x=b["x"] * (1 - amount) + (a["x"] + d["x"]) * amount / 2,
                            y=b["y"] * (1 - amount) + (a["y"] + d["y"]) * amount / 2,
                        )
                        for a, b, d in zip(points, points[1:], points[2:], strict=False)
                    ]
                    + [points[-1]]
                )
                c = {**c, "points": pts}
            draw_stroke(layer.image, c, progress)
            restrict_edit(self, layer, before, layer.image)
        elif op == "add_layer":
            self.layers.append(
                Layer(
                    c["id"],
                    c["name"],
                    transparent(self.width, self.height),
                    kind=c.get("kind", "paint"),
                    group_id=c.get("group_id"),
                    adjustment=c.get("adjustment"),
                )
            )
            self.active_id = c["id"]
        elif op == "update_layer":
            layer = self.layer(c["layer_id"])
            for key, value in c["changes"].items():
                setattr(layer, key, value)
        elif op == "delete_layer":
            removed = self.descendants(c["layer_id"]) | {c["layer_id"]}
            self.layers = [x for x in self.layers if x.id not in removed]
            if self.active_id in removed:
                self.active_id = next(x.id for x in reversed(self.layers) if x.kind == "paint")
        elif op == "move_layer":
            layer = self.layer(c["layer_id"])
            self.layers.remove(layer)
            self.layers.insert(c["index"], layer)
        elif op == "clear_layer":
            self.layer(c["layer_id"]).image.fill(Qt.GlobalColor.transparent)

    def execute(self, command, record=True):
        c = self.normalize(command)
        self._apply(c)
        self.history[self.cursor :] = [c]
        self.cursor += 1
        self.revision += 1
        if record:
            self.timeline.append(
                {
                    "action": "execute",
                    "command": c,
                    "at_ms": round((time.monotonic() - self.started) * 1000),
                }
            )
        return c

    def undo(self, record=True):
        if self.cursor == 0:
            return False
        self.cursor -= 1
        self._rebuild()
        self.revision += 1
        if record:
            self.timeline.append(
                {"action": "undo", "at_ms": round((time.monotonic() - self.started) * 1000)}
            )
        return True

    def redo(self, record=True):
        if self.cursor == len(self.history):
            return False
        self._apply(self.history[self.cursor])
        self.cursor += 1
        self.revision += 1
        if record:
            self.timeline.append(
                {"action": "redo", "at_ms": round((time.monotonic() - self.started) * 1000)}
            )
        return True

    def _rebuild(self):
        active = self.active_id
        self._reset_layers()
        for c in self.history[: self.cursor]:
            self._apply(c)
        if any(layer.id == active for layer in self.layers):
            self.active_id = active

    def composite(self, background=True):
        from .operations import composite_layers

        return composite_layers(self, background=background)

    def descendants(self, layer_id):
        children = {x.id for x in self.layers if x.group_id == layer_id}
        for child in list(children):
            children |= self.descendants(child)
        return children

    def state(self):
        return {
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "revision": self.revision,
            "active_layer": self.active_id,
            "coordinates": "canvas pixels, origin top-left, x right, y down",
            "can_undo": self.cursor > 0,
            "can_redo": self.cursor < len(self.history),
            "recorded_events": len(self.timeline),
            "selection": {
                "active": self.selection is not None,
                "bounds": self.selection.getbbox() if self.selection is not None else None,
            },
            "layers": [
                {
                    "id": x.id,
                    "name": x.name,
                    "visible": x.visible,
                    "locked": x.locked,
                    "opacity": x.opacity,
                    "index": i,
                    "kind": x.kind,
                    "group_id": x.group_id,
                    "blend_mode": x.blend_mode,
                    "clipping": x.clipping,
                    "alpha_lock": x.alpha_lock,
                    "has_mask": x.mask is not None,
                    "layer_color": x.layer_color,
                    "adjustment": x.adjustment,
                }
                for i, x in enumerate(self.layers)
            ],
        }

    def payload(self):
        return {
            "format": "MCPaint",
            "version": 3,
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "base_id": self.base_id,
            "active_id": self.active_id,
            "timeline": self.timeline,
        }

    def save(self, path):
        path = Path(path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically; interrupted saves leave the previous project intact.
        fd, name = tempfile.mkstemp(prefix=".mcpaint-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    self.payload(), f, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return str(path)

    @classmethod
    def load(cls, path):
        if Path(path).stat().st_size > 100 * 1024 * 1024:
            raise ValueError("プロジェクトは100MB以下にしてください")
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("format") != "MCPaint" or payload.get("version") not in (1, 2, 3):
            raise ValueError("対応していないプロジェクト形式です")
        doc = cls(payload["width"], payload["height"], payload["background"], payload["base_id"])
        timeline = payload["timeline"]
        if not isinstance(timeline, list) or len(timeline) > 100000:
            raise ValueError("不正なイベント数です")
        for event in timeline:
            if event["action"] == "execute":
                doc.execute(event["command"], record=False)
            elif event["action"] == "undo":
                doc.undo(record=False)
            elif event["action"] == "redo":
                doc.redo(record=False)
            else:
                raise ValueError("未知の記録操作です")
        doc.timeline = timeline
        doc.active_id = doc.layer(payload.get("active_id", doc.active_id)).id
        elapsed = number(timeline[-1].get("at_ms", 0), 0, 1e12, "at_ms") if timeline else 0
        doc.started = time.monotonic() - elapsed / 1000
        return doc
