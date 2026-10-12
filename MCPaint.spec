# Run with: python -m PyInstaller --noconfirm MCPaint.spec
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = collect_data_files('imageio_ffmpeg', includes=['binaries/*'])
datas += copy_metadata('mcp')
a = Analysis(
    ['scripts/launch.py'], pathex=['src'], binaries=[], datas=datas,
    hiddenimports=['mcpaint.app', 'mcpaint.mcp_server', 'mcpaint.selftest'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtPdf', 'PySide6.QtQml', 'PySide6.QtQuick',
              'tkinter', 'matplotlib', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MCPaint',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False, disable_windowed_traceback=False)
mcp = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MCPaint-MCP',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=True)
coll = COLLECT(gui, mcp, a.binaries, a.datas, strip=False, upx=False, name='MCPaint')
