import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from mcpaint.app import PaintWindow
from mcpaint.engine import Document


@pytest.fixture
def studio(qapp):
    window = PaintWindow(start_bridge=False, recover=False)
    window.doc = Document(160, 100)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def drag(window, tool, start, end):
    window.tool_combo.setCurrentIndex(window.tool_combo.findData(tool))
    origin, scale = window.canvas.geometry_info()
    a = (origin + QPointF(start[0] * scale, start[1] * scale)).toPoint()
    b = (origin + QPointF(end[0] * scale, end[1] * scale)).toPoint()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(window.canvas, b)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=b)


def test_native_selection_bucket_and_gradient_tools(studio):
    drag(studio, "select_rect", [20, 20], [100, 80])
    assert studio.doc.selection.getpixel((50, 50)) > 200
    assert studio.doc.selection.getpixel((5, 5)) == 0
    drag(studio, "gradient", [20, 20], [100, 80])
    assert studio.doc.layer().image.pixelColor(50, 50).alpha() > 200
    assert studio.doc.layer().image.pixelColor(5, 5).alpha() == 0
    studio.doc.execute({"op": "selection_edit", "action": "clear"})
    studio.refresh()
    studio.set_color("#ff0000")
    drag(studio, "fill", [5, 5], [5, 5])
    assert studio.doc.layer().image.pixelColor(5, 5).red() == 255
    assert studio.doc.timeline[-1]["command"]["op"] == "fill"


def test_native_shapes_and_mirrored_rotated_coordinate_mapping(studio):
    drag(studio, "ellipse", [20, 20], [100, 80])
    assert studio.doc.timeline[-1]["command"]["kind"] == "ellipse"
    studio.handle({"op": "set_view", "flip_horizontal": True, "rotation": 30})
    # A viewport center maps to canvas center even under a rotated view.
    origin, scale = studio.canvas.geometry_info()
    center = origin + QPointF(studio.doc.width * scale / 2, studio.doc.height * scale / 2)
    x, y = studio.canvas.document_point(center)
    assert abs(x - 79) < 0.01 and abs(y - 50) < 0.01
    state = studio.handle({"op": "screenshot"})
    assert state["view"]["rotation"] == 30
    assert state["state"]["coordinates"].startswith("canvas pixels")


def test_mask_edit_does_not_depend_on_unrelated_locked_paint_layer(studio):
    base = studio.doc.active_id
    studio.doc.execute({"op": "update_layer", "changes": {"locked": True}})
    studio.doc.execute({"op": "add_layer", "kind": "group"})
    studio.doc.execute({"op": "mask", "action": "reveal_all"})
    studio.doc.execute(
        {
            "op": "mask_stroke",
            "points": [{"x": 50, "y": 50}],
            "brush": "pen",
            "size": 20,
            "value": 0,
        }
    )
    assert studio.doc.layer().mask.getpixel((50, 50)) == 0
    assert studio.doc.layer(base).locked
