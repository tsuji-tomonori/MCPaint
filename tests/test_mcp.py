import asyncio
import base64
import json
import os
import subprocess
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcpaint.bridge import data_dir
from mcpaint.mcp_server import existing_session


def test_real_stdio_mcp_to_desktop_and_authentication(tmp_path):
    # This is the real SDK client, stdio server subprocess and GUI subprocess.
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
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "MCPaint"
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    assert {
                        "screenshot",
                        "draw_stroke",
                        "export_timelapse",
                        "update_layer",
                    } <= names
                    assert len(names) == 33
                    result = await session.call_tool("new_canvas", {"width": 160, "height": 100})
                    assert not result.isError
                    state = json.loads(result.content[0].text)["state"]
                    result = await session.call_tool(
                        "draw_stroke",
                        {
                            "points": [{"x": 10, "y": 40}, {"x": 140, "y": 40}],
                            "color": "#dd3322",
                            "size": 8,
                            "expected_revision": state["revision"],
                        },
                    )
                    assert not result.isError
                    assert result.content[1].type == "image"
                    assert base64.b64decode(result.content[1].data).startswith(b"\x89PNG")
                    result = await session.call_tool(
                        "draw_stroke", {"points": [{"x": -10, "y": 0}]}
                    )
                    assert result.isError
                    path = str(tmp_path / "protocol.mcpaint")
                    assert not (await session.call_tool("save_project", {"path": path})).isError
                    assert not (
                        await session.call_tool(
                            "export_timelapse",
                            {
                                "path": str(tmp_path / "protocol.gif"),
                                "max_frames": 8,
                                "max_size": 160,
                            },
                        )
                    ).isError

        asyncio.run(exercise())
        import urllib.error
        import urllib.request

        import pytest

        port = json.loads((data_dir() / "session.json").read_text())["port"]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/command", data=b'{"op":"screenshot"}'
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req)
        assert error.value.code == 403
    finally:
        gui.terminate()
        gui.wait(timeout=10)
