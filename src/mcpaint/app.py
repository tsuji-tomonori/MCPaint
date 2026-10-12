from __future__ import annotations

import base64
import json
import math
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .bridge import Bridge, clone_document, data_dir
from .engine import BRUSHES, Document, color, draw_stroke, number, png_bytes
from .timelapse import export_timelapse

BRUSH_NAMES = {
    "pen": "ペン",
    "pencil": "鉛筆",
    "marker": "マーカー",
    "airbrush": "エアブラシ",
    "eraser": "消しゴム",
}


class Canvas(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.points = []
        self.stroke = None
        self.preview = None
        self.position = None
        self.zoom = 1.0
        self.pan = QPointF()
        self.pan_anchor = None

    def geometry_info(self):
        d = self.window.doc
        fit = min((self.width() - 72) / d.width, (self.height() - 72) / d.height)
        scale = max(0.01, fit * self.zoom)
        origin = (
            QPointF((self.width() - d.width * scale) / 2, (self.height() - d.height * scale) / 2)
            + self.pan
        )
        return origin, scale

    def document_point(self, position, clamp=False):
        origin, scale = self.geometry_info()
        x, y = (position.x() - origin.x()) / scale, (position.y() - origin.y()) / scale
        d = self.window.doc
        if clamp:
            return max(0, min(d.width - 1, x)), max(0, min(d.height - 1, y))
        return (x, y) if 0 <= x < d.width and 0 <= y < d.height else None

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#18202d"))
        p.setPen(QColor("#283243"))
        for y in range(16, self.height(), 24):
            for x in range(16, self.width(), 24):
                p.drawPoint(x, y)
        origin, scale = self.geometry_info()
        d = self.window.doc
        area = QRectF(origin.x(), origin.y(), d.width * scale, d.height * scale)
        p.fillRect(area.adjusted(4, 4, 4, 4), QColor("#0c111a"))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        image = self.preview if self.preview is not None else d.composite()
        p.drawImage(area, image)
        p.setPen(QColor("#8795ac"))
        p.drawRect(area)
        p.drawText(
            QPointF(origin.x(), max(18, origin.y() - 12)), f"0, 0   ·   {d.width} × {d.height} px"
        )
        if self.position is not None and self.document_point(self.position) is not None:
            radius = max(3, self.window.brush["size"] * scale / 2)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawEllipse(self.position, radius, radius)
            p.setPen(QPen(QColor("#22334a"), 1))
            p.drawEllipse(self.position, radius, radius)
            p.drawLine(self.position + QPointF(-4, 0), self.position + QPointF(4, 0))
            p.drawLine(self.position + QPointF(0, -4), self.position + QPointF(0, 4))

    def begin(self, position, pressure=1.0):
        point = self.document_point(position)
        if point is None:
            return
        if self.window.doc.layer().locked:
            self.window.statusBar().showMessage("レイヤーはロックされています", 3000)
            return
        self.started = time.monotonic()
        self.points = []
        self.stroke = {
            "op": "stroke",
            "layer_id": self.window.doc.active_id,
            **self.window.brush.copy(),
            "points": self.points,
        }
        self.append(position, pressure)

    def append(self, position, pressure=1.0):
        self.position = position
        point = self.document_point(position, clamp=True)
        if self.stroke and point and len(self.points) < 20000:
            x, y = point
            if self.points and math.hypot(x - self.points[-1]["x"], y - self.points[-1]["y"]) < 0.3:
                return
            self.points.append(
                {
                    "x": x,
                    "y": y,
                    "pressure": pressure,
                    "t_ms": min(120000, (time.monotonic() - self.started) * 1000),
                }
            )
            layer = self.window.doc.layer(self.stroke["layer_id"])
            saved = layer.image
            layer.image = saved.copy()
            draw_stroke(layer.image, self.stroke)
            self.preview = self.window.doc.composite()
            layer.image = saved
        self.update()

    def finish(self):
        stroke = self.stroke
        self.stroke = None
        self.preview = None
        self.points = []
        if stroke:
            self.window.mutate(stroke)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_anchor = event.position()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.begin(event.position())

    def mouseMoveEvent(self, event):
        if self.pan_anchor is not None:
            self.pan += event.position() - self.pan_anchor
            self.pan_anchor = event.position()
            self.update()
            return
        self.append(event.position())
        point = self.document_point(event.position())
        if point:
            self.window.coordinate_label.setText(f"X {point[0]:.0f}   Y {point[1]:.0f}")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_anchor = None
        elif event.button() == Qt.MouseButton.LeftButton:
            self.append(event.position())
            self.finish()

    def tabletEvent(self, event):
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.TabletPress:
            self.begin(event.position(), event.pressure())
        elif event.type() == QEvent.Type.TabletMove:
            self.append(event.position(), event.pressure())
        else:
            self.finish()
        event.accept()

    def wheelEvent(self, event):
        self.zoom = max(
            0.25, min(8, self.zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15))
        )
        self.window.zoom_label.setText(f"表示 {self.zoom:.0%}")
        self.update()


class PaintWindow(QMainWindow):
    export_done = Signal(str, str)

    def __init__(self, start_bridge=True, recover=True):
        super().__init__()
        self.doc = Document()
        self.brush = {"brush": "pen", "color": "#24334a", "size": 5.0, "opacity": 1.0}
        self.project_path = None
        self.autosave_path = data_dir() / "autosave.mcpaint"
        self.export_running = False
        if recover and self.autosave_path.exists():
            try:
                self.doc = Document.load(self.autosave_path)
            except Exception:
                pass
        self.setWindowTitle(f"MCPaint {__version__} — ローカル ペイントスタジオ")
        self.resize(1320, 880)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #101723; color: #e4eaf3; font-family: 'Yu Gothic UI', 'Meiryo', 'Segoe UI', 'Noto Sans CJK JP'; font-size: 13px; }
            QLabel#brand { font-size: 24px; font-weight: 700; color: #71dcca; }
            QLabel#section { font-size: 11px; font-weight: 700; color: #93a3bd; padding-top: 12px; }
            QPushButton, QComboBox, QSpinBox, QDoubleSpinBox { background: #243045; border: 1px solid #34435b; border-radius: 6px; padding: 7px; }
            QPushButton:hover { background: #33445e; }
            QPushButton:checked { border: 1px solid #71dcca; background: #284e50; }
            QPushButton:disabled { color: #65718a; }
            QListWidget { background: #192335; border: 1px solid #34435b; border-radius: 6px; }
            QListWidget::item { padding: 11px; }
            QListWidget::item:selected { background: #2b5557; }
            QMenuBar, QMenu, QStatusBar { background: #151e2d; }
            QSlider::groove:horizontal { background: #34435b; height: 5px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #71dcca; width: 14px; margin: -5px 0; border-radius: 7px; }
        """)
        splitter = QSplitter()
        self.canvas = Canvas(self)
        side = QWidget()
        side.setMinimumWidth(245)
        side.setMaximumWidth(290)
        panel = QVBoxLayout(side)
        panel.setContentsMargins(18, 18, 18, 16)
        brand = QLabel("MCPaint")
        brand.setObjectName("brand")
        panel.addWidget(brand)
        panel.addWidget(QLabel("線を描く。過程を残す。"))

        def section(title):
            label = QLabel(title)
            label.setObjectName("section")
            panel.addWidget(label)

        section("BRUSH / ブラシ")
        self.brush_combo = QComboBox()
        for key, name in BRUSH_NAMES.items():
            self.brush_combo.addItem(name, key)
        self.brush_combo.currentIndexChanged.connect(
            lambda: self.brush.update(brush=self.brush_combo.currentData())
        )
        panel.addWidget(self.brush_combo)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.choose_color)
        panel.addWidget(self.color_button)
        swatches = QHBoxLayout()
        for hex_color in ("#24334a", "#e96f70", "#e9b85f", "#50bfa6", "#698cdb", "#ffffff"):
            button = QPushButton()
            button.setFixedSize(28, 28)
            button.setStyleSheet(
                f"background:{hex_color}; border-radius: 14px; border:1px solid #78869c;"
            )
            button.clicked.connect(lambda checked=False, c=hex_color: self.set_color(c))
            swatches.addWidget(button)
        panel.addLayout(swatches)
        form = QFormLayout()
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(0.5, 300)
        self.size_spin.setValue(5)
        self.size_spin.setSuffix(" px")
        self.size_spin.valueChanged.connect(lambda v: self.brush.update(size=v))
        form.addRow("太さ", self.size_spin)
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setValue(100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.valueChanged.connect(lambda v: self.brush.update(opacity=v / 100))
        form.addRow("濃さ", self.opacity_spin)
        panel.addLayout(form)
        section("LAYERS / レイヤー")
        self.layers_list = QListWidget()
        self.layers_list.setMinimumHeight(140)
        self.layers_list.currentItemChanged.connect(self.select_layer)
        self.layers_list.itemChanged.connect(self.toggle_layer)
        self.layers_list.itemDoubleClicked.connect(self.rename_layer)
        panel.addWidget(self.layers_list, 1)
        layer_buttons = QHBoxLayout()
        for label, callback in (
            ("＋", lambda: self.mutate({"op": "add_layer"})),
            ("−", lambda: self.mutate({"op": "delete_layer"})),
            ("↑", lambda: self.move_layer(1)),
            ("↓", lambda: self.move_layer(-1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            layer_buttons.addWidget(button)
        panel.addLayout(layer_buttons)
        self.lock_check = QCheckBox("選択レイヤーをロック")
        self.lock_check.toggled.connect(
            lambda v: self.mutate({"op": "update_layer", "changes": {"locked": v}})
        )
        panel.addWidget(self.lock_check)
        self.layer_opacity = QSlider(Qt.Orientation.Horizontal)
        self.layer_opacity.setRange(0, 100)
        self.layer_opacity.sliderReleased.connect(
            lambda: self.mutate(
                {"op": "update_layer", "changes": {"opacity": self.layer_opacity.value() / 100}}
            )
        )
        panel.addWidget(QLabel("レイヤーの不透明度"))
        panel.addWidget(self.layer_opacity)
        section("RECORD / 制作記録")
        self.record_label = QLabel()
        panel.addWidget(self.record_label)
        panel.addWidget(QLabel("線・筆圧・取り消しを自動記録\nプロジェクトに保存できます。"))
        export_button = QPushButton("タイムラプスを書き出す")
        export_button.clicked.connect(self.export_dialog)
        panel.addWidget(export_button)
        self.connection_label = QLabel("● MCP 接続待機中 / ローカル専用")
        self.connection_label.setStyleSheet("color: #71dcca; font-size: 11px;")
        panel.addWidget(self.connection_label)
        splitter.addWidget(self.canvas)
        splitter.addWidget(side)
        splitter.setSizes([1030, 270])
        self.setCentralWidget(splitter)
        self.coordinate_label = QLabel("X —   Y —")
        self.zoom_label = QLabel("表示 100%  ·  ホイールで拡大 / 中ボタンで移動")
        self.statusBar().addWidget(self.coordinate_label)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.build_menus()
        self.export_done.connect(self.on_export_done)
        self.bridge = Bridge() if start_bridge else None
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.bridge.drain(self.handle) if self.bridge else None)
        self.timer.start(15)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.autosave)
        self.set_color(self.brush["color"])
        self.refresh()

    def build_menus(self):
        file_menu = self.menuBar().addMenu("ファイル")
        edit_menu = self.menuBar().addMenu("編集")
        help_menu = self.menuBar().addMenu("接続")
        for menu, text, shortcut, callback in (
            (file_menu, "新しいキャンバス", "Ctrl+N", self.new_dialog),
            (file_menu, "プロジェクトを開く", "Ctrl+O", self.open_dialog),
            (file_menu, "プロジェクトを保存", "Ctrl+S", self.save_dialog),
            (file_menu, "PNGを書き出す", "Ctrl+Shift+S", self.png_dialog),
            (file_menu, "タイムラプスを書き出す", "", self.export_dialog),
            (edit_menu, "元に戻す", "Ctrl+Z", lambda: self.history_action("undo")),
            (edit_menu, "やり直す", "Ctrl+Y", lambda: self.history_action("redo")),
            (edit_menu, "表示をフィット", "Ctrl+0", self.fit_canvas),
            (help_menu, "MCP設定をコピー", "", self.copy_config),
            (help_menu, "使い方", "F1", self.show_help),
        ):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            menu.addAction(action)

    def refresh(self):
        self.layers_list.blockSignals(True)
        self.layers_list.clear()
        for layer in reversed(self.doc.layers):
            item = QListWidgetItem(("🔒 " if layer.locked else "") + layer.name)
            item.setData(Qt.ItemDataRole.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            self.layers_list.addItem(item)
            if layer.id == self.doc.active_id:
                self.layers_list.setCurrentItem(item)
        self.layers_list.blockSignals(False)
        self.lock_check.blockSignals(True)
        self.lock_check.setChecked(self.doc.layer().locked)
        self.lock_check.blockSignals(False)
        self.layer_opacity.setValue(round(self.doc.layer().opacity * 100))
        self.record_label.setText(f"● REC   {len(self.doc.timeline)} 操作を記録")
        self.canvas.update()

    def changed(self):
        self.refresh()
        self.save_timer.start(350)

    def mutate(self, command):
        try:
            self.doc.execute(command)
            self.changed()
        except Exception as e:
            self.statusBar().showMessage(str(e), 5000)

    def autosave(self):
        try:
            self.doc.save(self.autosave_path)
        except Exception as e:
            self.statusBar().showMessage(f"自動保存に失敗: {e}", 7000)

    def history_action(self, op):
        if getattr(self.doc, op)():
            self.changed()

    def select_layer(self, item, previous):
        if item:
            self.doc.active_id = item.data(Qt.ItemDataRole.UserRole)
            self.refresh()

    def toggle_layer(self, item):
        self.mutate(
            {
                "op": "update_layer",
                "layer_id": item.data(Qt.ItemDataRole.UserRole),
                "changes": {"visible": item.checkState() == Qt.CheckState.Checked},
            }
        )

    def rename_layer(self, item):
        layer = self.doc.layer(item.data(Qt.ItemDataRole.UserRole))
        name, ok = QInputDialog.getText(self, "レイヤー名", "名前", text=layer.name)
        if ok:
            self.mutate({"op": "update_layer", "layer_id": layer.id, "changes": {"name": name}})

    def move_layer(self, offset):
        index = self.doc.layers.index(self.doc.layer())
        self.mutate(
            {"op": "move_layer", "index": max(0, min(len(self.doc.layers) - 1, index + offset))}
        )

    def set_color(self, value):
        self.brush["color"] = color(value)
        self.color_button.setText(f"色   {value.upper()}")
        self.color_button.setStyleSheet(f"border-left: 16px solid {value};")

    def choose_color(self):
        result = QColorDialog.getColor(QColor(self.brush["color"]), self, "ブラシの色")
        if result.isValid():
            self.set_color(result.name())

    def fit_canvas(self):
        self.canvas.zoom = 1
        self.canvas.pan = QPointF()
        self.zoom_label.setText("表示 100%  ·  ホイールで拡大 / 中ボタンで移動")
        self.canvas.update()

    def checkpoint(self):
        if self.doc.timeline:
            self.doc.save(data_dir() / "checkpoints" / f"before-switch-{time.time_ns()}.mcpaint")

    def new_dialog(self):
        width, ok = QInputDialog.getInt(self, "キャンバスの幅", "幅 (px)", 1280, 1, 4096)
        if not ok:
            return
        height, ok = QInputDialog.getInt(self, "キャンバスの高さ", "高さ (px)", 800, 1, 4096)
        if ok:
            self.checkpoint()
            self.doc = Document(width, height)
            self.project_path = None
            self.fit_canvas()
            self.changed()

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "プロジェクトを開く", "", "MCPaint (*.mcpaint)")
        if path:
            try:
                doc = Document.load(path)
                self.checkpoint()
                self.doc, self.project_path = doc, path
                self.fit_canvas()
                self.changed()
            except Exception as e:
                QMessageBox.warning(self, "開けません", str(e))

    def save_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "プロジェクトを保存",
            self.project_path or "drawing.mcpaint",
            "MCPaint (*.mcpaint)",
        )
        if path:
            self.doc.save(path)
            self.project_path = path
            self.statusBar().showMessage("プロジェクトを保存しました", 3000)

    def png_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "PNGを書き出す", "drawing.png", "PNG (*.png)")
        if path:
            Path(path).write_bytes(png_bytes(self.doc.composite()))

    def export_dialog(self):
        if self.export_running:
            self.statusBar().showMessage("タイムラプスを書き出しています", 3000)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "タイムラプスを書き出す", "timelapse.mp4", "MP4 (*.mp4);;GIF (*.gif)"
        )
        if path:
            snapshot = clone_document(self.doc)
            self.export_running = True
            self.statusBar().showMessage("タイムラプスを書き出しています…")

            def work():
                try:
                    self.export_done.emit(export_timelapse(snapshot, path), "")
                except Exception as e:
                    self.export_done.emit("", str(e))

            threading.Thread(target=work, daemon=True).start()

    def on_export_done(self, path, error):
        self.export_running = False
        self.statusBar().showMessage(
            f"書き出しました: {path}" if not error else f"書き出し失敗: {error}", 8000
        )

    def copy_config(self):
        if getattr(sys, "frozen", False):
            command, args = str(Path(sys.executable).with_name("MCPaint-MCP.exe")), []
        else:
            command, args = sys.executable, ["-m", "mcpaint", "--mcp"]
        text = json.dumps(
            {"mcpServers": {"mcpaint": {"command": command, "args": args}}},
            ensure_ascii=False,
            indent=2,
        )
        QApplication.clipboard().setText(text)
        QMessageBox.information(
            self,
            "MCP設定",
            "設定をクリップボードにコピーしました。\n\nCodex CLI / Desktopでこの実行ファイルをstdio MCPサーバーとして登録してください。\n同じPC上のクライアントから操作できます。",
        )

    def show_help(self):
        QMessageBox.information(
            self,
            "MCPaint",
            "ドラッグ: 描画 / タブレット: 筆圧に対応\nホイール: 拡大縮小 / 中ボタン: 表示の移動\nCtrl+Z: 元に戻す / Ctrl+Y: やり直す\nレイヤーのチェック: 表示切替 / ダブルクリック: 名前変更\n\n制作過程は常に記録され、プロジェクトに保存されます。\nMCP操作は同じ画面を更新し、操作後の画像を返します。\n接続メニューからMCP設定をコピーできます。",
        )

    def handle(self, request):
        op = request["op"]
        if self.canvas.stroke is not None and op != "screenshot":
            raise ValueError("手で描画中です。ストローク終了後に操作してください")
        if (
            request.get("expected_revision") is not None
            and request["expected_revision"] != self.doc.revision
        ):
            raise ValueError("画面の版が変わりました。screenshotで現在の画像を確認してください")
        extra = {}
        if op == "new_canvas":
            doc = Document(
                request.get("width", 1280),
                request.get("height", 800),
                request.get("background", "#ffffff"),
            )
            self.checkpoint()
            doc.revision = self.doc.revision + 1
            self.doc = doc
            self.project_path = None
            self.fit_canvas()
            self.changed()
        elif op == "set_brush":
            values = {k: v for k, v in request.items() if k in self.brush and v is not None}
            candidate = {**self.brush, **values}
            if candidate["brush"] not in BRUSHES:
                raise ValueError("無効なブラシです")
            color(candidate["color"])
            number(candidate["size"], 0.5, 300, "size")
            number(candidate["opacity"], 0, 1, "opacity")
            self.brush = candidate
            self.brush_combo.setCurrentIndex(BRUSHES.index(candidate["brush"]))
            self.size_spin.setValue(candidate["size"])
            self.opacity_spin.setValue(round(candidate["opacity"] * 100))
            self.set_color(candidate["color"])
        elif op in (
            "stroke",
            "add_layer",
            "update_layer",
            "delete_layer",
            "move_layer",
            "clear_layer",
        ):
            command = {**self.brush, **request} if op == "stroke" else request
            self.doc.execute(command)
            self.changed()
        elif op == "select_layer":
            self.doc.active_id = self.doc.layer(request["layer_id"]).id
            self.changed()
        elif op in ("undo", "redo"):
            getattr(self.doc, op)()
            self.changed()
        elif op == "save_project":
            extra["path"] = self.doc.save(request["path"])
            self.project_path = extra["path"]
        elif op == "open_project":
            doc = Document.load(request["path"])
            self.checkpoint()
            doc.revision = self.doc.revision + 1
            self.doc = doc
            self.project_path = request["path"]
            self.fit_canvas()
            self.changed()
        elif op == "export_png":
            path = Path(request["path"]).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png_bytes(self.doc.composite(request.get("background", True))))
            extra["path"] = str(path)
        elif op == "export_timelapse":
            if self.export_running:
                raise ValueError("タイムラプスを書き出し中です")
            extra["path"] = export_timelapse(
                clone_document(self.doc),
                request["path"],
                request.get("fps", 20),
                request.get("max_frames", 240),
                request.get("max_size", 800),
            )
        elif op != "screenshot":
            raise ValueError("未知の操作です")
        self.connection_label.setText("● MCP 操作を受信 / ローカル専用")
        self.canvas.repaint()
        scope = request.get("scope", "canvas")
        if scope not in ("canvas", "window"):
            raise ValueError("scopeはcanvasかwindowです")
        image = (
            self.grab().toImage()
            if scope == "window"
            else self.canvas.preview.copy()
            if self.canvas.preview is not None
            else self.doc.composite()
        )
        origin = [0, 0]
        crop = request.get("crop")
        if crop:
            if scope != "canvas" or len(crop) != 4:
                raise ValueError("crop は canvas の [x,y,width,height] です")
            x, y, w, h = map(int, crop)
            if min(x, y) < 0 or min(w, h) < 1 or x + w > image.width() or y + h > image.height():
                raise ValueError("切り取り範囲はキャンバス内に指定してください")
            image = image.copy(x, y, w, h)
            origin = [x, y]
        if request.get("grid") and scope == "canvas":
            p = QPainter(image)
            p.setPen(QPen(QColor(65, 95, 130, 130), 1))
            for x in range((-origin[0]) % 100, image.width(), 100):
                p.drawLine(x, 0, x, image.height())
                p.drawText(x + 4, 18, str(x + origin[0]))
            for y in range((-origin[1]) % 100, image.height(), 100):
                p.drawLine(0, y, image.width(), y)
                p.drawText(4, y + 16, str(y + origin[1]))
            p.end()
        source_size = [image.width(), image.height()]
        max_size = int(number(request.get("max_size", 1280), 64, 4096, "max_size"))
        if max(source_size) > max_size:
            image = image.scaled(
                max_size,
                max_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return {
            "state": self.doc.state(),
            "brush": self.brush,
            **extra,
            "image": base64.b64encode(png_bytes(image)).decode(),
            "image_info": {
                "scope": scope,
                "origin": origin,
                "source_size": source_size,
                "image_size": [image.width(), image.height()],
                "canvas_pixels_per_image_pixel": source_size[0] / image.width()
                if scope == "canvas"
                else None,
            },
        }

    def closeEvent(self, event):
        if self.export_running:
            QMessageBox.information(
                self, "書き出し中", "タイムラプスの書き出しが完了してから閉じてください。"
            )
            event.ignore()
            return
        self.canvas.finish()
        self.autosave()
        if self.bridge:
            self.bridge.close()
        event.accept()


def run_app():
    from .mcp_server import existing_session

    if existing_session():
        return 0
    app = QApplication(sys.argv[:1])
    app.setApplicationName("MCPaint")
    window = PaintWindow()
    window.show()
    return app.exec()
