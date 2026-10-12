import base64

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from mcpaint.app import PaintWindow
from mcpaint.engine import Document


@pytest.fixture
def window(qapp):
    w = PaintWindow(start_bridge=False, recover=False)
    w.doc = Document(160, 100)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_mcp_screen_crop_scale_and_shared_state(window):
    result = window.handle(
        {"op": "screenshot", "grid": True, "crop": [20, 10, 100, 80], "max_size": 64}
    )
    assert base64.b64decode(result["image"]).startswith(b"\x89PNG")
    assert result["image_info"]["origin"] == [20, 10]
    assert result["image_info"]["image_size"] == [64, 51]
    revision = result["state"]["revision"]
    window.handle(
        {
            "op": "stroke",
            "points": [{"x": 20, "y": 30}, {"x": 130, "y": 30}],
            "expected_revision": revision,
        }
    )
    assert window.doc.composite().pixelColor(60, 30).name() == window.brush["color"]
    with pytest.raises(ValueError, match="版"):
        window.handle(
            {"op": "stroke", "points": [{"x": 20, "y": 30}], "expected_revision": revision}
        )
    window.handle(
        {"op": "set_brush", "brush": "marker", "color": "#123456", "size": 30, "opacity": 0.5}
    )
    assert window.brush_combo.currentData() == "marker"
    assert window.size_spin.value() == 30
    assert window.handle({"op": "screenshot", "scope": "window"})["image"]


def test_actual_mouse_drag_records_path(window, qapp):
    origin, scale = window.canvas.geometry_info()
    a = (origin + QPointF(20 * scale, 40 * scale)).toPoint()
    b = (origin + QPointF(120 * scale, 40 * scale)).toPoint()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(window.canvas, b)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=b)
    qapp.processEvents()
    assert window.doc.revision == 1
    assert len(window.doc.timeline[0]["command"]["points"]) >= 2
    assert window.doc.composite().pixelColor(60, 40).name() == window.brush["color"]


def test_new_canvas_checkpoints_and_autosave(window, tmp_path):
    window.handle({"op": "stroke", "points": [{"x": 50, "y": 50}]})
    window.handle({"op": "new_canvas", "width": 200, "height": 100})
    assert list((tmp_path / "home" / "checkpoints").glob("*.mcpaint"))
    window.autosave()
    assert Document.load(tmp_path / "home" / "autosave.mcpaint").width == 200
