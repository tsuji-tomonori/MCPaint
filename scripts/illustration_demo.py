"""Draw an original layered example through the real MCP protocol and save stage images."""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcpaint.mcp_server import existing_session

root = Path(__file__).resolve().parents[1]
folder = root / "build" / "illustration-demo"
folder.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MCPAINT_HOME"] = str(folder / "home")
gui = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import sys; from PySide6.QtWidgets import QApplication; from PySide6.QtGui import QFontDatabase; from mcpaint.app import PaintWindow; app=QApplication([]); QFontDatabase.addApplicationFont(sys.argv[1]); window=PaintWindow(); window.show(); sys.exit(app.exec())",
        str(root / "build" / "NotoSansCJKjp-Regular.otf"),
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def curve(a, b, c, d):
    return [
        [
            (1 - t) ** 3 * a[0]
            + 3 * (1 - t) ** 2 * t * b[0]
            + 3 * (1 - t) * t * t * c[0]
            + t**3 * d[0],
            (1 - t) ** 3 * a[1]
            + 3 * (1 - t) ** 2 * t * b[1]
            + 3 * (1 - t) * t * t * c[1]
            + t**3 * d[1],
        ]
        for t in [i / 40 for i in range(41)]
    ]


async def draw():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcpaint", "--mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def invoke(tool, **args):
                result = await session.call_tool(tool, args)
                if result.isError:
                    raise RuntimeError(f"{tool}: {result.content[0].text}")
                return json.loads(result.content[0].text), base64.b64decode(result.content[1].data)

            async def line(points, color="#3d3d65", size=5, brush="pen", opacity=1):
                return await invoke(
                    "draw_stroke",
                    points=[
                        {"x": x, "y": y, "t_ms": i * 20, "pressure": 0.9}
                        for i, (x, y) in enumerate(points)
                    ],
                    color=color,
                    size=size,
                    brush=brush,
                    opacity=opacity,
                )

            async def path(a, b, c, d, **kwargs):
                return await line(curve(a, b, c, d), **kwargs)

            async def checkpoint(name):
                _, png = await invoke("screenshot", selection_overlay=False)
                (folder / f"{name}.png").write_bytes(png)

            state, _ = await invoke("new_canvas", width=960, height=720, background="#f7f0ee")
            await invoke(
                "paint_gradient", start=[0, 0], end=[0, 719], color="#c9c8eb", end_color="#f6dcd7"
            )
            for x, y, r in [(160, 130, 90), (745, 125, 65), (830, 300, 45), (80, 430, 50)]:
                await invoke(
                    "draw_shape",
                    kind="ellipse",
                    rect=[x - r, y - r, r * 2, r * 2],
                    color="#e9e3f4",
                    fill_color="#e9e3f4",
                    size=1,
                    opacity=0.4,
                )
            state, _ = await invoke("add_layer", name="線画")
            lines = state["state"]["active_layer"]
            # Closed, slightly irregular hand-drawn silhouette.
            outline = []
            for a, b, c, d in [
                ((350, 465), (280, 457), (285, 325), (320, 304)),
                ((320, 304), (303, 276), (297, 225), (305, 218)),
                ((305, 218), (332, 222), (370, 248), (385, 264)),
                ((385, 264), (435, 240), (498, 247), (537, 266)),
                ((537, 266), (555, 242), (592, 220), (605, 216)),
                ((605, 216), (612, 245), (610, 282), (594, 307)),
                ((594, 307), (631, 354), (620, 445), (565, 466)),
                ((565, 466), (667, 537), (655, 615), (555, 626)),
                ((555, 626), (510, 650), (382, 650), (344, 626)),
                ((344, 626), (260, 621), (258, 529), (350, 465)),
            ]:
                pts = curve(a, b, c, d)
                outline += pts[:-1]
            outline.append(outline[0])
            await line(outline, size=5)
            await path((555, 617), (755, 616), (777, 480), (705, 504), size=6)
            await checkpoint("01-line-art")
            state, _ = await invoke("add_layer", name="下塗りベース")
            base = state["state"]["active_layer"]
            await invoke("move_layer", layer_id=base, index=1)
            await invoke(
                "fill_area",
                x=445,
                y=400,
                color="#f6dbc5",
                reference="layer",
                reference_layer_id=lines,
                expand=2,
            )
            state, _ = await invoke("add_layer", name="塗りフォルダー", kind="group")
            colors = state["state"]["active_layer"]
            await invoke("move_layer", layer_id=colors, index=2)
            await invoke("update_layer", layer_id=colors, clipping=True)
            await invoke("add_layer", name="塗りの地色", group_id=colors)
            await invoke("fill_area", mode="selection", color="#f6dbc5")
            state, _ = await invoke("add_layer", name="スカーフ・耳", group_id=colors)
            await invoke(
                "draw_shape",
                kind="polygon",
                points=[
                    [338, 461],
                    [392, 473],
                    [503, 472],
                    [570, 459],
                    [565, 501],
                    [472, 523],
                    [449, 587],
                    [416, 507],
                    [355, 499],
                ],
                color="#5ea8ba",
                fill_color="#5ea8ba",
                size=2,
            )
            for pts in ([[320, 245], [366, 269], [327, 297]], [[588, 243], [551, 271], [580, 297]]):
                await invoke(
                    "draw_shape",
                    kind="polygon",
                    points=pts,
                    color="#dda7aa",
                    fill_color="#dda7aa",
                    size=1,
                )
            await checkpoint("02-flat-colors")
            state, _ = await invoke("add_layer", name="影・乗算", group_id=colors)
            shade = state["state"]["active_layer"]
            await invoke("update_layer", layer_id=shade, blend_mode="multiply", opacity=0.4)
            await invoke(
                "paint_gradient",
                start=[420, 200],
                end=[575, 630],
                color="#ffffff",
                end_color="#987baf",
            )
            await invoke("layer_mask", action="reveal_all")
            await invoke(
                "draw_mask_stroke",
                points=[{"x": 380, "y": 370}, {"x": 470, "y": 430}],
                brush="airbrush",
                size=170,
                opacity=0.7,
                value=0,
            )
            state, _ = await invoke("add_layer", name="柔らかい光", group_id=colors)
            await invoke(
                "update_layer",
                layer_id=state["state"]["active_layer"],
                blend_mode="screen",
                opacity=0.55,
            )
            await line(
                [[368, 344], [395, 339], [435, 343]], color="#f8d0b0", size=110, brush="airbrush"
            )
            await checkpoint("03-light-and-shade")
            await invoke("select_layer", layer_id=lines)
            await path((369, 363), (383, 342), (402, 345), (413, 362), size=4)
            await path((502, 363), (513, 343), (535, 344), (546, 363), size=4)
            await line([[444, 381], [467, 381], [455, 394], [444, 381]], color="#b36f88", size=5)
            await path((455, 394), (456, 412), (431, 417), (424, 405), size=3)
            await path((455, 394), (455, 413), (481, 417), (488, 405), size=3)
            for yy, delta in [(389, -9), (404, 1), (420, 10)]:
                await line([[385, yy], [313, yy + delta]], size=2.5)
                await line([[529, yy], [603, yy + delta]], size=2.5)
            await path((354, 621), (355, 575), (403, 578), (408, 634), size=4)
            await path((496, 634), (502, 577), (550, 577), (550, 622), size=4)
            # Foreground, original small botanical decorations and stars.
            state, _ = await invoke("add_layer", name="草花・きらめき")
            for x, y in [(140, 590), (175, 635), (790, 615), (835, 572)]:
                await line([[x, y + 25], [x, y - 60]], color="#6c8f87", size=3)
                for offset in [-30, -5, 15]:
                    await path(
                        (x, y + offset),
                        (x - 35, y + offset - 30),
                        (x - 40, y + offset),
                        (x, y + offset + 10),
                        color="#80a89a",
                        size=10,
                        brush="marker",
                    )
                    await path(
                        (x, y + offset - 12),
                        (x + 30, y + offset - 48),
                        (x + 35, y + offset - 10),
                        (x, y + offset),
                        color="#80a89a",
                        size=9,
                        brush="marker",
                    )
            for x, y in [(238, 260), (710, 330), (620, 155), (230, 470), (760, 200)]:
                await invoke(
                    "draw_shape",
                    kind="polygon",
                    points=[
                        [x, y - 12],
                        [x + 3, y - 3],
                        [x + 12, y],
                        [x + 3, y + 3],
                        [x, y + 12],
                        [x - 3, y + 3],
                        [x - 12, y],
                        [x - 3, y - 3],
                    ],
                    color="#fff4d8",
                    fill_color="#fff4d8",
                    size=1,
                )
            await invoke(
                "add_adjustment_layer",
                name="仕上げ・カラーバランス",
                settings={"kind": "color_balance", "red": 4, "green": 0, "blue": 3},
            )
            await invoke(
                "update_layer",
                layer_id=(await invoke("screenshot"))[0]["state"]["active_layer"],
                opacity=0.3,
            )
            await checkpoint("04-final")
            await invoke("save_project", path=str(folder / "illustration.mcpaint"))
            await invoke("export_png", path=str(folder / "illustration.png"))
            await invoke(
                "export_timelapse",
                path=str(folder / "illustration.mp4"),
                max_frames=240,
                max_size=800,
            )
            _, png = await invoke("screenshot", scope="window", max_size=1600)
            (root / "docs" / "screenshot.png").write_bytes(png)
            print("Real MCP illustration, stage images, project and MP4 written")


try:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not existing_session():
        time.sleep(0.1)
    if not existing_session():
        raise RuntimeError("GUI startup failed")
    asyncio.run(draw())
finally:
    gui.terminate()
    gui.wait(timeout=10)
