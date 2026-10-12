"""Run through the actual packaged interpreter on a Windows build runner."""

import json
import os
import tempfile
from pathlib import Path


def run():
    from PySide6.QtWidgets import QApplication

    from .app import PaintWindow
    from .engine import Document
    from .mcp_server import mcp
    from .timelapse import export_timelapse

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        os.environ["MCPAINT_HOME"] = str(folder / "home")
        window = PaintWindow(start_bridge=False, recover=False)
        window.doc = Document(128, 96)
        window.doc.execute(
            {
                "op": "stroke",
                "brush": "pen",
                "color": "#ff0000",
                "size": 8,
                "points": [{"x": 10, "y": 48}, {"x": 110, "y": 48}],
            }
        )
        assert window.doc.composite().pixelColor(60, 48).red() > 200
        project = folder / "roundtrip.mcpaint"
        window.doc.save(project)
        assert Document.load(project).composite() == window.doc.composite()
        window.show()
        app.processEvents()
        result = window.handle({"op": "screenshot", "scope": "window"})
        assert result["image"]
        export_timelapse(window.doc, folder / "test.gif", max_frames=8, max_size=128)
        export_timelapse(window.doc, folder / "test.mp4", max_frames=8, max_size=128)
        assert (folder / "test.mp4").stat().st_size > 100
        assert mcp.name == "MCPaint"
        # Frozen builds must import numpy and expose every extension module, too.
        window.handle({"op": "add_layer", "kind": "group", "name": "colors"})
        window.handle({"op": "add_layer", "group_id": window.doc.active_id})
        window.handle({"op": "select_region", "kind": "ellipse", "rect": [20, 20, 50, 50]})
        window.handle({"op": "fill", "mode": "selection", "color": "#3388dd"})
        window.handle(
            {"op": "update_layer", "changes": {"alpha_lock": True, "blend_mode": "multiply"}}
        )
        window.handle({"op": "mask", "action": "from_selection"})
        window.handle({"op": "selection_edit", "action": "clear"})
        window.handle({"op": "filter", "settings": {"kind": "hue_saturation", "hue": 20}})
        extended = folder / "extended.mcpaint"
        window.doc.save(extended)
        assert Document.load(extended).composite() == window.doc.composite()
        import asyncio

        assert len(asyncio.run(mcp.list_tools())) == 33
        window.close()
    print(
        json.dumps(
            {
                "self_test": "passed",
                "checks": [
                    "Qt window",
                    "stroke",
                    "project",
                    "screenshot",
                    "GIF",
                    "MP4",
                    "MCP imports",
                ],
            }
        )
    )
    return 0
