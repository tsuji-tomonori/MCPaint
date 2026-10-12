import json

import pytest
from PIL import Image

from mcpaint.engine import BRUSHES, Document, png_bytes
from mcpaint.timelapse import export_timelapse, replay_frames


def stroke(doc, brush="pen", color="#ff0000", size=10, **kwargs):
    return doc.execute(
        {
            "op": "stroke",
            "brush": brush,
            "color": color,
            "size": size,
            "points": [
                {"x": 10, "y": 32, "pressure": 0.5, "t_ms": 0},
                {"x": 54, "y": 32, "pressure": 1, "t_ms": 500},
            ],
            **kwargs,
        }
    )


@pytest.mark.parametrize("brush", BRUSHES)
def test_brushes_roundtrip_and_timelapse(brush, tmp_path):
    doc = Document(64, 64)
    stroke(doc, size=20)
    before = png_bytes(doc.composite())
    if brush in ("blur", "smudge"):
        stroke(doc, brush=brush, size=30, points=[{"x": 5, "y": 32}, {"x": 63, "y": 32}])
    else:
        stroke(doc, brush=brush, color="#0000ff", size=8)
    if brush == "eraser":
        assert doc.layer().image.pixelColor(32, 32).alpha() == 0
    else:
        assert png_bytes(doc.composite()) != before
    path = tmp_path / "painting.mcpaint"
    doc.save(path)
    loaded = Document.load(path)
    assert png_bytes(loaded.composite()) == png_bytes(doc.composite())
    assert loaded.timeline == doc.timeline
    frames = list(replay_frames(loaded, 9, 64))
    assert frames[-1].tobytes() == list(replay_frames(doc, 9, 64))[-1].tobytes()


def test_layers_visibility_order_lock_and_undo(tmp_path):
    doc = Document(64, 64)
    bottom = doc.active_id
    stroke(doc)
    doc.execute({"op": "add_layer", "name": "blue"})
    top = doc.active_id
    stroke(doc, color="#0000ff")
    assert doc.composite().pixelColor(32, 32).blue() == 255
    doc.execute({"op": "update_layer", "changes": {"visible": False}})
    assert doc.composite().pixelColor(32, 32).red() == 255
    doc.undo()
    doc.execute({"op": "move_layer", "index": 0})
    assert doc.composite().pixelColor(32, 32).red() == 255
    doc.execute({"op": "update_layer", "layer_id": top, "changes": {"locked": True}})
    size = len(doc.timeline)
    with pytest.raises(ValueError, match="ロック"):
        stroke(doc, layer_id=top)
    assert len(doc.timeline) == size
    doc.undo()
    doc.execute({"op": "delete_layer", "layer_id": bottom})
    doc.undo()
    doc.redo()
    doc.undo()
    path = tmp_path / "undo.mcpaint"
    doc.save(path)
    loaded = Document.load(path)
    assert png_bytes(loaded.composite()) == png_bytes(doc.composite())
    assert loaded.state()["can_redo"]
    assert loaded.redo()
    assert len(loaded.layers) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"size": float("nan")},
        {"size": 0},
        {"color": "red"},
        {"brush": "unknown"},
        {"points": []},
        {"points": [{"x": -1, "y": 0}]},
        {"points": [{"x": 0, "y": 0, "t_ms": 10}, {"x": 1, "y": 1, "t_ms": 0}]},
    ],
)
def test_invalid_stroke_is_atomic(change):
    doc = Document(64, 64)
    before = png_bytes(doc.composite())
    with pytest.raises((ValueError, KeyError)):
        stroke(doc, **change)
    assert before == png_bytes(doc.composite())
    assert doc.revision == 0
    assert not doc.timeline


def test_timelapse_shows_interior_of_stroke_and_final_state(tmp_path):
    doc = Document(64, 64)
    stroke(doc)
    frames = list(replay_frames(doc, 5, 64))
    assert frames[1].getpixel((20, 32))[0] > 200
    assert frames[1].getpixel((45, 32)) == (255, 255, 255)
    assert frames[-1].getpixel((45, 32))[1] < 100
    doc.undo()
    final = list(replay_frames(doc, 5, 64))[-1]
    assert final.getpixel((45, 32)) == (255, 255, 255)
    doc.redo()
    gif = tmp_path / "replay.gif"
    mp4 = tmp_path / "replay.mp4"
    export_timelapse(doc, gif, max_frames=12, max_size=64)
    export_timelapse(doc, mp4, max_frames=12, max_size=64)
    with Image.open(gif) as image:
        assert image.n_frames > 2
    assert mp4.stat().st_size > 500
    assert b"ftyp" in mp4.read_bytes()[:20]


def test_new_branch_after_undo_retains_actual_recording(tmp_path):
    doc = Document(64, 64)
    stroke(doc)
    stroke(doc, color="#0000ff")
    doc.undo()
    stroke(doc, color="#00ff00")
    assert not doc.redo()
    doc.save(tmp_path / "branch.mcpaint")
    payload = json.loads((tmp_path / "branch.mcpaint").read_text())
    assert len(payload["timeline"]) == 4
    assert list(replay_frames(doc, 10, 64))[-1].getpixel((32, 32))[1] == 255
