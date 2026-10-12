# Third-party components

MCPaint source is MIT licensed. The portable build also contains third-party software:

- Qt / PySide6 Essentials / Shiboken6: LGPL-3.0 (Qt components may offer other licenses). Qt is dynamically linked in `_internal`. Do not remove the runtime DLLs. License notices shipped with the installed wheels are retained in the runtime. Source and replacement instructions: https://www.qt.io/licensing/open-source-lgpl-obligations and https://code.qt.io/ . Users may replace compatible Qt DLLs and debug modifications to them under the applicable license.
- MCP Python SDK: MIT, https://github.com/modelcontextprotocol/python-sdk .
- Pillow: HPND, https://github.com/python-pillow/Pillow .
- NumPy: BSD-3-Clause, https://github.com/numpy/numpy . Its bundled numerical libraries retain their accompanying notices.
- imageio-ffmpeg: BSD-2-Clause, https://github.com/imageio/imageio-ffmpeg .
- The bundled FFmpeg binary may include GPL codecs (including libx264). Its license and build configuration must accompany the distributed binary; corresponding source is available via the imageio-ffmpeg release documentation and https://ffmpeg.org/download.html . The build script collects the FFmpeg license/configuration in `third-party`.
- Python and remaining dependencies retain their respective licenses. The build script copies installed distribution license notices into `third-party`.

This file is a component inventory. See the packaged license texts for actual terms.
