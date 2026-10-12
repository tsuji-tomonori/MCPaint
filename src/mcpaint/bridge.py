"""Authenticated loopback bridge. Qt objects are accessed only on the GUI thread."""

from __future__ import annotations

import json
import os
import queue
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .engine import Document


def data_dir():
    root = os.environ.get("MCPAINT_HOME")
    return Path(root).expanduser().resolve() if root else Path.home() / ".mcpaint"


@dataclass
class Job:
    payload: dict
    done: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None


class Bridge:
    def __init__(self):
        self.queue = queue.Queue(maxsize=32)
        self.token = secrets.token_urlsafe(32)
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if self.path != "/command" or not secrets.compare_digest(
                    self.headers.get("Authorization", ""), f"Bearer {bridge.token}"
                ):
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32 * 1024 * 1024:
                        self.send_error(413)
                        return
                    payload = json.loads(self.rfile.read(size))
                    if payload.get("op") == "ping":
                        from . import __version__

                        result = {"ok": True, "name": "MCPaint", "version": __version__}
                    else:
                        job = Job(payload)
                        bridge.queue.put_nowait(job)
                        if not job.done.wait(120):
                            raise TimeoutError("描画処理の応答を待つ時間を超えました")
                        result = job.result
                    data = json.dumps(result, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (ValueError, queue.Full, TimeoutError) as e:
                    self.send_error(400, str(e).encode("ascii", "replace").decode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.directory = data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_path = self.directory / "session.json"
        payload = {"token": self.token, "port": self.server.server_port, "pid": os.getpid()}
        tmp = self.directory / f"session-{os.getpid()}.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        if os.name != "nt":
            tmp.chmod(0o600)
        tmp.replace(self.session_path)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        try:
            if json.loads(self.session_path.read_text())["token"] == self.token:
                self.session_path.unlink()
        except (FileNotFoundError, ValueError, KeyError):
            pass

    def drain(self, handler):
        while True:
            try:
                job = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                job.result = {"ok": True, **handler(job.payload)}
            except Exception as e:
                job.result = {"ok": False, "error": str(e)}
            finally:
                job.done.set()


def clone_document(doc):
    """Snapshot for export worker; never share live mutable QImages."""
    result = Document(doc.width, doc.height, doc.background, doc.base_id)
    import copy

    result.timeline = copy.deepcopy(doc.timeline)
    return result
