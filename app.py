#!/usr/bin/env python3
"""Local-first web application for Arknights RIIC roster optimization."""

from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from maabase.importers import parse_roster
from maabase.optimizer import optimize
from maabase.roster_store import load_roster, save_roster
from maabase.simulator import simulate
from maabase.skland import Client as SklandClient
from maabase.skland import SklandError, create_scan, credential_from_scan_code, get_scan_code


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
CATALOG = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
ROSTER_PATH = ROOT / "data" / "user_roster.json"
APP_REVISION = "2026.08.17-skill-precedence-v9"
SCAN_SESSIONS: dict[str, dict] = {}
SCAN_LOCK = threading.Lock()


def _qr_data_uri(value: str) -> str:
    try:
        import qrcode
    except ImportError as exc:
        raise ValueError("缺少二维码组件，请运行 .venv/bin/python -m pip install -r requirements.txt") from exc
    image = qrcode.make(value)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _scan_session(scan_id: str) -> dict:
    with SCAN_LOCK:
        session = SCAN_SESSIONS.get(scan_id)
        if not session or float(session["expires_at"]) < time.time():
            SCAN_SESSIONS.pop(scan_id, None)
            raise ValueError("二维码已过期，请重新生成")
        return session


class Handler(BaseHTTPRequestHandler):
    server_version = "MaaBaseOptimizer/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-MaaBaseOptimizer-Revision", APP_REVISION)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 20 * 1024 * 1024:
            raise ValueError("请求文件过大")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/operators":
            operators = [
                {"id": op_id, "name": op["name"], "rarity": op["rarity"]}
                for op_id, op in CATALOG["operators"].items()
            ]
            operators.sort(key=lambda x: (-x["rarity"], x["name"]))
            self._json(200, {
                "operators": operators,
                "count": len(operators),
                "schema": CATALOG["schema"],
                "app_revision": APP_REVISION,
            })
            return
        if path == "/api/roster":
            roster = load_roster(ROSTER_PATH, CATALOG)
            self._json(200, {"operators": roster, "count": len(roster)})
            return
        if path == "/api/skland/scan/status":
            try:
                scan_id = (parse_qs(parsed.query).get("scan_id") or [""])[0]
                session = _scan_session(scan_id)
                if session.get("credential"):
                    self._json(200, {"status": "authorized", "accounts": session["accounts"]})
                    return
                scan_code = get_scan_code(scan_id)
                if not scan_code:
                    self._json(200, {"status": "waiting"})
                    return
                credential = credential_from_scan_code(scan_code)
                accounts = SklandClient(credential).bindings()
                with SCAN_LOCK:
                    session["credential"] = credential
                    session["accounts"] = accounts
                self._json(200, {"status": "authorized", "accounts": accounts})
            except (ValueError, SklandError) as exc:
                self._json(400, {"error": str(exc)})
            return
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        file = (WEB / relative).resolve()
        if WEB.resolve() not in file.parents or not file.is_file():
            self.send_error(404)
            return
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-MaaBaseOptimizer-Revision", APP_REVISION)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._payload()
            if self.path == "/api/import":
                roster, warnings = parse_roster(payload, CATALOG)
                save_roster(ROSTER_PATH, roster, CATALOG)
                self._json(200, {"operators": roster, "warnings": warnings})
            elif self.path == "/api/roster":
                roster = save_roster(ROSTER_PATH, payload.get("operators") if isinstance(payload, dict) else payload, CATALOG)
                self._json(200, {"operators": roster, "count": len(roster), "saved": True})
            elif self.path == "/api/skland/scan/start":
                scan = create_scan()
                with SCAN_LOCK:
                    expired = [key for key, value in SCAN_SESSIONS.items() if float(value["expires_at"]) < time.time()]
                    for key in expired:
                        SCAN_SESSIONS.pop(key, None)
                    SCAN_SESSIONS[scan["scan_id"]] = dict(scan)
                self._json(200, {
                    "scan_id": scan["scan_id"],
                    "expires_at": scan["expires_at"],
                    "qr_data_uri": _qr_data_uri(scan["scan_url"]),
                })
            elif self.path == "/api/skland/import":
                if not isinstance(payload, dict):
                    raise ValueError("请求格式错误")
                scan_id = str(payload.get("scan_id") or "")
                uid = str(payload.get("uid") or "")
                session = _scan_session(scan_id)
                credential = session.get("credential")
                if not credential:
                    raise ValueError("尚未完成扫码授权")
                accounts = session.get("accounts") or []
                account = next((x for x in accounts if x.get("uid") == uid), None)
                if not account:
                    raise ValueError("所选角色不在本次森空岛授权的绑定列表中")
                roster = SklandClient(credential).operators(uid, CATALOG)
                roster = save_roster(ROSTER_PATH, roster, CATALOG)
                with SCAN_LOCK:
                    SCAN_SESSIONS.pop(scan_id, None)
                self._json(200, {"operators": roster, "count": len(roster), "account": account})
            elif self.path == "/api/optimize":
                if isinstance(payload, dict):
                    payload.setdefault("include_rotation", True)
                self._json(200, optimize(payload, CATALOG))
            elif self.path == "/api/simulate":
                if not isinstance(payload, dict):
                    raise ValueError("请求格式错误")
                self._json(200, simulate(payload))
            else:
                self._json(404, {"error": "unknown endpoint"})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # keep local UI usable and show actionable error
            self._json(500, {"error": f"计算失败：{exc.__class__.__name__}: {exc}"})


def main() -> None:
    parser = argparse.ArgumentParser(description="明日方舟基建候选集排班优化器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"MaaBaseOptimizer 已启动：{url}")
    print("按 Control-C 停止。数据只在本机处理。")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
