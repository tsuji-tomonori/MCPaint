"""One shared PyInstaller archive with a GUI and a stdio console entry point."""

import sys
from pathlib import Path

from mcpaint.__main__ import main

if (
    Path(sys.executable).stem.endswith("-MCP")
    and "--mcp" not in sys.argv
    and "--self-test" not in sys.argv
):
    sys.argv.append("--mcp")

raise SystemExit(main())
