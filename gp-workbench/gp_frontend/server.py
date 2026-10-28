"""Local-only workbench: authenticated actions, guarded report reads and scoped run deletion."""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.cookies import SimpleCookie
from .examples import project as example_project

from .path_probe import run_probe
from .csv_window import run_window_probe
from .service import Workbench


def create_server(root, port=8765):
    workbench = Workbench(root)
    token = secrets.token_urlsafe(32)
    cookie_name = "gp_workbench_session"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, content_type="application/json; charset=utf-8", set_session=False):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; object-src 'none'")
            if set_session:
                self.send_header('Set-Cookie',f'{cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # Client has already stopped waiting; no partial success claim.

        def valid_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def authenticated(self):
            return secrets.compare_digest(self.headers.get("X-Workbench-Token", ""), token)

        def same_origin(self):
            origin=self.headers.get('Origin')
            allowed=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
            return (not origin or origin in allowed) and self.headers.get('Sec-Fetch-Site') not in ('cross-site', 'same-site')

        def session_authenticated(self):
            try:
                cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                value=cookies.get(cookie_name)
                return bool(value) and secrets.compare_digest(value.value,token)
            except (ValueError,TypeError):
                return False

        def drive_idle(self):
            with workbench.lock:
                if any(j["status"] in ("queued", "running") for j in workbench.jobs.values()):
                    raise ValueError("請等目前工作結束後再更換 Google Drive 登入狀態。")

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, dict(error="Host rejected"))
            path = urlparse(self.path).path
            if path != '/oauth/drive/callback' and not self.same_origin():
                return self.send(403,dict(error='Cross-site read rejected; open the local workbench directly.'))
            try:
                if path == "/oauth/drive/callback":
                    self.drive_idle()
                    workbench.drive_auth.finish(parse_qs(urlparse(self.path).query))
                    return self.send(200, '<!doctype html><meta charset="utf-8"><title>登入完成</title><h1>Google Drive 登入完成</h1><p>請回到工作台，按「更新登入狀態」。可以關閉此分頁。</p>'.encode("utf-8"), "text/html; charset=utf-8")
                if path == "/":
                    data = (Path(__file__).parent / "static/index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", token)
                    return self.send(200, data.encode("utf-8"), "text/html; charset=utf-8", set_session=True)
                if path == "/targets.js":
                    return self.send(200, (Path(__file__).parent / "static/targets.js").read_bytes(), "text/javascript; charset=utf-8")
                if path == "/app.js":
                    return self.send(200, (Path(__file__).parent / "static/app.js").read_bytes(), "text/javascript; charset=utf-8")
                if path.startswith("/api/"):
                    if not self.authenticated():
                        return self.send(403, dict(error="請重新開啟本機介面。"))
                    if path.startswith("/api/jobs/"):
                        return self.send(200, workbench.job(path.rsplit("/", 1)[-1]))
                    if path == "/api/history":
                        return self.send(200, workbench.history())
                    if path == "/api/drive/status":
                        return self.send(200, workbench.drive_auth.status())
                match = re.fullmatch(r"/runs/([0-9]{8}_[0-9]{6}_[a-f0-9]{6})/(.+)", path)
                if match:
                    if not (self.authenticated() or self.session_authenticated()):
                        return self.send(403,dict(error='Open the workbench before accessing reports.'))
                    runs=(workbench.root/'web_runs').resolve()
                    base = (runs / match[1]).resolve()
                    if base.parent != runs:
                        return self.send(404,dict(error='Invalid report path.'))
                    file = (base / match[2]).resolve()
                    if base not in file.parents or file.suffix not in (".html", ".json", ".csv") or not file.is_file():
                        return self.send(404, dict(error="檔案不存在。"))
                    return self.send(200, file.read_bytes(), (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8")
                return self.send(404, dict(error="找不到頁面。"))
            except (ValueError, OSError) as exc:
                return self.send(400, dict(error=str(exc)))

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
            if not self.valid_host() or not self.authenticated() or not self.same_origin():
                return self.send(403, dict(error="跨來源請求已拒絕；請在本機介面操作。"))
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 256 * 1024:
                    return self.send(413, dict(error="設定資料過大或空白。"))
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("請求必須是 JSON 物件。")
                if self.path == "/api/drive/login":
                    self.drive_idle()
                    return self.send(200, workbench.drive_auth.begin(payload.get("client_json_path"),
                        f"http://127.0.0.1:{self.server.server_port}/oauth/drive/callback", payload.get("consent")))
                if self.path == "/api/drive/disconnect":
                    self.drive_idle()
                    workbench.drive_plans.clear()
                    return self.send(200, workbench.drive_auth.disconnect())
                if self.path == "/api/history/delete-preview":
                    return self.send(200, workbench.preview_run_deletion(payload.get("run_id")))
                if self.path == "/api/history/delete":
                    return self.send(200, workbench.delete_run(payload))
                if self.path == "/api/csv-window":
                    return self.send(200, run_window_probe(payload.get("paths")))
                if self.path == "/api/inspect":
                    return self.send(200, run_probe(payload.get("path")))
                if self.path == '/api/example-project':
                    return self.send(200,example_project())
                if self.path == "/api/demo":
                    return self.send(200, workbench.demo())
                if self.path == "/api/raw-demo":
                    from .raw_demo import make
                    return self.send(200, make(workbench.root))
                if self.path == "/api/cancel":
                    return self.send(200, workbench.cancel(payload.get("job_id")))
                if self.path in ("/api/analyze", "/api/train", "/api/preview_raw", "/api/extract_raw", "/api/choose_folder", "/api/project_scattering"):
                    return self.send(202, workbench.start(self.path.rsplit("/", 1)[-1], payload))
                return self.send(404, dict(error="未知操作。"))
            except (ValueError, OSError, TypeError, KeyError) as exc:
                return self.send(400, dict(error=str(exc)))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    cookie_name = f"gp_workbench_session_{server.server_port}"
    server.workbench = workbench
    return server


def main():
    parser = argparse.ArgumentParser(description="Local five-ratio condition GP workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path, help="Output workspace; defaults to ./runtime beside the application")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    root = (args.workspace or (Path(__file__).resolve().parents[1]/"runtime")).resolve()
    root.mkdir(parents=True,exist_ok=True)
    server = create_server(root, args.port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"GP workbench: {url}\nKeep this terminal open. Ctrl+C stops the server.", flush=True)
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.workbench.pool.shutdown(wait=True)
