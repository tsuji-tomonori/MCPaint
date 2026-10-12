"""Generate a native-app screenshot, editable demo and recording for visual QA."""

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from mcpaint.app import PaintWindow
from mcpaint.engine import Document, png_bytes
from mcpaint.timelapse import export_timelapse

root = Path(__file__).resolve().parents[1]
os.environ["MCPAINT_HOME"] = str(root / "build" / "demo-home")
app = QApplication([])
font = root / "build" / "NotoSansCJKjp-Regular.otf"
if font.exists():
    QFontDatabase.addApplicationFont(str(font))
window = PaintWindow(start_bridge=False, recover=False)
window.doc = Document(960, 640, "#fbf8f1")


def line(points, color="#294451", size=4, brush="pen", opacity=1):
    window.doc.execute(
        {
            "op": "stroke",
            "color": color,
            "size": size,
            "brush": brush,
            "opacity": opacity,
            "points": [
                {"x": x, "y": y, "pressure": 0.85 + 0.15 * math.sin(i / 9), "t_ms": i * 18}
                for i, (x, y) in enumerate(points)
            ],
        }
    )


def curve(a, b, c, d, **kwargs):
    line(
        [
            (
                (1 - t) ** 3 * a[0]
                + 3 * (1 - t) ** 2 * t * b[0]
                + 3 * (1 - t) * t * t * c[0]
                + t**3 * d[0],
                (1 - t) ** 3 * a[1]
                + 3 * (1 - t) ** 2 * t * b[1]
                + 3 * (1 - t) * t * t * c[1]
                + t**3 * d[1],
            )
            for t in [i / 40 for i in range(41)]
        ],
        **kwargs,
    )


def arc(x, y, rx, ry, start=0, end=math.tau, **kwargs):
    line(
        [
            (
                x + rx * math.cos(start + (end - start) * i / 80),
                y + ry * math.sin(start + (end - start) * i / 80),
            )
            for i in range(81)
        ],
        **kwargs,
    )


window.doc.execute({"op": "add_layer", "name": "空と遠くの山"})
arc(742, 151, 41, 41, color="#efbd63", size=32, brush="marker")
curve((80, 278), (210, 120), (230, 178), (372, 275), color="#abc9ca", size=45, brush="marker")
curve((294, 276), (440, 74), (482, 180), (657, 277), color="#abc9ca", size=45, brush="marker")
curve((515, 274), (650, 150), (752, 182), (876, 281), color="#bad1c7", size=38, brush="marker")
window.doc.execute({"op": "add_layer", "name": "川辺のスケッチ"})
curve((66, 424), (240, 379), (727, 373), (902, 424), color="#74897d", size=3, brush="pencil")
for i in range(5):
    curve(
        (110 + i * 28, 470 + i * 16),
        (290, 445 + i * 18),
        (580, 515 + i * 11),
        (840 - i * 31, 462 + i * 24),
        color="#66aaa9",
        size=6,
        brush="marker",
    )
for x, y in [(144, 322), (798, 322), (833, 348)]:
    line([(x, y + 95), (x, y)], color="#4e8076", size=3)
    curve(
        (x, y + 63),
        (x - 45, y + 25),
        (x - 51, y + 52),
        (x, y + 77),
        color="#86b096",
        size=10,
        brush="marker",
    )
    curve(
        (x, y + 35),
        (x + 44, y - 7),
        (x + 59, y + 13),
        (x, y + 54),
        color="#86b096",
        size=10,
        brush="marker",
    )
window.doc.execute({"op": "add_layer", "name": "猫の線画"})
curve((413, 335), (372, 350), (360, 413), (405, 419), size=4)
curve((405, 419), (440, 430), (528, 434), (572, 418), size=4)
curve((572, 418), (605, 384), (556, 357), (542, 337), size=4)
# Face and pointed ears, separate strokes preserve the handmade line endings.
curve((413, 335), (397, 330), (395, 299), (411, 286), size=4)
line([(411, 286), (405, 239), (449, 266)], size=4)
curve((449, 266), (476, 251), (502, 260), (516, 267), size=4)
line([(516, 267), (553, 239), (549, 288)], size=4)
curve((549, 288), (565, 312), (552, 341), (529, 350), size=4)
curve((529, 350), (491, 374), (431, 367), (413, 335), size=4)
arc(445, 311, 10, 9, start=math.pi, end=math.tau, size=3)
arc(515, 311, 10, 9, start=math.pi, end=math.tau, size=3)
line([(474, 325), (485, 325), (480, 331), (474, 325)], color="#cc837c", size=3)
curve((480, 331), (480, 343), (466, 342), (462, 337), size=2.6)
curve((480, 331), (480, 343), (494, 342), (498, 337), size=2.6)
for y, delta in [(323, -10), (335, 1), (346, 11)]:
    line([(432, y), (391, y + delta)], size=2)
    line([(531, y), (573, y + delta)], size=2)
curve((421, 414), (404, 408), (450, 395), (456, 421), size=3)
curve((503, 424), (505, 394), (548, 408), (536, 423), size=3)
curve((564, 409), (668, 380), (654, 312), (619, 344), size=11, color="#d4a179", brush="marker")
curve((564, 409), (668, 380), (654, 312), (619, 344), size=3)
window.doc.execute({"op": "add_layer", "name": "ブラシと色の試し描き"})
for i, brush in enumerate(["pen", "pencil", "marker", "airbrush"]):
    curve(
        (226 + i * 128, 570),
        (246 + i * 128, 551),
        (262 + i * 128, 592),
        (288 + i * 128, 568),
        color=["#294451", "#cc837c", "#66aaa9", "#efbd63"][i],
        size=14,
        brush=brush,
    )
window.refresh()
window.show()
app.processEvents()
(root / "docs" / "screenshot.png").write_bytes(png_bytes(window.grab().toImage()))
folder = root / "build" / "demo"
folder.mkdir(parents=True, exist_ok=True)
window.doc.save(folder / "river-cat.mcpaint")
(folder / "river-cat.png").write_bytes(png_bytes(window.doc.composite()))
export_timelapse(window.doc, folder / "river-cat.mp4", max_frames=240)
window.close()
print("Generated native UI screenshot and editable timelapse demo")
