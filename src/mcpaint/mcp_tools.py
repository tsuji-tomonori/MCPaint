"""Illustration tools registered on the same MCP server; all edits return PNG feedback."""

from typing import Literal

from mcp.types import CallToolResult

from .mcp_server import EDIT, READ, StrokePoint, call, mcp


@mcp.tool(annotations=EDIT)
def set_selection(
    kind: Literal["rect", "ellipse", "polygon", "wand", "layer_alpha"],
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    x: float = 0,
    y: float = 0,
    combine: Literal["replace", "add", "subtract", "intersect"] = "replace",
    reference: Literal["active", "visible", "layer"] = "visible",
    reference_layer_id: str | None = None,
    tolerance: int = 24,
    gap_close: int = 0,
    expand: int = 0,
    expected_revision: int | None = None,
) -> CallToolResult:
    """Select a rectangle/ellipse [x,y,w,h], lasso polygon, color-connected region or layer alpha.

    All following strokes, fills and filters respect this selection. Wand coordinates use
    original canvas pixels. combine supports Shift-like add and subtraction. Return PNG.
    """
    return call(
        "select_region",
        kind=kind,
        rect=rect,
        points=points,
        point=[x, y],
        combine=combine,
        reference=reference,
        reference_layer_id=reference_layer_id,
        tolerance=tolerance,
        gap_close=gap_close,
        expand=expand,
        expected_revision=expected_revision,
    )


@mcp.tool(annotations=EDIT)
def modify_selection(
    action: Literal["clear", "all", "invert", "grow", "shrink", "feather"], amount: int = 2
) -> CallToolResult:
    """Deselect, select all, invert, grow/shrink or feather the current selection (0..32 px)."""
    return call("selection_edit", action=action, amount=amount)


@mcp.tool(annotations=EDIT)
def fill_area(
    color: str,
    x: float = 0,
    y: float = 0,
    layer_id: str | None = None,
    mode: Literal["contiguous", "global", "selection", "enclosed"] = "contiguous",
    reference: Literal["active", "visible", "layer"] = "visible",
    reference_layer_id: str | None = None,
    tolerance: int = 24,
    gap_close: int = 0,
    expand: int = 1,
    opacity: float = 1,
    points: list[list[float]] | None = None,
    erase: bool = False,
    expected_revision: int | None = None,
) -> CallToolResult:
    """Bucket fill using current/visible/specified reference layer. Fill beneath separate line art.

    tolerance=0..255; gap_close=0..8 closes small gaps; expand=0..16 covers edge halos.
    mode=selection fills current selection (whole layer if none); global replaces all matching
    colors; enclosed fills closed regions inside the lasso points. erase clears with transparency.
    Clipping, alpha lock, masks and undo are preserved. Return PNG and state.
    """
    return call(
        "fill",
        color=color,
        point=[x, y],
        layer_id=layer_id,
        mode=mode,
        reference=reference,
        reference_layer_id=reference_layer_id,
        tolerance=tolerance,
        gap_close=gap_close,
        expand=expand,
        opacity=opacity,
        points=points,
        erase=erase,
        expected_revision=expected_revision,
    )


@mcp.tool(annotations=EDIT)
def draw_shape(
    kind: Literal["line", "rect", "ellipse", "polygon", "bezier"],
    color: str,
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    size: float = 3,
    fill_color: str | None = None,
    opacity: float = 1,
    layer_id: str | None = None,
    erase: bool = False,
    expected_revision: int | None = None,
) -> CallToolResult:
    """Draw geometry. rect=[x,y,w,h], polygon uses points; cubic Bezier has four ordered points
    [start, control1, control2, end]. Optional fill_color gives a solid interior. Return PNG.
    """
    return call(
        "shape",
        kind=kind,
        color=color,
        rect=rect,
        points=points,
        size=size,
        fill_color=fill_color,
        opacity=opacity,
        layer_id=layer_id,
        erase=erase,
        expected_revision=expected_revision,
    )


@mcp.tool(annotations=EDIT)
def paint_gradient(
    start: list[float],
    end: list[float],
    color: str,
    end_color: str,
    kind: Literal["linear", "radial"] = "linear",
    opacity: float = 1,
    layer_id: str | None = None,
) -> CallToolResult:
    """Paint a linear/radial gradient through the current selection and alpha lock. Return PNG."""
    return call(
        "gradient",
        start=start,
        end=end,
        color=color,
        end_color=end_color,
        kind=kind,
        opacity=opacity,
        layer_id=layer_id,
    )


@mcp.tool(annotations=EDIT)
def transform_layer(
    layer_id: str | None = None,
    dx: float = 0,
    dy: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    angle: float = 0,
    shear_x: float = 0,
    shear_y: float = 0,
    pivot: list[float] | None = None,
    expected_revision: int | None = None,
) -> CallToolResult:
    """Move, scale, rotate or skew selected pixels; without selection, transform entire layer.

    Negative scale mirrors artwork. angle is degrees; default pivot is canvas center.
    Selection moves with the pixels. Full-layer transforms move its mask too. Return PNG.
    """
    return call(
        "transform",
        layer_id=layer_id,
        dx=dx,
        dy=dy,
        scale_x=scale_x,
        scale_y=scale_y,
        angle=angle,
        shear_x=shear_x,
        shear_y=shear_y,
        pivot=pivot,
        expected_revision=expected_revision,
    )


@mcp.tool(annotations=EDIT)
def warp_mesh(
    points: list[list[float]], columns: int = 2, rows: int = 2, layer_id: str | None = None
) -> CallToolResult:
    """Warp selected pixels or the layer with a 1..8 by 1..8 cell mesh. Give destination control
    points in row-major order, exactly (columns+1)*(rows+1), in original canvas pixels.
    Each cell must remain a convex non-crossing quad. Piecewise projective mapping. Return PNG.
    """
    return call("mesh_warp", points=points, columns=columns, rows=rows, layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def apply_filter(settings: dict, layer_id: str | None = None) -> CallToolResult:
    """Apply a reversible pixel filter inside selection. settings.kind is blur (radius),
    brightness_contrast (brightness/contrast factors), hue_saturation (hue degrees/saturation
    factor), color_balance (red/green/blue offsets), tone_curve (ascending [input,output] points
    from 0..255 including endpoints), or gradient_map (ascending [0..1,#RRGGBB] stops).
    Use add_adjustment_layer instead for nondestructive color correction. Return PNG.
    """
    return call("filter", settings=settings, layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def add_adjustment_layer(
    settings: dict, name: str = "色調補正", group_id: str | None = None
) -> CallToolResult:
    """Add a nondestructive filter layer affecting siblings below it. Same settings as
    apply_filter; mask, clipping and opacity restrict the effect. Editable with update_layer.
    """
    return call("add_layer", kind="adjustment", adjustment=settings, name=name, group_id=group_id)


@mcp.tool(annotations=EDIT)
def layer_mask(
    action: Literal["from_selection", "reveal_all", "hide_all", "invert", "remove", "apply"],
    layer_id: str | None = None,
) -> CallToolResult:
    """Create/update a nondestructive mask on a paint/group/adjustment layer. from_selection
    reveals selected pixels; draw_mask_stroke edits it. apply bakes a paint layer's mask.
    """
    return call("mask", action=action, layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def draw_mask_stroke(
    points: list[StrokePoint],
    value: int = 0,
    brush: Literal["pen", "airbrush"] = "pen",
    size: float = 30,
    opacity: float = 1,
    layer_id: str | None = None,
) -> CallToolResult:
    """Paint an existing mask: value 0 hides, 255 reveals, gray partly reveals. Pen/airbrush
    support pressure and soft opacity, and respect current selection. Return PNG.
    """
    return call(
        "mask_stroke",
        points=[p.model_dump(exclude_none=True) for p in points],
        value=value,
        brush=brush,
        size=size,
        opacity=opacity,
        layer_id=layer_id,
    )


@mcp.tool(annotations=EDIT)
def duplicate_layer(layer_id: str | None = None) -> CallToolResult:
    """Duplicate and select a paint/adjustment layer with its mask and settings. Return PNG."""
    return call("duplicate_layer", layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def merge_layer_down(layer_id: str | None = None) -> CallToolResult:
    """Merge into the next paint layer below in the same folder. Both must use normal blending
    without clipping; masks and opacity are baked. Reversible with undo. Return PNG.
    """
    return call("merge_down", layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def flatten_group(layer_id: str | None = None) -> CallToolResult:
    """Flatten a folder and its nested child layers into one paint layer. Bake internal blending,
    masks and color corrections while preserving the folder's outer blending, clipping and
    opacity. Reversible with undo; children must be unlocked. Return PNG.
    """
    return call("flatten_group", layer_id=layer_id)


@mcp.tool(annotations=EDIT)
def import_image(path: str, layer_id: str | None = None, x: int = 0, y: int = 0) -> CallToolResult:
    """Import a local PNG/JPEG/WebP into the selected paint layer. Max 4096px/16MB.
    Image bytes are embedded in the project journal so replay never needs the original file.
    """
    return call("import_image", path=path, layer_id=layer_id, x=x, y=y)


@mcp.tool(annotations=EDIT)
def import_image_layer(
    path: str,
    name: str | None = None,
    placement: Literal["back", "above"] = "back",
    fit: Literal["contain", "original"] = "contain",
    opacity: float = 0.5,
    locked: bool = True,
    select_imported: bool = False,
    expected_revision: int | None = None,
) -> CallToolResult:
    """Import PNG/JPEG/WebP as a NEW independent layer and return its imported_layer_id + PNG.

    Defaults suit tracing: root-level back layer, centered proportional fit, 50% opacity,
    locked; keep the drawing layer selected. Selection does not crop the imported image.
    Draw above it, then update_layer(imported_layer_id, visible=False) before final export.
    For an ordinary image layer use placement='above', opacity=1, locked=False,
    select_imported=True. fit='original' centers native pixels (outside canvas is cropped).
    Max 4096px/16MB; JPEG EXIF orientation and PNG transparency are preserved. Image bytes
    are embedded in the project, including undo/redo and timelapse. Return state + PNG.
    """
    return call(
        "import_image_layer",
        path=path,
        name=name,
        placement=placement,
        fit=fit,
        opacity=opacity,
        locked=locked,
        select_imported=select_imported,
        expected_revision=expected_revision,
    )


@mcp.tool(annotations=READ)
def sample_color(
    x: float,
    y: float,
    reference: Literal["active", "visible", "layer"] = "visible",
    reference_layer_id: str | None = None,
) -> CallToolResult:
    """Eyedropper: return sampled #RRGGBB/RGBA plus current PNG. Does not change brush color."""
    return call(
        "sample_color", point=[x, y], reference=reference, reference_layer_id=reference_layer_id
    )


@mcp.tool(annotations=EDIT)
def set_view(
    flip_horizontal: bool | None = None, zoom: float | None = None, rotation: float | None = None
) -> CallToolResult:
    """Flip the desktop view for proportion checks or change zoom 0.25..8. Artwork and MCP
    canvas coordinates stay unchanged; window screenshots show the transformed desktop view.
    """
    return call(
        "set_view", flip_horizontal=flip_horizontal, zoom=zoom, rotation=rotation, scope="window"
    )
