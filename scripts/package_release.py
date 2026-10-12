"""Add usage/license files, zip portable output and emit a SHA-256 manifest."""

import hashlib
import shutil
from pathlib import Path

from mcpaint import __version__

root = Path(__file__).resolve().parents[1]
portable = root / "dist" / "MCPaint"
for name in ("README.md", "LICENSE", "THIRD_PARTY.md"):
    shutil.copy2(root / name, portable / name)
shutil.copytree(root / "docs", portable / "docs", dirs_exist_ok=True)
shutil.copytree(root / "examples", portable / "examples", dirs_exist_ok=True)
shutil.copy2(root / "scripts" / "register-codex.ps1", portable / "register-codex.ps1")
asset = Path(
    shutil.make_archive(
        str(root / "dist" / f"MCPaint-{__version__}-windows-x64"), "zip", root / "dist", "MCPaint"
    )
)
digest = hashlib.sha256(asset.read_bytes()).hexdigest()
(root / "dist" / "SHA256SUMS.txt").write_text(f"{digest}  {asset.name}\n", encoding="utf-8")
print(f"Packaged {asset.name}: {asset.stat().st_size:,} bytes")
