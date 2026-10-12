"""Exercise real stdio tools against the packaged GUI and MCP executables."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

from mcpaint.mcp_server import existing_session

root = Path(__file__).resolve().parents[1]
suffix = ".exe" if sys.platform == "win32" else ""
gui_exe = root / "dist" / "MCPaint" / f"MCPaint{suffix}"
server_exe = gui_exe.with_name(f"MCPaint-MCP{suffix}")


async def verify(folder):
    params = StdioServerParameters(command=str(server_exe), args=[], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 34
            for name, args in [
                ("new_canvas", {"width": 160, "height": 100}),
                ("import_image_layer", {"path": str(folder / "reference.png")}),
                ("import_image_layer", {"path": str(folder / "reference.jpg")}),
                (
                    "draw_shape",
                    {
                        "kind": "ellipse",
                        "rect": [20, 20, 60, 60],
                        "color": "#ff8866",
                        "fill_color": "#ff8866",
                    },
                ),
                ("set_selection", {"kind": "rect", "rect": [20, 20, 30, 60]}),
                ("fill_area", {"mode": "selection", "color": "#3355aa"}),
                ("layer_mask", {"action": "from_selection"}),
                ("modify_selection", {"action": "clear"}),
                (
                    "add_adjustment_layer",
                    {
                        "settings": {
                            "kind": "gradient_map",
                            "stops": [[0, "#443355"], [1, "#ffeedd"]],
                        }
                    },
                ),
                ("screenshot", {"scope": "window"}),
                ("save_project", {"path": str(folder / "packaged.mcpaint")}),
                (
                    "export_timelapse",
                    {"path": str(folder / "packaged.mp4"), "max_frames": 12, "max_size": 160},
                ),
            ]:
                result = await session.call_tool(name, args)
                assert not result.isError, (name, result.content)
                assert result.content[1].type == "image"
                if name == "import_image_layer":
                    state = json.loads(result.content[0].text)
                    hidden = await session.call_tool(
                        "update_layer",
                        {
                            "layer_id": state["imported_layer_id"],
                            "visible": False,
                        },
                    )
                    assert not hidden.isError and hidden.content[1].type == "image"
            assert (folder / "packaged.mp4").stat().st_size > 1000


with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    Image.new("RGBA", (32, 20), (50, 80, 200, 128)).save(folder / "reference.png")
    Image.new("RGB", (32, 20), "#4488cc").save(folder / "reference.jpg")
    os.environ["MCPAINT_HOME"] = str(folder / "home")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    gui = subprocess.Popen([str(gui_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not existing_session():
            assert gui.poll() is None, "Packaged GUI exited"
            time.sleep(0.1)
        assert existing_session()
        asyncio.run(verify(folder))
    finally:
        gui.terminate()
        gui.wait(timeout=10)
print("Packaged GUI + stdio MCP + extended painting + MP4: passed")
