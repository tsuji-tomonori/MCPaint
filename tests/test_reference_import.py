import base64

import pytest
from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import Qt

from mcpaint import ui_tools
from mcpaint.app import PaintWindow
from mcpaint.engine import Document, png_bytes
from mcpaint.operations import pil
from mcpaint.timelapse import replay_frames


@pytest.mark.parametrize("extension", ["png", "jpg"])
def test_reference_import_trace_hide_and_self_contained_roundtrip(extension, tmp_path):
    source = tmp_path / f"お手本.{extension}"
    Image.new(
        "RGBA" if extension == "png" else "RGB",
        (40, 20),
        (220, 40, 60, 128) if extension == "png" else (220, 40, 60),
    ).save(source)
    doc = Document(100, 80)
    drawing = doc.active_id
    doc.execute({"op": "select_region", "kind": "rect", "rect": [0, 0, 4, 4]})
    imported = doc.execute({"op": "import_image_layer", "data": ui_tools.image_data(source)})
    ref = doc.layer(imported["id"])
    assert doc.layers[0].id == ref.id and doc.active_id == drawing
    assert ref.locked and ref.opacity == 0.5 and ref.group_id is None
    assert ref.image.pixelColor(50, 40).alpha() == (128 if extension == "png" else 255)
    assert ref.image.pixelColor(50, 10).alpha() == 0  # Aspect ratio and centering.
    assert doc.layer(drawing).image.pixelColor(50, 40).alpha() == 0
    before = png_bytes(doc.composite())
    doc.undo()
    assert len(doc.layers) == 1 and doc.active_id == drawing
    doc.redo()
    assert png_bytes(doc.composite()) == before
    with pytest.raises(ValueError, match="ロック"):
        doc.execute(
            {"op": "stroke", "layer_id": ref.id, "brush": "pen", "points": [{"x": 50, "y": 40}]}
        )
    doc.execute({"op": "selection_edit", "action": "clear"})
    doc.execute(
        {
            "op": "stroke",
            "brush": "pen",
            "color": "#123456",
            "size": 3,
            "points": [{"x": 20, "y": 40}, {"x": 80, "y": 40}],
        }
    )
    doc.execute({"op": "update_layer", "layer_id": ref.id, "changes": {"visible": False}})
    assert doc.composite().pixelColor(50, 40).name() == "#123456"
    assert doc.composite().pixelColor(50, 25).name() == "#ffffff"
    source.unlink()
    project = tmp_path / "trace.mcpaint"
    doc.save(project)
    restored = Document.load(project)
    assert png_bytes(restored.composite()) == png_bytes(doc.composite())
    assert not restored.layer(ref.id).visible and restored.layer(ref.id).locked
    assert restored.layer(ref.id).image == ref.image
    assert (
        list(replay_frames(restored, 16, 100))[-1].tobytes()
        == pil(doc.composite()).convert("RGB").tobytes()
    )


def test_jpeg_exif_orientation_and_regular_layer_inside_folder(tmp_path):
    source = tmp_path / "portrait.jpeg"
    image = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    doc = Document(100, 80)
    group = doc.execute({"op": "add_layer", "kind": "group"})["id"]
    command = doc.execute(
        {
            "op": "import_image_layer",
            "data": ui_tools.image_data(source),
            "placement": "above",
            "fit": "original",
            "opacity": 1,
            "locked": False,
            "select_imported": True,
        }
    )
    layer = doc.layer(command["id"])
    assert layer.group_id == group and doc.active_id == layer.id
    assert pil(layer.image).getbbox() == (40, 20, 60, 60)  # EXIF turns 40x20 into 20x40.
    doc.execute({"op": "update_layer", "layer_id": group, "changes": {"locked": True}})
    before = doc.payload()
    with pytest.raises(ValueError, match="ロック"):
        doc.execute({"op": "import_image_layer", "data": command["data"], "placement": "above"})
    assert doc.payload() == before
    # Back references are independent of the currently selected locked folder.
    ref = doc.execute({"op": "import_image_layer", "data": command["data"]})
    assert doc.layer(ref["id"]).group_id is None


def test_invalid_image_import_is_atomic():
    doc = Document(100, 80)
    before = doc.payload()
    with pytest.raises(UnidentifiedImageError):
        doc.execute({"op": "import_image_layer", "data": base64.b64encode(b"invalid").decode()})
    assert doc.payload() == before and len(doc.layers) == 1


def test_native_reference_menu_keeps_drawing_separate_and_visibility_toggle(
    qapp, tmp_path, monkeypatch
):
    source = tmp_path / "reference.png"
    Image.new("RGB", (160, 100), "#ff0000").save(source)
    monkeypatch.setattr(ui_tools.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    window = PaintWindow(start_bridge=False, recover=False)
    try:
        window.doc = Document(160, 100)
        window.show()
        qapp.processEvents()
        drawing = window.doc.active_id
        menu = next(
            action.menu() for action in window.menuBar().actions() if action.text() == "画像"
        )
        next(action for action in menu.actions() if action.text().startswith("参考画像")).trigger()
        reference = window.doc.layers[0]
        assert reference.name == "reference" and reference.locked
        assert window.doc.active_id == drawing
        window.handle(
            {
                "op": "stroke",
                "points": [{"x": 20, "y": 40}, {"x": 100, "y": 40}],
                "color": "#123456",
                "size": 3,
            }
        )
        item = next(
            window.layers_list.item(i)
            for i in range(window.layers_list.count())
            if window.layers_list.item(i).data(Qt.ItemDataRole.UserRole) == reference.id
        )
        item.setCheckState(Qt.CheckState.Unchecked)
        assert not reference.visible
        assert window.doc.composite().pixelColor(60, 40).name() == "#123456"
        assert window.doc.composite().pixelColor(60, 20).name() == "#ffffff"
        next(
            action for action in menu.actions() if action.text().startswith("画像を新しい")
        ).trigger()
        assert len(window.doc.layers) == 3
        assert window.doc.layer().id not in (reference.id, drawing)
        assert not window.doc.layer().locked and window.doc.layer().opacity == 1
    finally:
        window.close()
