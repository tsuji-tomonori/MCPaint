"""Standard stdio MCP server; every operation returns visual feedback."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from .bridge import data_dir

Brush = Literal[
    "pen", "pencil", "marker", "airbrush", "eraser", "watercolor", "spray", "blur", "smudge"
]

INSTRUCTIONS = """MCPaint is a local Windows paint studio. Work visually: call screenshot first,
inspect it, choose a layer and brush, draw a small group of strokes, then inspect returned images.
Coordinates always use ORIGINAL canvas pixels (top-left origin, x right, y down), not scaled
image pixels. image_info gives crop origin and scaling. Use expected_revision to reject a stale
drawing plan. Each mutation returns state + PNG. Use points to express the actual path, pressure
and per-point t_ms to preserve stroke motion. Never assume an image before examining it.
All strokes, layer edits, undo and redo are automatically journaled. Save a .mcpaint project to
preserve editable layers and history; export PNG for artwork and MP4/GIF for timelapse.
Illustration workflow: keep sketch, line art, flats, shadows and highlights on separate layers.
Fill flats using reference='layer' and the line-art reference_layer_id. Select/invert the outside
to create a silhouette base, then clip a color folder and shading layers to it. Use multiply
for shadows, screen/add for light, alpha_lock for recoloring, and layer masks for soft erasure.
Use nondestructive adjustment layers for tone curves, color balance and gradient maps.
Inspect selection/mask/layer PNGs before applying transforms or detailed edits. All tools use
the same journal and desktop rendering; no image generation service is required.
"""

mcp = FastMCP("MCPaint", instructions=INSTRUCTIONS)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


class StrokePoint(BaseModel):
    x: float = Field(description="Original canvas x coordinate in pixels")
    y: float = Field(description="Original canvas y coordinate in pixels")
    pressure: float = Field(default=1, ge=0, le=1)
    t_ms: float | None = Field(
        default=None, ge=0, le=120000, description="Milliseconds since stroke start; ascending"
    )


def request(payload, timeout=125):
    session = json.loads((data_dir() / "session.json").read_text(encoding="utf-8"))
    port = int(session["port"])
    if not 1 <= port <= 65535:
        raise ValueError("Invalid local session port")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {session['token']}", "Content-Type": "application/json"},
    )
    # A proxy must never see local authentication tokens or canvas data.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def existing_session():
    try:
        return request({"op": "ping"}, timeout=0.5).get("ok", False)
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return False


def ensure_app():
    if existing_session():
        from . import __version__

        version = request({"op": "ping"}, timeout=1).get("version", "0.1.0")
        if version != __version__:
            raise RuntimeError(
                f"起動中のMCPaintは{version}です。終了して{__version__}のMCPaint.exeを起動してください"
            )
        return
    if getattr(sys, "frozen", False):
        command = [str(Path(sys.executable).with_name("MCPaint.exe"))]
    else:
        command = [sys.executable, "-m", "mcpaint"]
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if existing_session():
            return
        time.sleep(0.1)
    raise RuntimeError("MCPaintの画面を起動できません。MCPaint.exeを手動で開いてください")


def call(op, **args):
    try:
        ensure_app()
        payload = {"op": op, **{k: v for k, v in args.items() if v is not None}}
        result = request(payload)
        if not result.get("ok"):
            raise ValueError(result.get("error", "操作に失敗しました"))
        encoded = result.pop("image")
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False)),
                ImageContent(type="image", mimeType="image/png", data=encoded),
            ]
        )
    except Exception as e:
        return CallToolResult(isError=True, content=[TextContent(type="text", text=str(e))])


@mcp.tool(annotations=READ)
def screenshot(
    scope: Literal["canvas", "window", "layer", "selection", "mask"] = "canvas",
    grid: bool = False,
    crop: list[int] | None = None,
    max_size: int = 1280,
    layer_id: str | None = None,
    selection_overlay: bool = True,
) -> CallToolResult:
    """Return current PNG, layers, brush, revision and pixel coordinate mapping. crop=[x,y,w,h]."""
    return call(
        "screenshot",
        scope=scope,
        grid=grid,
        crop=crop,
        max_size=max_size,
        layer_id=layer_id,
        selection_overlay=selection_overlay,
    )


@mcp.tool(annotations=EDIT)
def new_canvas(width: int = 1280, height: int = 800, background: str = "#ffffff") -> CallToolResult:
    """Create a canvas (1..4096 each dimension). Previous work is checkpointed automatically."""
    return call("new_canvas", width=width, height=height, background=background)


@mcp.tool(annotations=EDIT)
def set_brush(
    brush: Brush | None = None,
    color: str | None = None,
    size: float | None = None,
    opacity: float | None = None,
    smoothing: float | None = None,
) -> CallToolResult:
    """Choose brush, #RRGGBB color, width 0.5..300 px and opacity 0..1. Return screen."""
    return call(
        "set_brush", brush=brush, color=color, size=size, opacity=opacity, smoothing=smoothing
    )


@mcp.tool(annotations=EDIT)
def draw_stroke(
    points: list[StrokePoint],
    layer_id: str | None = None,
    brush: Brush | None = None,
    color: str | None = None,
    size: float | None = None,
    opacity: float | None = None,
    expected_revision: int | None = None,
    smoothing: float | None = None,
    seed: int = 0,
) -> CallToolResult:
    """Draw a path of 1..20000 ordered points in original canvas pixels. Optional pressure/t_ms.

    Inspect the returned PNG before planning the next stroke. Defaults use current brush/layer.
    """
    serialized = [point.model_dump(exclude_none=True) for point in points]
    return call(
        "stroke",
        points=serialized,
        layer_id=layer_id,
        brush=brush,
        color=color,
        size=size,
        opacity=opacity,
        expected_revision=expected_revision,
        smoothing=smoothing,
        seed=seed,
    )


@mcp.tool(annotations=EDIT)
def add_layer(
    name: str = "新しいレイヤー",
    kind: Literal["paint", "group"] = "paint",
    group_id: str | None = None,
) -> CallToolResult:
    """Add and select a paint layer or folder (maximum 64); group_id puts it inside a folder.
    Paint flats inside a clipped color folder before adding multiply shadows in that folder.
    """
    return call("add_layer", name=name, kind=kind, group_id=group_id)


@mcp.tool(annotations=EDIT)
def select_layer(layer_id: str) -> CallToolResult:
    """Select a layer by ID returned by screenshot."""
    return call("select_layer", layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def update_layer(
    layer_id: str,
    name: str | None = None,
    visible: bool | None = None,
    locked: bool | None = None,
    opacity: float | None = None,
    blend_mode: Literal[
        "normal",
        "multiply",
        "screen",
        "overlay",
        "soft_light",
        "hard_light",
        "add",
        "darken",
        "lighten",
        "color_dodge",
        "color_burn",
        "linear_burn",
        "difference",
    ]
    | None = None,
    clipping: bool | None = None,
    alpha_lock: bool | None = None,
    group_id: str | None = None,
    ungroup: bool = False,
    layer_color: str | None = None,
    clear_layer_color: bool = False,
    adjustment: dict | None = None,
) -> CallToolResult:
    """Edit layer/folder name, visibility, lock, opacity, blend mode, clipping, alpha lock,
    parent folder, display line color, or correction settings. Clipping uses the nearest
    non-clipping sibling below. ungroup/clear_layer_color remove those settings. Return PNG.
    """
    changes = {
        k: v
        for k, v in {
            "name": name,
            "visible": visible,
            "locked": locked,
            "opacity": opacity,
            "blend_mode": blend_mode,
            "clipping": clipping,
            "alpha_lock": alpha_lock,
            "group_id": group_id,
            "layer_color": layer_color,
            "adjustment": adjustment,
        }.items()
        if v is not None
    }
    if ungroup:
        changes["group_id"] = None
    if clear_layer_color:
        changes["layer_color"] = None
    return call("update_layer", layer_id=layer_id, changes=changes)


@mcp.tool(annotations=EDIT)
def move_layer(layer_id: str, index: int) -> CallToolResult:
    """Move a layer; index 0 is bottom, larger indices are on top."""
    return call("move_layer", layer_id=layer_id, index=index)


@mcp.tool(annotations=EDIT)
def delete_layer(layer_id: str) -> CallToolResult:
    """Delete a layer. Reversible with undo; the final layer cannot be deleted."""
    return call("delete_layer", layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def clear_layer(layer_id: str | None = None) -> CallToolResult:
    """Clear the selected/specified unlocked layer. Reversible with undo."""
    return call("clear_layer", layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def undo() -> CallToolResult:
    """Undo the last drawing or layer edit; record the action in the timelapse."""
    return call("undo")


@mcp.tool(annotations=EDIT)
def redo() -> CallToolResult:
    """Redo an undone edit; record the action in the timelapse."""
    return call("redo")


@mcp.tool(annotations=EDIT)
def save_project(path: str) -> CallToolResult:
    """Save editable layers and complete creation history to a local .mcpaint path."""
    return call("save_project", path=path)


@mcp.tool(annotations=EDIT)
def open_project(path: str) -> CallToolResult:
    """Load a local .mcpaint project. Current work is checkpointed first."""
    return call("open_project", path=path)


@mcp.tool(annotations=EDIT)
def export_png(path: str, background: bool = True) -> CallToolResult:
    """Save artwork to local PNG. Set background=false for transparent background."""
    return call("export_png", path=path, background=background)


@mcp.tool(annotations=EDIT)
def export_timelapse(
    path: str, fps: int = 20, max_frames: int = 240, max_size: int = 800
) -> CallToolResult:
    """Export recorded stroke motion, edits and undo/redo to local MP4 or GIF.

    Idle time is compressed. fps=1..60, max_frames=2..360, max_size=64..960.
    """
    return call("export_timelapse", path=path, fps=fps, max_frames=max_frames, max_size=max_size)


@mcp.prompt()
def visual_painting():
    """A visual-first painting workflow for Codex and other MCP clients."""
    return "最初にscreenshot(grid=true)で画像・座標・レイヤーを確認してください。描く対象を小さな線のまとまりに分け、set_brushとdraw_strokeで描いてください。各操作が返す画像を見て、形・位置・色を確認してから次の線を計画してください。最後にsave_project、export_png、export_timelapseで保存してください。"


def run_mcp():
    mcp.run(transport="stdio")


from . import mcp_tools  # noqa: E402,F401
