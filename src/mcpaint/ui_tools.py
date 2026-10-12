"""Native desktop controls for the same journaled operations exposed over MCP."""

import base64
import io
import math
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
)

from .operations import BLEND_MODES, FILTERS

TOOLS = {
    "brush": "ブラシ",
    "fill": "塗りつぶし",
    "select_rect": "長方形選択",
    "select_ellipse": "楕円選択",
    "lasso": "投げ縄選択",
    "wand": "自動選択",
    "line": "直線",
    "rect": "長方形",
    "ellipse": "楕円",
    "polygon": "多角形（右クリックで確定）",
    "bezier": "曲線（始点・制御点2点・終点）",
    "gradient": "グラデーション",
    "eyedropper": "スポイト",
    "mask_hide": "マスクを隠す",
    "mask_reveal": "マスクを表示",
    "mesh": "メッシュ変形（点をドラッグ）",
}
BLEND_LABELS = {
    "normal": "通常",
    "multiply": "乗算",
    "screen": "スクリーン",
    "overlay": "オーバーレイ",
    "soft_light": "ソフトライト",
    "hard_light": "ハードライト",
    "add": "加算（発光）",
    "darken": "比較（暗）",
    "lighten": "比較（明）",
    "color_dodge": "覆い焼き",
    "color_burn": "焼き込み",
    "linear_burn": "焼き込み（リニア）",
    "difference": "差の絶対値",
}


def canonical_image(path):
    if Path(path).stat().st_size > 16 * 1024 * 1024:
        raise ValueError("画像は16MB以下にしてください")
    with Image.open(path) as image:
        if max(image.size) > 4096:
            raise ValueError("画像は4096px以下にしてください")
        image = ImageOps.exif_transpose(image).convert("RGBA")
        output = io.BytesIO()
        image.save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode()


def install(window, panel):
    window.tool = "brush"
    window.end_color = "#ffffff"
    toolbar = QToolBar("作画ツール", window)
    toolbar.setMovable(False)
    window.addToolBar(toolbar)
    window.tool_combo = QComboBox()
    for key, title in TOOLS.items():
        window.tool_combo.addItem(title, key)
    window.tool_combo.currentIndexChanged.connect(lambda: change_tool(window))
    toolbar.addWidget(window.tool_combo)
    toolbar.addSeparator()
    button = QPushButton("終点の色")
    button.clicked.connect(lambda: choose_end_color(window))
    toolbar.addWidget(button)
    toolbar.addAction("左右反転表示", lambda: toggle_flip(window))
    toolbar.addAction("表示を回転", lambda: rotate_view(window))
    toolbar.addAction(
        "選択解除", lambda: window.mutate({"op": "selection_edit", "action": "clear"})
    )
    form = QFormLayout()
    window.reference_combo = QComboBox()
    window.reference_combo.addItem("表示中のレイヤー", "visible")
    window.reference_combo.addItem("選択レイヤーのみ", "active")
    form.addRow("塗り・選択の参照", window.reference_combo)
    window.tolerance_spin = QSpinBox()
    window.tolerance_spin.setRange(0, 255)
    window.tolerance_spin.setValue(24)
    form.addRow("色の誤差", window.tolerance_spin)
    window.gap_spin = QSpinBox()
    window.gap_spin.setRange(0, 8)
    form.addRow("すきま閉じ (px)", window.gap_spin)
    window.expand_spin = QSpinBox()
    window.expand_spin.setRange(0, 16)
    window.expand_spin.setValue(1)
    form.addRow("領域拡張 (px)", window.expand_spin)
    window.combine_combo = QComboBox()
    for key, label in (
        ("replace", "置換"),
        ("add", "追加"),
        ("subtract", "削る"),
        ("intersect", "共通部分"),
    ):
        window.combine_combo.addItem(label, key)
    form.addRow("選択範囲", window.combine_combo)
    window.smoothing_spin = QDoubleSpinBox()
    window.smoothing_spin.setRange(0, 1)
    window.smoothing_spin.setSingleStep(0.1)
    window.smoothing_spin.valueChanged.connect(lambda v: window.brush.update(smoothing=v))
    form.addRow("手ブレ補正", window.smoothing_spin)
    panel.addLayout(form)
    window.blend_combo = QComboBox()
    for mode in BLEND_MODES:
        window.blend_combo.addItem(BLEND_LABELS[mode], mode)
    window.blend_combo.currentIndexChanged.connect(
        lambda: window.mutate(
            {"op": "update_layer", "changes": {"blend_mode": window.blend_combo.currentData()}}
        )
    )
    panel.addWidget(window.blend_combo)
    window.clip_check = QCheckBox("下のレイヤーでクリッピング")
    window.clip_check.toggled.connect(
        lambda value: window.mutate({"op": "update_layer", "changes": {"clipping": value}})
    )
    panel.addWidget(window.clip_check)
    window.alpha_check = QCheckBox("透明ピクセルをロック")
    window.alpha_check.toggled.connect(
        lambda value: window.mutate({"op": "update_layer", "changes": {"alpha_lock": value}})
    )
    panel.addWidget(window.alpha_check)
    window.mask_label = QLabel()
    panel.addWidget(window.mask_label)
    row = QHBoxLayout()
    for text, action in (("選択→マスク", "from_selection"), ("マスク解除", "remove")):
        button = QPushButton(text)
        button.clicked.connect(
            lambda checked=False, a=action: window.mutate({"op": "mask", "action": a})
        )
        row.addWidget(button)
    panel.addLayout(row)
    selection = window.menuBar().addMenu("選択範囲")
    for label, action, shortcut in (
        ("すべて選択", "all", "Ctrl+A"),
        ("選択を解除", "clear", "Ctrl+D"),
        ("選択を反転", "invert", "Ctrl+Shift+I"),
        ("選択を拡張", "grow", ""),
        ("選択を縮小", "shrink", ""),
        ("選択の境界をぼかす", "feather", ""),
    ):
        menu_action = QAction(label, window)
        if shortcut:
            menu_action.setShortcut(QKeySequence(shortcut))
        menu_action.triggered.connect(lambda checked=False, a=action: selection_action(window, a))
        selection.addAction(menu_action)
    selection.addAction(
        "選択範囲を塗りつぶす",
        lambda: window.mutate(
            {
                "op": "fill",
                "mode": "selection",
                "color": window.brush["color"],
                "opacity": window.brush["opacity"],
            }
        ),
    )
    selection.addAction(
        "レイヤーの不透明部分を選択",
        lambda: window.mutate({"op": "select_region", "kind": "layer_alpha"}),
    )
    layers = window.menuBar().addMenu("レイヤー")
    layers.addAction(
        "新しいフォルダー",
        lambda: window.mutate(
            {
                "op": "add_layer",
                "kind": "group",
                "name": "フォルダー",
                "group_id": window.doc.layer().group_id,
            }
        ),
    )
    layers.addAction("フォルダーへ移動", lambda: parent_dialog(window))
    layers.addAction("複製", lambda: window.mutate({"op": "duplicate_layer"}))
    layers.addAction("下のレイヤーと統合", lambda: window.mutate({"op": "merge_down"}))
    layers.addAction("フォルダーを1枚にまとめる", lambda: window.mutate({"op": "flatten_group"}))
    layers.addAction("線画の色を変更", lambda: recolor_dialog(window))
    layers.addAction(
        "線画の色変更を解除",
        lambda: window.mutate({"op": "update_layer", "changes": {"layer_color": None}}),
    )
    layers.addAction("補正レイヤーを追加", lambda: adjustment_dialog(window))
    layers.addAction("補正レイヤーの設定", lambda: adjustment_dialog(window, True))
    layers.addAction("マスクを反転", lambda: window.mutate({"op": "mask", "action": "invert"}))
    layers.addAction("マスクを描画に適用", lambda: window.mutate({"op": "mask", "action": "apply"}))
    image_menu = window.menuBar().addMenu("画像")
    image_menu.addAction("画像を選択レイヤーに読み込む", lambda: import_dialog(window))
    image_menu.addAction("選択範囲・レイヤーを変形", lambda: transform_dialog(window))
    image_menu.addAction("フィルター・色調整", lambda: filter_dialog(window))
    image_menu.addAction("選択範囲を囲って閉領域だけ塗る", lambda: enclose_selection(window))
    window.tool_controls = True


def refresh(window):
    if not getattr(window, "tool_controls", False):
        return
    layer = window.doc.layer()
    for widget, value in (
        (window.blend_combo, BLEND_MODES.index(layer.blend_mode)),
        (window.clip_check, layer.clipping),
        (window.alpha_check, layer.alpha_lock),
    ):
        widget.blockSignals(True)
        if isinstance(widget, QComboBox):
            widget.setCurrentIndex(value)
        else:
            widget.setChecked(value)
        widget.blockSignals(False)
    window.mask_label.setText(
        "マスクあり / ブラシで表示・非表示を編集" if layer.mask is not None else "マスクなし"
    )


def change_tool(window):
    window.tool = window.tool_combo.currentData()
    window.canvas.gesture = []
    window.canvas.mesh_points = (
        [
            [x * (window.doc.width - 1) / 2, y * (window.doc.height - 1) / 2]
            for y in range(3)
            for x in range(3)
        ]
        if window.tool == "mesh"
        else []
    )
    window.canvas.update()


def fill_settings(window):
    return {
        "reference": window.reference_combo.currentData(),
        "tolerance": window.tolerance_spin.value(),
        "gap_close": window.gap_spin.value(),
        "expand": window.expand_spin.value(),
    }


def press(canvas, event):
    w = canvas.window
    if event.button() == Qt.MouseButton.MiddleButton:
        return False
    pos = canvas.document_point(event.position())
    if pos is None:
        return True
    if event.button() == Qt.MouseButton.RightButton and w.tool == "polygon":
        if len(canvas.gesture) >= 3:
            w.mutate(
                {
                    "op": "shape",
                    "kind": "polygon",
                    "points": canvas.gesture,
                    "color": w.brush["color"],
                    "size": w.brush["size"],
                }
            )
        canvas.gesture = []
        canvas.update()
        return True
    if event.button() != Qt.MouseButton.LeftButton:
        return False
    if w.tool == "brush":
        return False
    if w.tool in ("fill", "wand", "eyedropper"):
        if w.tool == "eyedropper":
            w.set_color(w.doc.composite().pixelColor(int(pos[0]), int(pos[1])).name())
        elif w.tool == "fill":
            w.mutate(
                {
                    "op": "fill",
                    "point": pos,
                    "color": w.brush["color"],
                    "opacity": w.brush["opacity"],
                    **fill_settings(w),
                }
            )
        else:
            w.mutate(
                {
                    "op": "select_region",
                    "kind": "wand",
                    "point": pos,
                    "combine": w.combine_combo.currentData(),
                    **fill_settings(w),
                }
            )
        return True
    if w.tool == "mesh":
        nearest = min(
            range(9),
            key=lambda i: math.hypot(
                pos[0] - canvas.mesh_points[i][0], pos[1] - canvas.mesh_points[i][1]
            ),
        )
        canvas.mesh_handle = nearest
        return True
    if w.tool in ("bezier", "polygon"):
        canvas.gesture.append(list(pos))
        if w.tool == "bezier" and len(canvas.gesture) == 4:
            w.mutate(
                {
                    "op": "shape",
                    "kind": "bezier",
                    "points": canvas.gesture,
                    "color": w.brush["color"],
                    "size": w.brush["size"],
                }
            )
            canvas.gesture = []
        canvas.update()
        return True
    canvas.gesture = [list(pos)]
    return True


def move(canvas, event):
    w = canvas.window
    pos = canvas.document_point(event.position(), clamp=True)
    if canvas.mesh_handle is not None:
        canvas.mesh_points[canvas.mesh_handle] = list(pos)
        canvas.update()
        return True
    if w.tool == "brush" or not canvas.gesture or w.tool in ("bezier", "polygon"):
        return False
    if w.tool in ("lasso", "mask_hide", "mask_reveal"):
        canvas.gesture.append(list(pos))
    else:
        canvas.gesture = canvas.gesture[:1] + [list(pos)]
    canvas.update()
    return True


def release(canvas, event):
    w = canvas.window
    if event.button() != Qt.MouseButton.LeftButton or w.tool == "brush":
        return False
    if canvas.mesh_handle is not None:
        w.mutate({"op": "mesh_warp", "points": canvas.mesh_points, "columns": 2, "rows": 2})
        canvas.mesh_handle = None
        canvas.mesh_points = [
            [x * (w.doc.width - 1) / 2, y * (w.doc.height - 1) / 2]
            for y in range(3)
            for x in range(3)
        ]
        canvas.update()
        return True
    if w.tool in ("bezier", "polygon", "fill", "wand", "eyedropper"):
        return True
    pts = canvas.gesture
    canvas.gesture = []
    if not pts:
        return True
    pos = canvas.document_point(event.position(), clamp=True)
    pts.append(list(pos))
    a, b = pts[0], pts[-1]
    rect = [min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]), abs(b[1] - a[1])]
    common = {"color": w.brush["color"], "size": w.brush["size"], "opacity": w.brush["opacity"]}
    if w.tool.startswith("select_"):
        w.mutate(
            {
                "op": "select_region",
                "kind": w.tool.removeprefix("select_"),
                "rect": rect,
                "combine": w.combine_combo.currentData(),
            }
        )
    elif w.tool == "lasso" and len(pts) >= 3:
        w.mutate(
            {
                "op": "select_region",
                "kind": "polygon",
                "points": pts,
                "combine": w.combine_combo.currentData(),
            }
        )
    elif w.tool in ("rect", "ellipse", "line"):
        w.mutate({"op": "shape", "kind": w.tool, "rect": rect, "points": [a, b], **common})
    elif w.tool == "gradient":
        w.mutate({"op": "gradient", "start": a, "end": b, "end_color": w.end_color, **common})
    elif w.tool in ("mask_hide", "mask_reveal"):
        w.mutate(
            {
                "op": "mask_stroke",
                "value": 0 if w.tool == "mask_hide" else 255,
                "points": [{"x": x, "y": y, "t_ms": i * 16} for i, (x, y) in enumerate(pts)],
                "brush": "airbrush" if w.brush["brush"] == "airbrush" else "pen",
                **common,
            }
        )
    canvas.update()
    return True


def overlay(canvas, painter, area):
    w = canvas.window
    if w.doc.selection is not None:
        overlay = Image.new("RGBA", (w.doc.width, w.doc.height), (67, 150, 231, 0))
        overlay.putalpha(w.doc.selection.point(lambda v: round(v * 0.15)))
        from .operations import qimage

        image = qimage(overlay)
        if canvas.flip:
            image = image.mirrored(True, False)
        painter.drawImage(area, image)
    origin, scale = canvas.geometry_info()

    def screen(pos):
        x, y = pos
        if canvas.flip:
            x = w.doc.width - 1 - x
        return origin + QPointF(x * scale, y * scale)

    painter.setPen(QPen(QColor("#4496e7"), 1.5, Qt.PenStyle.DashLine))
    pts = canvas.mesh_points if w.tool == "mesh" else canvas.gesture
    for a, b in zip(pts, pts[1:], strict=False):
        painter.drawLine(screen(a), screen(b))
    for point in pts:
        painter.drawEllipse(screen(point), 4, 4)


def choose_end_color(window):
    result = QColorDialog.getColor(QColor(window.end_color), window, "グラデーション終点の色")
    if result.isValid():
        window.end_color = result.name()


def toggle_flip(window):
    window.canvas.flip = not window.canvas.flip
    window.canvas.update()


def rotate_view(window):
    angle, ok = QInputDialog.getDouble(
        window, "表示の回転", "角度（度）", window.canvas.rotation, -180, 180, 1
    )
    if ok:
        window.canvas.rotation = angle
        window.canvas.update()


def selection_action(window, action):
    amount, ok = (
        (2, True)
        if action in ("all", "clear", "invert")
        else QInputDialog.getInt(window, "選択範囲", "ピクセル数", 2, 0, 32)
    )
    if ok:
        window.mutate({"op": "selection_edit", "action": action, "amount": amount})


def parent_dialog(window):
    layer = window.doc.layer()
    groups = [
        x
        for x in window.doc.layers
        if x.kind == "group" and x.id != layer.id and x.id not in window.doc.descendants(layer.id)
    ]
    labels = ["フォルダー外"] + [f"{x.name} ({x.id[:6]})" for x in groups]
    choice, ok = QInputDialog.getItem(window, "フォルダーへ移動", "移動先", labels, 0, False)
    if ok:
        window.mutate(
            {
                "op": "update_layer",
                "changes": {
                    "group_id": None if choice == labels[0] else groups[labels.index(choice) - 1].id
                },
            }
        )


def recolor_dialog(window):
    result = QColorDialog.getColor(QColor(window.brush["color"]), window, "線画の表示色")
    if result.isValid():
        window.mutate({"op": "update_layer", "changes": {"layer_color": result.name()}})


def transform_dialog(window):
    fields = [
        ("dx", "横移動 (px)", 0, -4096, 4096),
        ("dy", "縦移動 (px)", 0, -4096, 4096),
        ("scale_x", "横の倍率", 1, -10, 10),
        ("scale_y", "縦の倍率", 1, -10, 10),
        ("angle", "回転 (度)", 0, -360, 360),
        ("shear_x", "横の傾き", 0, -5, 5),
        ("shear_y", "縦の傾き", 0, -5, 5),
    ]
    values = numeric_dialog(window, "選択範囲・レイヤーの変形", fields)
    if values:
        window.mutate({"op": "transform", **values})


def numeric_dialog(window, title, fields):
    dialog = QDialog(window)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    controls = {}
    for key, label, value, low, high in fields:
        widget = QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        widget.setDecimals(2)
        controls[key] = widget
        form.addRow(label, widget)
    layout.addLayout(form)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return {key: widget.value() for key, widget in controls.items()} if dialog.exec() else None


def filter_settings_dialog(window):
    labels = {
        "blur": "ぼかし",
        "brightness_contrast": "明るさ・コントラスト",
        "hue_saturation": "色相・彩度",
        "color_balance": "カラーバランス",
        "tone_curve": "トーンカーブ",
        "gradient_map": "グラデーションマップ",
    }
    choice, ok = QInputDialog.getItem(
        window, "色調整", "種類", [labels[x] for x in FILTERS], 0, False
    )
    if not ok:
        return None
    kind = next(k for k, v in labels.items() if v == choice)
    fields = {
        "blur": [("radius", "半径 (px)", 4, 0, 64)],
        "brightness_contrast": [
            ("brightness", "明るさ (1=元の色)", 1, 0, 3),
            ("contrast", "コントラスト", 1, 0, 3),
        ],
        "hue_saturation": [("hue", "色相 (度)", 0, -360, 360), ("saturation", "彩度", 1, 0, 3)],
        "color_balance": [
            ("red", "赤の増減", 0, -255, 255),
            ("green", "緑の増減", 0, -255, 255),
            ("blue", "青の増減", 0, -255, 255),
        ],
        "tone_curve": [("middle", "入力128の出力", 128, 0, 255)],
    }
    if kind == "gradient_map":
        start = QColorDialog.getColor(QColor(window.brush["color"]), window, "暗い部分の色")
        end = QColorDialog.getColor(QColor(window.end_color), window, "明るい部分の色")
        return (
            {"kind": kind, "stops": [[0, start.name()], [1, end.name()]]}
            if start.isValid() and end.isValid()
            else None
        )
    values = numeric_dialog(window, labels[kind], fields[kind])
    if values is None:
        return None
    if kind == "tone_curve":
        values = {"points": [[0, 0], [128, values["middle"]], [255, 255]]}
    return {"kind": kind, **values}


def filter_dialog(window):
    settings = filter_settings_dialog(window)
    if settings:
        window.mutate({"op": "filter", "settings": settings})


def adjustment_dialog(window, edit=False):
    settings = filter_settings_dialog(window)
    if settings:
        window.mutate(
            {"op": "update_layer", "changes": {"adjustment": settings}}
            if edit
            else {
                "op": "add_layer",
                "kind": "adjustment",
                "name": "色調補正",
                "adjustment": settings,
                "group_id": window.doc.layer().group_id,
            }
        )


def import_dialog(window):
    path, _ = QFileDialog.getOpenFileName(
        window, "画像を読み込む", "", "Images (*.png *.jpg *.jpeg *.webp)"
    )
    if path:
        try:
            window.mutate({"op": "import_image", "data": canonical_image(path)})
        except Exception as e:
            QMessageBox.warning(window, "読み込み失敗", str(e))


def enclose_selection(window):
    bbox = window.doc.selection.getbbox() if window.doc.selection is not None else None
    if bbox:
        x0, y0, x1, y1 = bbox
        window.mutate(
            {
                "op": "fill",
                "mode": "enclosed",
                "points": [[x0, y0], [x1 - 1, y0], [x1 - 1, y1 - 1], [x0, y1 - 1]],
                "color": window.brush["color"],
                **fill_settings(window),
            }
        )
    else:
        window.statusBar().showMessage("投げ縄などで囲ってから実行してください", 4000)
