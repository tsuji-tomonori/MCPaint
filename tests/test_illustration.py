import base64
import io

import pytest
from PIL import Image

from mcpaint.engine import Document, png_bytes
from mcpaint.operations import BLEND_MODES, FILTERS, pil
from mcpaint.timelapse import replay_frames


def shape(doc, rect=(10, 10, 40, 40), color="#ff0000", **kwargs):
    return doc.execute(
        {
            "op": "shape",
            "kind": "rect",
            "rect": list(rect),
            "color": color,
            "fill_color": color,
            "size": 1,
            **kwargs,
        }
    )


def add(doc, **kwargs):
    return doc.execute({"op": "add_layer", **kwargs})["id"]


def test_reference_fill_selection_and_gap_closing():
    doc = Document(64, 64)
    line = doc.active_id
    doc.execute(
        {"op": "shape", "kind": "rect", "rect": [10, 10, 40, 40], "color": "#000000", "size": 2}
    )
    paint = add(doc)
    doc.execute({"op": "move_layer", "index": 0})
    doc.execute(
        {
            "op": "fill",
            "point": [20, 20],
            "color": "#e09070",
            "reference": "layer",
            "reference_layer_id": line,
            "expand": 1,
        }
    )
    assert doc.layer(paint).image.pixelColor(25, 25).name() == "#e09070"
    assert doc.layer(paint).image.pixelColor(5, 5).alpha() == 0
    doc.execute(
        {
            "op": "select_region",
            "kind": "wand",
            "point": [0, 0],
            "reference": "layer",
            "reference_layer_id": line,
        }
    )
    doc.execute({"op": "selection_edit", "action": "invert"})
    assert doc.selection.getpixel((20, 20)) == 255
    assert doc.selection.getpixel((0, 0)) == 0
    doc.execute({"op": "fill", "mode": "selection", "color": "#123456"})
    assert doc.layer().image.pixelColor(25, 25).name() == "#123456"
    assert doc.layer().image.pixelColor(5, 5).alpha() == 0
    doc.execute({"op": "selection_edit", "action": "clear"})
    # Erase a two-pixel gap in the reference, then fill without leaking through it.
    doc.active_id = line
    doc.execute({"op": "stroke", "brush": "eraser", "size": 2, "points": [{"x": 30, "y": 10}]})
    doc.active_id = paint
    doc.execute({"op": "clear_layer"})
    doc.execute(
        {
            "op": "fill",
            "point": [20, 20],
            "color": "#ff0000",
            "reference": "layer",
            "reference_layer_id": line,
            "gap_close": 2,
        }
    )
    assert doc.layer().image.pixelColor(20, 20).alpha() > 200
    assert doc.layer().image.pixelColor(0, 0).alpha() == 0


def test_alpha_lock_selection_and_mask_survive_undo_save_and_replay(tmp_path):
    doc = Document(64, 64)
    shape(doc)
    doc.execute({"op": "update_layer", "changes": {"alpha_lock": True}})
    doc.execute({"op": "fill", "mode": "selection", "color": "#0000ff"})
    assert doc.layer().image.pixelColor(30, 30).blue() == 255
    assert doc.layer().image.pixelColor(0, 0).alpha() == 0
    doc.execute({"op": "select_region", "kind": "rect", "rect": [0, 0, 32, 64]})
    doc.execute({"op": "mask", "action": "from_selection"})
    assert doc.composite(False).pixelColor(40, 30).alpha() == 0
    assert doc.layer().image.pixelColor(40, 30).alpha() == 255
    doc.execute({"op": "selection_edit", "action": "clear"})
    doc.execute(
        {"op": "mask_stroke", "points": [{"x": 20, "y": 30}], "value": 0, "size": 8, "brush": "pen"}
    )
    assert doc.composite(False).pixelColor(20, 30).alpha() == 0
    doc.undo()
    assert doc.composite(False).pixelColor(20, 30).alpha() > 200
    doc.redo()
    path = tmp_path / "mask.mcpaint"
    doc.save(path)
    restored = Document.load(path)
    assert png_bytes(restored.composite(False)) == png_bytes(doc.composite(False))
    assert restored.layer().mask.tobytes() == doc.layer().mask.tobytes()
    final = list(replay_frames(doc, 12, 64))[-1]
    assert final.tobytes() == pil(doc.composite()).convert("RGB").tobytes()


def test_clipped_folder_chains_nested_and_hidden_base():
    doc = Document(64, 64)
    base = doc.active_id
    shape(doc, rect=(20, 20, 20, 20), color="#888888")
    folder = add(doc, kind="group", name="colors")
    doc.execute({"op": "update_layer", "changes": {"clipping": True}})
    child = add(doc, group_id=folder)
    doc.execute({"op": "fill", "mode": "selection", "color": "#ff0000"})
    assert doc.composite(False).pixelColor(30, 30).red() == 255
    assert doc.composite(False).pixelColor(0, 0).alpha() == 0
    assert doc.layer(child).image.pixelColor(0, 0).alpha() == 255
    shade = add(doc, group_id=folder)
    doc.execute(
        {
            "op": "update_layer",
            "changes": {"clipping": True, "blend_mode": "multiply", "opacity": 0.5},
        }
    )
    doc.execute({"op": "fill", "mode": "selection", "color": "#000000"})
    assert 110 <= doc.composite().pixelColor(30, 30).red() <= 140
    doc.execute({"op": "update_layer", "layer_id": base, "changes": {"visible": False}})
    assert doc.composite(False).pixelColor(30, 30).alpha() == 0
    doc.undo()
    doc.execute({"op": "update_layer", "layer_id": folder, "changes": {"locked": True}})
    with pytest.raises(ValueError, match="ロック"):
        shape(doc, layer_id=shade)
    doc.undo()
    nested = add(doc, kind="group", group_id=folder)
    with pytest.raises(ValueError, match="循環"):
        doc.execute({"op": "update_layer", "layer_id": folder, "changes": {"group_id": nested}})
    # Flattening a clipped folder must preserve its children, blend, mask and outer opacity.
    doc.execute({"op": "update_layer", "layer_id": folder, "changes": {"opacity": 0.7}})
    doc.execute({"op": "select_region", "kind": "rect", "rect": [0, 0, 32, 64]})
    doc.execute({"op": "mask", "layer_id": folder, "action": "from_selection"})
    before = png_bytes(doc.composite(False))
    doc.execute({"op": "flatten_group", "layer_id": folder})
    assert doc.layer(folder).kind == "paint"
    assert len(doc.layers) == 2
    assert png_bytes(doc.composite(False)) == before
    doc.undo()
    assert doc.layer(folder).kind == "group"
    assert png_bytes(doc.composite(False)) == before


@pytest.mark.parametrize("mode", BLEND_MODES)
def test_blend_mode_save_and_expected_multiply(mode, tmp_path):
    doc = Document(64, 64)
    shape(doc, color="#808080")
    add(doc)
    shape(doc, color="#808080")
    doc.execute({"op": "update_layer", "changes": {"blend_mode": mode}})
    if mode == "multiply":
        assert 62 <= doc.composite().pixelColor(30, 30).red() <= 66
    if mode == "linear_burn":
        assert doc.composite().pixelColor(30, 30).red() <= 2
    doc.save(tmp_path / "mode.mcpaint")
    assert png_bytes(Document.load(tmp_path / "mode.mcpaint").composite()) == png_bytes(
        doc.composite()
    )


@pytest.mark.parametrize("kind", FILTERS)
def test_adjustment_layer_nondestructive_masked_and_editable(kind, tmp_path):
    doc = Document(64, 64)
    base = doc.active_id
    shape(doc, color="#804060")
    original = png_bytes(doc.layer().image)
    settings = {
        "kind": kind,
        "radius": 5,
        "brightness": 1.5,
        "contrast": 1.2,
        "hue": 90,
        "saturation": 0.1,
        "red": 30,
        "points": [[0, 0], [128, 200], [255, 255]],
        "stops": [[0, "#0000ff"], [1, "#ffff00"]],
    }
    correction = add(doc, kind="adjustment", adjustment=settings)
    assert png_bytes(doc.layer(base).image) == original
    filtered = png_bytes(doc.composite())
    assert filtered != png_bytes(doc.layer(base).image)
    doc.execute({"op": "select_region", "kind": "rect", "rect": [0, 0, 32, 64]})
    doc.execute({"op": "mask", "action": "from_selection"})
    assert doc.composite().pixelColor(40, 30).name() == "#804060"
    doc.execute({"op": "update_layer", "layer_id": correction, "changes": {"visible": False}})
    assert doc.composite().pixelColor(20, 30).name() == "#804060"
    doc.undo()
    doc.save(tmp_path / "correction.mcpaint")
    assert png_bytes(Document.load(tmp_path / "correction.mcpaint").composite()) == png_bytes(
        doc.composite()
    )


def test_selected_transform_mesh_import_and_duplicate_are_replayable(tmp_path):
    doc = Document(64, 64)
    shape(doc, rect=(10, 10, 10, 10))
    doc.execute({"op": "select_region", "kind": "rect", "rect": [8, 8, 15, 15]})
    doc.execute({"op": "transform", "dx": 20, "dy": 0})
    assert doc.layer().image.pixelColor(15, 15).alpha() == 0
    assert doc.layer().image.pixelColor(35, 15).red() == 255
    assert doc.selection.getbbox()[0] >= 28
    doc.execute({"op": "selection_edit", "action": "clear"})
    grid = [[x * 63 / 2, y * 63 / 2] for y in range(3) for x in range(3)]
    grid[4] = [38, 31.5]
    doc.execute({"op": "mesh_warp", "points": grid, "columns": 2, "rows": 2})
    source = Image.new("RGBA", (8, 8), "#00ff00")
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    doc.execute(
        {
            "op": "import_image",
            "data": base64.b64encode(buffer.getvalue()).decode(),
            "x": 50,
            "y": 50,
        }
    )
    assert doc.layer().image.pixelColor(53, 53).green() == 255
    doc.execute({"op": "duplicate_layer"})
    assert len(doc.layers) == 2
    assert doc.layers[0].image == doc.layers[1].image
    doc.execute({"op": "merge_down"})
    assert len(doc.layers) == 1
    doc.save(tmp_path / "geometry.mcpaint")
    assert Document.load(tmp_path / "geometry.mcpaint").composite() == doc.composite()


def test_lasso_enclosed_fill_gradient_and_selection_edits():
    doc = Document(64, 64)
    lines = doc.active_id
    doc.execute(
        {"op": "shape", "kind": "ellipse", "rect": [20, 20, 20, 20], "color": "#000000", "size": 2}
    )
    add(doc)
    doc.execute(
        {
            "op": "fill",
            "mode": "enclosed",
            "points": [[5, 5], [58, 5], [58, 58], [5, 58]],
            "reference": "layer",
            "reference_layer_id": lines,
            "color": "#dd3322",
        }
    )
    assert doc.layer().image.pixelColor(30, 30).red() > 200
    assert doc.layer().image.pixelColor(10, 10).alpha() == 0
    doc.execute(
        {"op": "select_region", "kind": "polygon", "points": [[0, 0], [32, 0], [32, 63], [0, 63]]}
    )
    doc.execute({"op": "selection_edit", "action": "grow", "amount": 2})
    doc.execute({"op": "selection_edit", "action": "shrink", "amount": 2})
    doc.execute({"op": "selection_edit", "action": "feather", "amount": 2})
    doc.execute(
        {
            "op": "gradient",
            "start": [0, 0],
            "end": [63, 0],
            "color": "#000000",
            "end_color": "#ffffff",
        }
    )
    assert doc.layer().image.pixelColor(10, 10).alpha() > 200
    assert doc.layer().image.pixelColor(50, 10).alpha() == 0


@pytest.mark.parametrize(
    "command",
    [
        {"op": "select_region", "kind": "rect", "rect": [0, 0, 100, 10]},
        {"op": "gradient", "start": [0, 0], "end": [0, 0], "end_color": "#ffffff"},
        {"op": "filter", "settings": {"kind": "blur", "radius": float("nan")}},
        {"op": "transform", "scale_x": 0},
        {"op": "fill", "point": [-1, 0]},
        {"op": "shape", "kind": "bezier", "points": [[0, 0], [1, 1]]},
        {"op": "mesh_warp", "points": [[0, 0]]},
    ],
)
def test_bad_new_commands_are_atomic(command):
    doc = Document(64, 64)
    original = png_bytes(doc.composite())
    with pytest.raises((ValueError, KeyError)):
        doc.execute(command)
    assert not doc.timeline
    assert png_bytes(doc.composite()) == original


def test_v1_project_loads_with_identical_pixels(tmp_path):
    import json

    payload = {
        "format": "MCPaint",
        "version": 1,
        "width": 64,
        "height": 64,
        "background": "#ffffff",
        "base_id": "legacy",
        "active_id": "legacy",
        "timeline": [
            {
                "action": "execute",
                "at_ms": 50,
                "command": {
                    "op": "stroke",
                    "layer_id": "legacy",
                    "brush": "pen",
                    "color": "#ff0000",
                    "size": 4,
                    "points": [{"x": 10, "y": 10}, {"x": 50, "y": 50}],
                },
            }
        ],
    }
    path = tmp_path / "old.mcpaint"
    path.write_text(json.dumps(payload))
    doc = Document.load(path)
    assert doc.composite().pixelColor(30, 30).red() == 255
    assert doc.layer().blend_mode == "normal"
