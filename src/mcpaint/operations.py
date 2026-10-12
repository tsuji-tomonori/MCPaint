"""Selection, color and geometry tools. Every normalized operation is replayable."""

import base64
import io
import math
import uuid

import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
    QTransform,
)

BLEND_MODES = (
    "normal",
    "multiply",
    "screen",
    "overlay",
    "soft_light",
    "hard_light",
    "add",
    "darken",
    "lighten",
    "color_dodge",
    "color_burn",
    "linear_burn",
    "difference",
)
FILTERS = (
    "blur",
    "brightness_contrast",
    "hue_saturation",
    "color_balance",
    "tone_curve",
    "gradient_map",
)
OPS = {
    "select_region",
    "selection_edit",
    "fill",
    "shape",
    "gradient",
    "transform",
    "filter",
    "mask",
    "mask_stroke",
    "duplicate_layer",
    "merge_down",
    "import_image",
    "import_image_layer",
    "mesh_warp",
    "flatten_group",
}


def pil(image):
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()))


def qimage(image):
    image = image.convert("RGBA")
    return (
        QImage(
            image.tobytes(),
            image.width,
            image.height,
            image.width * 4,
            QImage.Format.Format_RGBA8888,
        )
        .copy()
        .convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    )


def mask_image(mask):
    result = Image.new("RGBA", mask.size, "white")
    result.putalpha(mask)
    return qimage(result)


def solid_mask(doc, value=255):
    return Image.new("L", (doc.width, doc.height), value)


def apply_alpha(image, mask):
    result = pil(image)
    result.putalpha(ImageChops.multiply(result.getchannel("A"), mask))
    return qimage(result)


def point(doc, value):
    from .engine import number

    if len(value) != 2:
        raise ValueError("点は [x,y] です")
    return [number(value[0], 0, doc.width - 1, "x"), number(value[1], 0, doc.height - 1, "y")]


def bounds(doc, value):
    from .engine import number

    if len(value) != 4:
        raise ValueError("範囲は [x,y,width,height] です")
    x, y, w, h = [number(v, 0, 4096, "rect") for v in value]
    if w <= 0 or h <= 0 or x + w > doc.width or y + h > doc.height:
        raise ValueError("範囲はキャンバス内に指定してください")
    return [x, y, w, h]


def unlocked(doc, layer):
    if layer.locked:
        raise ValueError("レイヤーはロックされています")
    parent = layer.group_id
    while parent:
        ancestor = doc.layer(parent)
        if ancestor.locked:
            raise ValueError("フォルダーはロックされています")
        parent = ancestor.group_id


def drawable(doc, layer):
    unlocked(doc, layer)
    if layer.kind != "paint":
        raise ValueError("描画用レイヤーを選択してください")


def normalize(doc, c):
    from .engine import color, number

    op = c["op"]
    if op not in OPS:
        raise ValueError("未知の操作です")
    if op not in ("select_region", "selection_edit", "import_image_layer"):
        layer = doc.layer(c.get("layer_id"))
        c["layer_id"] = layer.id
        if op in ("fill", "shape", "gradient", "transform", "filter", "import_image", "mesh_warp"):
            drawable(doc, layer)
        elif op != "duplicate_layer":
            unlocked(doc, layer)
    if op in ("shape", "select_region"):
        kind = c.get("kind", "rect")
        allowed = (
            ("rect", "ellipse", "polygon", "wand", "layer_alpha")
            if op == "select_region"
            else ("line", "rect", "ellipse", "polygon", "bezier")
        )
        if kind not in allowed:
            raise ValueError("無効な図形です")
        c["kind"] = kind
        if kind in ("rect", "ellipse"):
            c["rect"] = bounds(doc, c["rect"])
        if kind in ("line", "polygon", "bezier"):
            required = 4 if kind == "bezier" else 2 if kind == "line" else 3
            pts = c["points"]
            if (
                not required <= len(pts) <= 10000
                or kind in ("line", "bezier")
                and len(pts) != required
            ):
                raise ValueError("点数が不正です")
            c["points"] = [point(doc, p) for p in pts]
    if op in ("select_region", "fill"):
        if op == "select_region":
            c["combine"] = c.get("combine", "replace")
            if c["combine"] not in ("replace", "add", "subtract", "intersect"):
                raise ValueError("無効な選択範囲の結合方法です")
        if op == "fill" or c["kind"] == "wand":
            c["mode"] = c.get("mode", "contiguous")
            if c["mode"] not in ("contiguous", "global", "selection", "enclosed"):
                raise ValueError("無効な塗りつぶし方法です")
            if c["mode"] != "selection":
                c["point"] = point(doc, c.get("point", [0, 0]))
            c["tolerance"] = int(number(c.get("tolerance", 24), 0, 255, "tolerance"))
            c["gap_close"] = int(number(c.get("gap_close", 0), 0, 8, "gap_close"))
            c["expand"] = int(number(c.get("expand", 0), 0, 16, "expand"))
            reference = c.get("reference", "visible")
            if reference not in ("active", "visible", "layer"):
                raise ValueError("referenceはactive/visible/layerです")
            c["reference"] = reference
            if reference == "layer":
                c["reference_layer_id"] = doc.layer(c["reference_layer_id"]).id
        if c.get("kind") == "layer_alpha":
            c["reference_layer_id"] = doc.layer(c.get("reference_layer_id")).id
        if c.get("mode") == "enclosed":
            pts = c.get("points", [])
            if not 3 <= len(pts) <= 10000:
                raise ValueError("囲って塗るには3点以上が必要です")
            c["points"] = [point(doc, p) for p in pts]
    if op == "selection_edit":
        if c["action"] not in ("clear", "all", "invert", "grow", "shrink", "feather"):
            raise ValueError("無効な選択範囲操作です")
        c["amount"] = int(number(c.get("amount", 2), 0, 32, "amount"))
    if op in ("fill", "shape", "gradient"):
        c["color"] = color(c.get("color", "#24334a"))
        c["opacity"] = number(c.get("opacity", 1), 0, 1, "opacity")
        if not isinstance(c.get("erase", False), bool):
            raise ValueError("eraseは真偽値です")
    if op == "shape":
        c["size"] = number(c.get("size", 3), 0.5, 300, "size")
        c["fill_color"] = color(c["fill_color"]) if c.get("fill_color") else None
    if op == "gradient":
        c["start"] = point(doc, c["start"])
        c["end"] = point(doc, c["end"])
        if c["start"] == c["end"]:
            raise ValueError("グラデーションの始点と終点を分けてください")
        c["end_color"] = color(c["end_color"])
        c["kind"] = c.get("kind", "linear")
        if c["kind"] not in ("linear", "radial"):
            raise ValueError("グラデーションはlinear/radialです")
    if op == "transform":
        for key, default, low, high in (
            ("dx", 0, -8192, 8192),
            ("dy", 0, -8192, 8192),
            ("scale_x", 1, -10, 10),
            ("scale_y", 1, -10, 10),
            ("angle", 0, -3600, 3600),
            ("shear_x", 0, -5, 5),
            ("shear_y", 0, -5, 5),
        ):
            c[key] = number(c.get(key, default), low, high, key)
        if abs(c["scale_x"] * c["scale_y"]) < 1e-6:
            raise ValueError("拡大率を0にはできません")
        c["pivot"] = point(doc, c["pivot"]) if c.get("pivot") else [doc.width / 2, doc.height / 2]
    if op == "filter":
        c["settings"] = normalize_filter(c.get("settings", {"kind": "blur"}))
    if op == "mask":
        if c["action"] not in (
            "from_selection",
            "reveal_all",
            "hide_all",
            "invert",
            "remove",
            "apply",
        ):
            raise ValueError("無効なマスク操作です")
        if c["action"] == "apply" and doc.layer(c["layer_id"]).kind != "paint":
            raise ValueError("フォルダー・補正レイヤーのマスクは削除か編集してください")
    if op == "mask_stroke":
        layer = doc.layer(c["layer_id"])
        if layer.mask is None:
            raise ValueError("マスクを作成してから描画してください")
        c["value"] = int(number(c.get("value", 0), 0, 255, "value"))
        points = c.get("points", [])
        if not isinstance(points, list) or not 1 <= len(points) <= 20000:
            raise ValueError("マスク描画には1〜20000点が必要です")
        clean = []
        previous = 0
        for i, p in enumerate(points):
            x, y = point(doc, [p["x"], p["y"]])
            elapsed = number(p.get("t_ms", i * 16), previous, 120000, "t_ms")
            previous = elapsed
            clean.append(
                {
                    "x": x,
                    "y": y,
                    "pressure": number(p.get("pressure", 1), 0, 1, "pressure"),
                    "t_ms": elapsed,
                }
            )
        offset = clean[0]["t_ms"]
        for p in clean:
            p["t_ms"] -= offset
        c["points"] = clean
        c["brush"] = c.get("brush", "pen")
        c["size"] = number(c.get("size", 30), 0.5, 300, "size")
        c["opacity"] = number(c.get("opacity", 1), 0, 1, "opacity")
        if c["brush"] not in ("pen", "airbrush"):
            raise ValueError("マスク用ブラシはpen/airbrushです")
    if op == "duplicate_layer":
        if len(doc.layers) >= 64 or doc.layer(c["layer_id"]).kind == "group":
            raise ValueError("複製は描画・補正レイヤーのみ、最大64枚です")
        c["id"] = c.get("id", uuid.uuid4().hex)
        if any(x.id == c["id"] for x in doc.layers):
            raise ValueError("レイヤーIDが重複しています")
    if op == "flatten_group":
        if doc.layer(c["layer_id"]).kind != "group":
            raise ValueError("フォルダーを選択してください")
        for child_id in doc.descendants(c["layer_id"]):
            unlocked(doc, doc.layer(child_id))
    if op == "merge_down":
        layer = doc.layer(c["layer_id"])
        drawable(doc, layer)
        siblings = [x for x in doc.layers if x.group_id == layer.group_id]
        index = siblings.index(layer)
        if index == 0:
            raise ValueError("下に統合対象がありません")
        lower = siblings[index - 1]
        drawable(doc, lower)
        if (
            layer.blend_mode != "normal"
            or lower.blend_mode != "normal"
            or layer.clipping
            or lower.clipping
            or not layer.visible
            or not lower.visible
        ):
            raise ValueError("統合対象は通常合成・クリッピングなしにしてください")
        c["lower_id"] = lower.id
    if op in ("import_image", "import_image_layer"):
        c.pop("path", None)
        data = base64.b64decode(c["data"], validate=True)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("画像は16MB以下にしてください")
        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) > 4096:
                raise ValueError("画像は4096px以下にしてください")
            im.load()
        if op == "import_image":
            c["x"] = int(number(c.get("x", 0), -4096, 4096, "x"))
            c["y"] = int(number(c.get("y", 0), -4096, 4096, "y"))
        else:
            if len(doc.layers) >= 64:
                raise ValueError("レイヤー数の上限は64です")
            c["id"] = c.get("id") or uuid.uuid4().hex
            if any(layer.id == c["id"] for layer in doc.layers):
                raise ValueError("レイヤーIDが重複しています")
            c["name"] = str(c.get("name") or "参考画像")[:100]
            c["fit"] = c.get("fit", "contain")
            c["placement"] = c.get("placement", "back")
            if c["fit"] not in ("contain", "original"):
                raise ValueError("fitはcontain/originalです")
            if c["placement"] not in ("back", "above"):
                raise ValueError("placementはback/aboveです")
            c["opacity"] = number(c.get("opacity", 0.5), 0, 1, "opacity")
            for key, default in (("locked", True), ("select_imported", False)):
                c[key] = c.get(key, default)
                if not isinstance(c[key], bool):
                    raise ValueError(f"{key}は真偽値です")
            c["previous_active_id"] = doc.layer(c.get("previous_active_id")).id
            anchor = doc.layer(c.get("anchor_id") or c["previous_active_id"])
            c["anchor_id"] = anchor.id
            c["group_id"] = (
                None
                if c["placement"] == "back"
                else anchor.id
                if anchor.kind == "group"
                else anchor.group_id
            )
            if c["group_id"]:
                unlocked(doc, doc.layer(c["group_id"]))
    if op == "mesh_warp":
        c["columns"] = int(number(c.get("columns", 2), 1, 8, "columns"))
        c["rows"] = int(number(c.get("rows", 2), 1, 8, "rows"))
        if len(c["points"]) != (c["columns"] + 1) * (c["rows"] + 1):
            raise ValueError("メッシュ点数は(columns+1)*(rows+1)です")
        c["points"] = [point(doc, p) for p in c["points"]]
        for y in range(c["rows"]):
            for x in range(c["columns"]):
                indices = [
                    y * (c["columns"] + 1) + x,
                    y * (c["columns"] + 1) + x + 1,
                    (y + 1) * (c["columns"] + 1) + x + 1,
                    (y + 1) * (c["columns"] + 1) + x,
                ]
                quad = [c["points"][i] for i in indices]
                cross = [
                    (quad[(i + 1) % 4][0] - quad[i][0])
                    * (quad[(i + 2) % 4][1] - quad[(i + 1) % 4][1])
                    - (quad[(i + 1) % 4][1] - quad[i][1])
                    * (quad[(i + 2) % 4][0] - quad[(i + 1) % 4][0])
                    for i in range(4)
                ]
                if min(cross) <= 0:
                    raise ValueError("メッシュの各セルは交差しない凸四角形にしてください")
    return c


def normalize_filter(settings):
    from .engine import color, number

    c = dict(settings)
    kind = c.get("kind")
    if kind not in FILTERS:
        raise ValueError("無効なフィルターです")
    if kind == "blur":
        c["radius"] = number(c.get("radius", 4), 0, 64, "radius")
    elif kind == "brightness_contrast":
        c["brightness"] = number(c.get("brightness", 1), 0, 3, "brightness")
        c["contrast"] = number(c.get("contrast", 1), 0, 3, "contrast")
    elif kind == "hue_saturation":
        c["hue"] = number(c.get("hue", 0), -360, 360, "hue")
        c["saturation"] = number(c.get("saturation", 1), 0, 3, "saturation")
    elif kind == "color_balance":
        for key in ("red", "green", "blue"):
            c[key] = number(c.get(key, 0), -255, 255, key)
    elif kind == "tone_curve":
        pts = c.get("points", [[0, 0], [255, 255]])
        if not 2 <= len(pts) <= 32 or pts[0][0] != 0 or pts[-1][0] != 255:
            raise ValueError("カーブは0〜255の両端を含めてください")
        c["points"] = [[number(x, 0, 255, "input"), number(y, 0, 255, "output")] for x, y in pts]
        if any(a[0] >= b[0] for a, b in zip(c["points"], c["points"][1:], strict=False)):
            raise ValueError("カーブの入力は昇順にしてください")
    elif kind == "gradient_map":
        stops = c.get("stops", [[0, "#24334a"], [1, "#ffffff"]])
        if not 2 <= len(stops) <= 16:
            raise ValueError("グラデーション色数は2〜16です")
        c["stops"] = [[number(x, 0, 1, "position"), color(y)] for x, y in stops]
        if any(a[0] >= b[0] for a, b in zip(c["stops"], c["stops"][1:], strict=False)):
            raise ValueError("グラデーション位置は昇順にしてください")
    return c


def filter_image(image, settings):
    rgba = pil(image)
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    kind = settings["kind"]
    if kind == "blur":
        # Blur premultiplied channels to avoid dark halos at transparent boundaries.
        premul = np.asarray(rgba, dtype=np.float32).copy()
        premul[:, :, :3] *= premul[:, :, 3:] / 255
        blurred = Image.fromarray(np.uint8(premul)).filter(
            ImageFilter.GaussianBlur(settings["radius"])
        )
        arr = np.asarray(blurred, dtype=np.float32).copy()
        arr[:, :, :3] = np.divide(
            arr[:, :, :3] * 255,
            arr[:, :, 3:],
            out=np.zeros_like(arr[:, :, :3]),
            where=arr[:, :, 3:] > 0,
        )
        return qimage(Image.fromarray(np.uint8(np.clip(arr, 0, 255))))
    if kind == "brightness_contrast":
        rgb = ImageEnhance.Contrast(
            ImageEnhance.Brightness(rgb).enhance(settings["brightness"])
        ).enhance(settings["contrast"])
    elif kind == "hue_saturation":
        rgb = ImageEnhance.Color(rgb).enhance(settings["saturation"])
        hsv = np.array(rgb.convert("HSV"))
        hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + round(settings["hue"] * 255 / 360)) % 256
        rgb = Image.frombytes("HSV", rgb.size, hsv.tobytes()).convert("RGB")
    elif kind == "color_balance":
        arr = np.asarray(rgb, dtype=np.float32) + [settings[k] for k in ("red", "green", "blue")]
        rgb = Image.fromarray(np.uint8(np.clip(arr, 0, 255)))
    elif kind == "tone_curve":
        pts = settings["points"]
        lut = (
            np.interp(np.arange(256), [p[0] for p in pts], [p[1] for p in pts])
            .astype(np.uint8)
            .tolist()
        )
        rgb = rgb.point(lut * 3)
    elif kind == "gradient_map":
        arr = np.asarray(ImageOps.grayscale(rgb)) / 255
        stops = settings["stops"]
        colors = [QColor(c).getRgb()[:3] for _, c in stops]
        mapped = np.stack(
            [
                np.interp(arr, [p for p, _ in stops], [c[channel] for c in colors])
                for channel in range(3)
            ],
            axis=-1,
        )
        rgb = Image.fromarray(np.uint8(mapped))
    rgb.putalpha(alpha)
    return qimage(rgb)


def render_layer(doc, layer):
    from .engine import transparent

    if layer.kind == "group":
        image = composite_layers(doc, layer.id)
    else:
        image = layer.image.copy()
    if layer.layer_color:
        alpha = pil(image).getchannel("A")
        image = transparent(doc.width, doc.height)
        image.fill(QColor(layer.layer_color))
        image = apply_alpha(image, alpha)
    if layer.mask is not None:
        image = apply_alpha(image, layer.mask)
    return image


def paint_blend(target, source, mode, opacity):
    if mode == "linear_burn":
        dst = np.asarray(pil(target), dtype=np.float32) / 255
        src = np.asarray(pil(source), dtype=np.float32) / 255
        sa, da = src[:, :, 3:] * opacity, dst[:, :, 3:]
        alpha = sa + da * (1 - sa)
        blend = np.maximum(0, src[:, :, :3] + dst[:, :, :3] - 1)
        rgb = sa * ((1 - da) * src[:, :, :3] + da * blend) + (1 - sa) * da * dst[:, :, :3]
        rgb = np.divide(rgb, alpha, out=np.zeros_like(rgb), where=alpha > 0)
        return qimage(
            Image.fromarray(np.uint8(np.clip(np.concatenate([rgb, alpha], axis=-1) * 255, 0, 255)))
        )
    modes = {
        "normal": "SourceOver",
        "multiply": "Multiply",
        "screen": "Screen",
        "overlay": "Overlay",
        "soft_light": "SoftLight",
        "hard_light": "HardLight",
        "add": "Plus",
        "darken": "Darken",
        "lighten": "Lighten",
        "color_dodge": "ColorDodge",
        "color_burn": "ColorBurn",
        "difference": "Difference",
    }
    p = QPainter(target)
    p.setCompositionMode(getattr(QPainter.CompositionMode, "CompositionMode_" + modes[mode]))
    p.setOpacity(opacity)
    p.drawImage(0, 0, source)
    p.end()
    return target


def composite_layers(doc, parent=None, background=False):
    from .engine import transparent

    image = transparent(doc.width, doc.height)
    if background:
        image.fill(QColor(doc.background))
    clip_base = solid_mask(doc, 0)
    for layer in (x for x in doc.layers if x.group_id == parent):
        if not layer.visible:
            if not layer.clipping:
                clip_base = solid_mask(doc, 0)
            continue
        if layer.kind == "adjustment":
            filtered = filter_image(image, layer.adjustment)
            mask = layer.mask if layer.mask is not None else solid_mask(doc)
            if layer.clipping:
                mask = ImageChops.multiply(mask, clip_base)
            amount = mask.point(lambda x, opacity=layer.opacity: round(x * opacity))
            image = qimage(Image.composite(pil(filtered), pil(image), amount))
            continue
        rendered = render_layer(doc, layer)
        if layer.clipping:
            rendered = apply_alpha(rendered, clip_base)
        else:
            clip_base = pil(rendered).getchannel("A")
        image = paint_blend(image, rendered, layer.blend_mode, layer.opacity)
    return image


def reference_image(doc, c):
    if c.get("reference", "visible") == "visible":
        return doc.composite()
    return render_layer(
        doc,
        doc.layer(
            c.get("reference_layer_id") if c.get("reference") == "layer" else c.get("layer_id")
        ),
    )


def flood_mask(doc, c):
    rgba = np.asarray(pil(reference_image(doc, c)), dtype=np.int16)
    x, y = map(int, c["point"])
    match = np.max(np.abs(rgba - rgba[y, x]), axis=-1) <= c["tolerance"]
    if c["gap_close"]:
        barrier = Image.fromarray(np.uint8(~match) * 255)
        k = 2 * c["gap_close"] + 1
        barrier = barrier.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
        match = np.asarray(barrier) == 0
    if c["mode"] == "global":
        mask = match
    else:
        mask = np.zeros(match.shape, dtype=bool)
        stack = [(x, y)]
        height, width = match.shape
        while stack:
            x, y = stack.pop()
            if mask[y, x] or not match[y, x]:
                continue
            left, right = x, x + 1
            while left > 0 and match[y, left - 1] and not mask[y, left - 1]:
                left -= 1
            while right < width and match[y, right] and not mask[y, right]:
                right += 1
            mask[y, left:right] = True
            for row in (y - 1, y + 1):
                if 0 <= row < height:
                    candidate = match[row, left:right] & ~mask[row, left:right]
                    starts = np.flatnonzero(candidate & np.concatenate(([True], ~candidate[:-1])))
                    stack.extend((int(left + i), row) for i in starts)
    result = Image.fromarray(np.uint8(mask) * 255)
    if c["expand"]:
        result = result.filter(ImageFilter.MaxFilter(2 * c["expand"] + 1))
    return result


def shape_mask(doc, c):
    from .engine import transparent

    image = transparent(doc.width, doc.height)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(Qt.GlobalColor.white)
    draw_geometry(p, c)
    p.end()
    return pil(image).getchannel("A")


def draw_geometry(p, c):
    kind = c["kind"]
    if kind == "rect":
        p.drawRect(QRectF(*c["rect"]))
    elif kind == "ellipse":
        p.drawEllipse(QRectF(*c["rect"]))
    elif kind == "polygon":
        p.drawPolygon(QPolygonF([QPointF(*v) for v in c["points"]]))
    elif kind == "line":
        p.drawLine(QPointF(*c["points"][0]), QPointF(*c["points"][1]))
    elif kind == "bezier":
        path = QPainterPath(QPointF(*c["points"][0]))
        path.cubicTo(*[QPointF(*v) for v in c["points"][1:]])
        p.drawPath(path)


def restrict_edit(doc, layer, before, after):
    before_p, after_p = pil(before), pil(after)
    if layer.alpha_lock:
        after_p.putalpha(before_p.getchannel("A"))
    if doc.selection is not None:
        after_p = Image.composite(after_p, before_p, doc.selection)
    layer.image = qimage(after_p)


def apply(doc, c, progress=1.0):
    from .engine import Layer, draw_stroke, transparent

    op = c["op"]
    if op == "import_image_layer":
        with Image.open(io.BytesIO(base64.b64decode(c["data"]))) as image:
            source = qimage(ImageOps.exif_transpose(image))
        if c["fit"] == "contain":
            source = source.scaled(
                doc.width,
                doc.height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        image = transparent(doc.width, doc.height)
        p = QPainter(image)
        p.drawImage((doc.width - source.width()) // 2, (doc.height - source.height()) // 2, source)
        p.end()
        layer = Layer(
            c["id"],
            c["name"],
            image,
            locked=c["locked"],
            opacity=c["opacity"],
            group_id=c["group_id"],
        )
        index = 0
        if c["placement"] == "above":
            anchors = doc.descendants(c["anchor_id"]) | {c["anchor_id"]}
            index = max(i for i, other in enumerate(doc.layers) if other.id in anchors) + 1
        doc.layers.insert(index, layer)
        doc.active_id = layer.id if c["select_imported"] else c["previous_active_id"]
        return
    if op == "select_region":
        if c["kind"] == "wand":
            mask = flood_mask(doc, c)
        elif c["kind"] == "layer_alpha":
            mask = pil(render_layer(doc, doc.layer(c["reference_layer_id"]))).getchannel("A")
        else:
            mask = shape_mask(doc, c)
        old = doc.selection or solid_mask(doc, 0)
        if c["combine"] == "add":
            mask = ImageChops.lighter(old, mask)
        elif c["combine"] == "subtract":
            mask = ImageChops.subtract(old, mask)
        elif c["combine"] == "intersect":
            mask = ImageChops.multiply(old, mask)
        doc.selection = mask
        return
    if op == "selection_edit":
        mask = doc.selection if doc.selection is not None else solid_mask(doc, 0)
        action = c["action"]
        doc.selection = (
            None
            if action == "clear"
            else solid_mask(doc)
            if action == "all"
            else ImageOps.invert(mask)
            if action == "invert"
            else mask.filter(ImageFilter.GaussianBlur(c["amount"]))
            if action == "feather"
            else mask.filter(
                (ImageFilter.MaxFilter if action == "grow" else ImageFilter.MinFilter)(
                    2 * c["amount"] + 1
                )
            )
        )
        return
    layer = doc.layer(c["layer_id"])
    before = layer.image.copy()
    if op == "mask":
        action = c["action"]
        if action == "remove":
            layer.mask = None
        elif action == "apply":
            if layer.mask is not None:
                layer.image = apply_alpha(layer.image, layer.mask)
                layer.mask = None
        elif action == "invert":
            layer.mask = ImageOps.invert(layer.mask if layer.mask is not None else solid_mask(doc))
        else:
            layer.mask = (
                doc.selection.copy()
                if action == "from_selection" and doc.selection is not None
                else solid_mask(doc, 0 if action == "hide_all" else 255)
            )
        return
    if op == "mask_stroke":
        dab = transparent(doc.width, doc.height)
        draw_stroke(dab, {**c, "color": "#ffffff"}, progress)
        mask = pil(dab).getchannel("A")
        if doc.selection is not None:
            mask = ImageChops.multiply(mask, doc.selection)
        layer.mask = Image.composite(solid_mask(doc, c["value"]), layer.mask, mask)
        return
    if op == "duplicate_layer":
        import copy

        new = copy.copy(layer)
        new.id = c["id"]
        new.name = layer.name + " コピー"
        new.image = layer.image.copy()
        new.mask = layer.mask.copy() if layer.mask is not None else None
        new.adjustment = copy.deepcopy(layer.adjustment)
        doc.layers.insert(doc.layers.index(layer) + 1, new)
        doc.active_id = new.id
        return
    if op == "flatten_group":
        image = render_layer(doc, layer)
        removed = doc.descendants(layer.id)
        doc.layers = [x for x in doc.layers if x.id not in removed]
        layer.kind = "paint"
        layer.image = image
        layer.mask = None
        layer.layer_color = None
        layer.adjustment = None
        doc.active_id = layer.id
        return
    if op == "merge_down":
        lower = doc.layer(c["lower_id"])
        target = transparent(doc.width, doc.height)
        target = paint_blend(target, render_layer(doc, lower), "normal", lower.opacity)
        lower.image = paint_blend(target, render_layer(doc, layer), "normal", layer.opacity)
        lower.mask = None
        lower.layer_color = None
        lower.opacity = 1
        doc.layers.remove(layer)
        doc.active_id = lower.id
        return
    if op in ("shape", "fill", "gradient"):
        ink = transparent(doc.width, doc.height)
        if op == "fill":
            if c["mode"] == "selection":
                mask = solid_mask(doc)
            elif c["mode"] == "enclosed":
                mask = enclosed_mask(doc, c)
            else:
                mask = flood_mask(doc, c)
            ink.fill(QColor(c["color"]))
            ink = apply_alpha(ink, mask)
        else:
            p = QPainter(ink)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if op == "shape":
                p.setPen(
                    QPen(
                        QColor(c["color"]),
                        c["size"],
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin,
                    )
                )
                p.setBrush(QColor(c["fill_color"]) if c["fill_color"] else Qt.BrushStyle.NoBrush)
                draw_geometry(p, c)
            else:
                a, b = QPointF(*c["start"]), QPointF(*c["end"])
                gradient = (
                    QLinearGradient(a, b)
                    if c["kind"] == "linear"
                    else QRadialGradient(a, math.hypot(b.x() - a.x(), b.y() - a.y()))
                )
                gradient.setColorAt(0, QColor(c["color"]))
                gradient.setColorAt(1, QColor(c["end_color"]))
                p.fillRect(ink.rect(), gradient)
            p.end()
        out = before.copy()
        p = QPainter(out)
        if c.get("erase"):
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        p.setOpacity(c["opacity"])
        p.drawImage(0, 0, ink)
        p.end()
    elif op == "filter":
        out = filter_image(before, c["settings"])
    elif op == "import_image":
        out = before.copy()
        source = QImage.fromData(base64.b64decode(c["data"]))
        p = QPainter(out)
        p.drawImage(c["x"], c["y"], source)
        p.end()
    elif op in ("transform", "mesh_warp"):
        selected = apply_alpha(before, doc.selection) if doc.selection is not None else before
        out = (
            apply_alpha(before, ImageOps.invert(doc.selection))
            if doc.selection is not None
            else transparent(doc.width, doc.height)
        )
        transformed = warp(doc, selected, c)
        p = QPainter(out)
        p.drawImage(0, 0, transformed)
        p.end()
        if doc.selection is not None:
            doc.selection = pil(warp(doc, mask_image(doc.selection), c)).getchannel("A")
        elif layer.mask is not None:
            layer.mask = pil(warp(doc, mask_image(layer.mask), c)).getchannel("A")
        layer.image = out
        return
    else:
        raise ValueError("未知の操作です")
    restrict_edit(doc, layer, before, out)


def enclosed_mask(doc, c):
    # Flood the transparent exterior of the line reference, then remove it. Intersect
    # with the lasso so only closed regions entirely inside the enclosure survive.
    area = shape_mask(doc, {"kind": "polygon", "points": c["points"]})
    rgba = pil(reference_image(doc, c))
    source = Image.new("RGB", rgba.size, "white")
    source.paste(rgba, mask=rgba.getchannel("A"))
    gray = np.asarray(ImageOps.grayscale(source))
    boundary = gray < 255 - c["tolerance"]
    k = 2 * c["gap_close"] + 1
    barrier = Image.fromarray(np.uint8(boundary) * 255)
    if k > 1:
        barrier = barrier.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    binary = np.asarray(barrier) > 0
    allowed = (~binary) & (np.asarray(area) > 0)
    # Any region touching the lasso's edge is exterior, not a closed region.
    eroded = area.filter(ImageFilter.MinFilter(3))
    edge = (np.asarray(area) > 0) & (np.asarray(eroded) == 0)
    outside = np.zeros_like(allowed)
    seeds = list(zip(*np.nonzero(edge & allowed), strict=False))
    stack = [(int(x), int(y)) for y, x in seeds]
    h, w = allowed.shape
    while stack:
        x, y = stack.pop()
        if outside[y, x] or not allowed[y, x]:
            continue
        left, right = x, x + 1
        while left > 0 and allowed[y, left - 1] and not outside[y, left - 1]:
            left -= 1
        while right < w and allowed[y, right] and not outside[y, right]:
            right += 1
        outside[y, left:right] = True
        for row in (y - 1, y + 1):
            if 0 <= row < h:
                candidate = allowed[row, left:right] & ~outside[row, left:right]
                starts = np.flatnonzero(candidate & np.concatenate(([True], ~candidate[:-1])))
                stack.extend((int(left + i), row) for i in starts)
    result = Image.fromarray(np.uint8(allowed & ~outside) * 255)
    if c["expand"]:
        result = result.filter(ImageFilter.MaxFilter(2 * c["expand"] + 1))
    return ImageChops.multiply(result, area)


def warp(doc, image, c):
    from .engine import transparent

    output = transparent(doc.width, doc.height)
    p = QPainter(output)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if c["op"] == "transform":
        px, py = c["pivot"]
        transform = (
            QTransform()
            .translate(px + c["dx"], py + c["dy"])
            .rotate(c["angle"])
            .shear(c["shear_x"], c["shear_y"])
            .scale(c["scale_x"], c["scale_y"])
            .translate(-px, -py)
        )
        p.setTransform(transform)
        p.drawImage(0, 0, image)
    else:
        columns, rows = c["columns"], c["rows"]
        for y in range(rows):
            for x in range(columns):
                x0, x1 = x * (doc.width - 1) / columns, (x + 1) * (doc.width - 1) / columns
                y0, y1 = y * (doc.height - 1) / rows, (y + 1) * (doc.height - 1) / rows
                source = QPolygonF(
                    [QPointF(x0, y0), QPointF(x1, y0), QPointF(x1, y1), QPointF(x0, y1)]
                )
                indices = [
                    y * (columns + 1) + x,
                    y * (columns + 1) + x + 1,
                    (y + 1) * (columns + 1) + x + 1,
                    (y + 1) * (columns + 1) + x,
                ]
                target = QPolygonF([QPointF(*c["points"][i]) for i in indices])
                transform = QTransform()
                if not QTransform.quadToQuad(source, target, transform):
                    continue
                p.save()
                path = QPainterPath()
                path.addPolygon(target)
                p.setClipPath(path)
                p.setTransform(transform)
                p.drawImage(
                    QRectF(x0, y0, x1 - x0, y1 - y0), image, QRectF(x0, y0, x1 - x0, y1 - y0)
                )
                p.restore()
    p.end()
    return output
