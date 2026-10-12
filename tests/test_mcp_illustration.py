"""A real visual feedback loop through all 33 public MCP tools, not direct engine calls."""

import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

from mcpaint.engine import Document
from mcpaint.mcp_server import existing_session


def test_entire_illustration_workflow_over_stdio(tmp_path):
    gui = subprocess.Popen(
        [sys.executable, "-m", "mcpaint"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not existing_session():
            assert gui.poll() is None
            time.sleep(0.1)
        assert existing_session()

        async def exercise():
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "mcpaint", "--mcp"], env=dict(os.environ)
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    advertised = {x.name for x in (await session.list_tools()).tools}
                    used = set()

                    async def call(tool_name, **args):
                        result = await session.call_tool(tool_name, args)
                        assert not result.isError, (
                            tool_name,
                            [getattr(c, "text", None) for c in result.content],
                        )
                        assert result.content[1].type == "image", tool_name
                        image = Image.open(
                            io.BytesIO(base64.b64decode(result.content[1].data))
                        ).convert("RGBA")
                        used.add(tool_name)
                        return json.loads(result.content[0].text), image

                    state, _ = await call("new_canvas", width=160, height=120)
                    line = state["state"]["active_layer"]
                    await call("set_brush", brush="pen", color="#222222", size=2, smoothing=0.4)
                    await call(
                        "draw_shape", kind="ellipse", rect=[30, 20, 70, 70], color="#222222", size=2
                    )
                    state, _ = await call("add_layer", name="下塗り")
                    flats = state["state"]["active_layer"]
                    await call("move_layer", layer_id=flats, index=0)
                    _, image = await call(
                        "fill_area",
                        x=60,
                        y=50,
                        color="#e8b898",
                        reference="layer",
                        reference_layer_id=line,
                        expand=1,
                    )
                    assert image.getpixel((60, 50))[:3] == (232, 184, 152)
                    assert image.getpixel((0, 0))[:3] == (255, 255, 255)
                    await call(
                        "set_selection",
                        kind="wand",
                        x=0,
                        y=0,
                        reference="layer",
                        reference_layer_id=line,
                    )
                    await call("modify_selection", action="invert")
                    state, _ = await call("add_layer", kind="group", name="塗りフォルダー")
                    folder = state["state"]["active_layer"]
                    await call("move_layer", layer_id=folder, index=1)
                    await call("update_layer", layer_id=folder, clipping=True)
                    await call("add_layer", name="塗り", group_id=folder)
                    await call("fill_area", mode="selection", color="#e8b898")
                    state, _ = await call("add_layer", name="影", group_id=folder)
                    shade = state["state"]["active_layer"]
                    await call("update_layer", layer_id=shade, blend_mode="multiply", opacity=0.5)
                    await call(
                        "draw_stroke",
                        points=[
                            {"x": 45, "y": 65, "pressure": 0.5},
                            {"x": 95, "y": 65, "pressure": 1},
                        ],
                        brush="airbrush",
                        size=30,
                        color="#a07a97",
                    )
                    await call(
                        "paint_gradient",
                        start=[30, 20],
                        end=[100, 90],
                        color="#7e6490",
                        end_color="#efd8bf",
                        opacity=0.2,
                    )
                    await call("layer_mask", action="from_selection", layer_id=shade)
                    await call("modify_selection", action="clear")
                    await call(
                        "draw_mask_stroke",
                        points=[{"x": 65, "y": 45}],
                        size=20,
                        value=0,
                        brush="airbrush",
                        layer_id=shade,
                    )
                    _, mask = await call("screenshot", scope="mask", layer_id=shade)
                    assert mask.getpixel((65, 45))[3] < 255
                    await call(
                        "apply_filter", settings={"kind": "blur", "radius": 2}, layer_id=shade
                    )
                    await call(
                        "add_adjustment_layer",
                        settings={"kind": "tone_curve", "points": [[0, 0], [128, 140], [255, 255]]},
                        name="仕上げ",
                    )
                    await call("set_view", flip_horizontal=True, zoom=1.2)
                    await call("sample_color", x=60, y=50)
                    await call("set_view", flip_horizontal=False, zoom=1)
                    await call("flatten_group", layer_id=folder)
                    await call("select_layer", layer_id=flats)
                    await call("set_selection", kind="ellipse", rect=[30, 20, 70, 70])
                    await call("transform_layer", dx=1, dy=0)
                    await call("modify_selection", action="clear")
                    points = [[x * 159 / 2, y * 119 / 2] for y in range(3) for x in range(3)]
                    points[4] = [82, 59.5]
                    await call("warp_mesh", points=points, columns=2, rows=2)
                    texture = tmp_path / "texture.png"
                    Image.new("RGBA", (8, 8), (200, 150, 80, 90)).save(texture)
                    await call("import_image", path=str(texture), x=45, y=40)
                    texture.unlink()
                    await call("duplicate_layer", layer_id=flats)
                    await call("merge_layer_down")
                    state, _ = await call("add_layer", name="test-clear")
                    temp = state["state"]["active_layer"]
                    await call(
                        "draw_stroke", points=[{"x": 100, "y": 100}], color="#ff0000", size=6
                    )
                    await call("clear_layer")
                    await call("undo")
                    await call("redo")
                    await call("delete_layer", layer_id=temp)
                    project = tmp_path / "illustration.mcpaint"
                    await call("save_project", path=str(project))
                    final = Document.load(project).composite()
                    await call("new_canvas", width=100, height=100)
                    await call("open_project", path=str(project))
                    await call("export_png", path=str(tmp_path / "result.png"))
                    await call(
                        "export_timelapse",
                        path=str(tmp_path / "result.mp4"),
                        max_frames=16,
                        max_size=160,
                    )
                    assert (tmp_path / "result.mp4").stat().st_size > 1000
                    assert Document.load(project).composite() == final
                    assert used == advertised, advertised - used

        asyncio.run(exercise())
    finally:
        gui.terminate()
        gui.wait(timeout=10)
