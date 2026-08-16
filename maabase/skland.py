"""Minimal local-only Skland QR login and operator importer.

The request flow follows the public goofish-infrast Skland client. Credentials
are deliberately returned to the caller for in-memory use only and are never
written by this module.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


APP_CODE = "4ca99fa6b56cc2ba"
HYPERGRYPH_BASE = "https://as.hypergryph.com"
SKLAND_BASE = "https://zonai.skland.com"
USER_AGENT = "Skland/1.21.0 (com.hypergryph.skland; build:102100065; iOS 17.6.0; ) Alamofire/5.7.1"
TIMEOUT = 25


class SklandError(RuntimeError):
    pass


def _request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    attempts = 3 if method == "GET" else 1
    last_error: Exception | None = None
    value: Any = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                value = json.loads(response.read().decode("utf-8"))
            last_error = None
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise SklandError(f"鹰角或森空岛接口返回 HTTP {exc.code}") from exc
            last_error = exc
        except (http.client.IncompleteRead, http.client.RemoteDisconnected, urllib.error.URLError, socket.timeout, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
        time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        if isinstance(last_error, http.client.IncompleteRead):
            raise SklandError(f"森空岛数据传输中断（已收到 {len(last_error.partial)} 字节），自动重试后仍未完成") from last_error
        raise SklandError(f"连接鹰角或森空岛接口失败：{last_error}") from last_error
    if not isinstance(value, dict):
        raise SklandError("鹰角或森空岛接口返回了无法识别的数据")
    return value


def create_scan() -> dict:
    value = _request(
        f"{HYPERGRYPH_BASE}/general/v1/gen_scan/login",
        method="POST",
        headers={"Content-Type": "application/json;charset=utf-8"},
        body={"appCode": APP_CODE},
    )
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    scan_id = data.get("scanId")
    if value.get("status") != 0 or value.get("msg") != "OK" or not isinstance(scan_id, str):
        raise SklandError("生成鹰角扫码登录二维码失败，请稍后重试")
    return {
        "scan_id": scan_id,
        "scan_url": f"hypergryph://scan_login?scanId={urllib.parse.quote(scan_id)}",
        "expires_at": time.time() + 120,
    }


def get_scan_code(scan_id: str) -> str | None:
    query = urllib.parse.urlencode({"scanId": scan_id})
    value = _request(f"{HYPERGRYPH_BASE}/general/v1/scan_status?{query}")
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    code = data.get("scanCode")
    return code if value.get("status") == 0 and isinstance(code, str) and code else None


def credential_from_scan_code(scan_code: str) -> str:
    login = _request(
        f"{HYPERGRYPH_BASE}/user/auth/v1/token_by_scan_code",
        method="POST",
        headers={"Content-Type": "application/json;charset=utf-8"},
        body={"scanCode": scan_code},
    )
    login_data = login.get("data") if isinstance(login.get("data"), dict) else {}
    token = login_data.get("token")
    if login.get("status") != 0 or login.get("msg") != "OK" or not isinstance(token, str):
        raise SklandError("扫码已确认，但获取鹰角登录凭据失败，请重新扫码")

    oauth = _request(
        f"{HYPERGRYPH_BASE}/user/oauth2/v2/grant",
        method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json;charset=utf-8"},
        body={"appCode": APP_CODE, "type": 0, "token": token},
    )
    oauth_data = oauth.get("data") if isinstance(oauth.get("data"), dict) else {}
    code = oauth_data.get("code")
    if oauth.get("msg") != "OK" or not isinstance(code, str):
        raise SklandError("鹰角授权换取森空岛 code 失败，请重新扫码")

    timestamp = str(int(time.time()))
    cred = _request(
        f"{SKLAND_BASE}/web/v1/user/auth/generate_cred_by_code",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/129 Safari/537.36",
            "Referer": "https://www.skland.com/",
            "Origin": "https://www.skland.com",
            "dId": str(uuid.uuid4()),
            "platform": "3",
            "timestamp": timestamp,
            "vName": "1.0.0",
        },
        body={"kind": 1, "code": code},
    )
    cred_data = cred.get("data") if isinstance(cred.get("data"), dict) else {}
    result = cred_data.get("cred")
    if cred.get("message") != "OK" or not isinstance(result, str):
        raise SklandError("森空岛凭据生成失败，请重新扫码")
    return result


def _sign(token: str, path: str, query: str, timestamp: str) -> str:
    header = {"platform": "1", "timestamp": timestamp, "dId": "", "vName": "1.21.0"}
    source = path + query + timestamp + json.dumps(header, ensure_ascii=False, separators=(",", ":"))
    digest = hmac.new(token.encode(), source.encode(), hashlib.sha256).hexdigest()
    # The upstream protocol requires MD5 around an HMAC-SHA256 digest.
    return hashlib.md5(digest.encode(), usedforsecurity=False).hexdigest()  # noqa: S324


class Client:
    def __init__(self, credential: str):
        self.credential = credential
        self.token = ""
        self.timestamp = ""

    def _headers(self, timestamp: str, sign: str) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "platform": "1",
            "Accept-Language": "zh-Hans-CN;q=1.0",
            "dId": "",
            "vName": "1.21.0",
            "language": "zh-hans-CN",
            "sign": sign,
            "timestamp": timestamp,
        }

    def _refresh(self) -> None:
        timestamp = str(int(time.time()))
        path = "/api/v1/auth/refresh"
        sign = _sign("", path, "", timestamp)
        headers = {**self._headers(timestamp, sign), "cred": self.credential}
        value = _request(f"{SKLAND_BASE}{path}", headers=headers)
        data = value.get("data") if isinstance(value.get("data"), dict) else {}
        if value.get("code") != 0 or value.get("message") != "OK" or not isinstance(data.get("token"), str):
            raise SklandError("森空岛凭据已失效，请重新扫码")
        self.token = data["token"]
        self.timestamp = str(value.get("timestamp") or timestamp)

    def get(self, path: str, query: str = "") -> dict:
        if not self.token:
            self._refresh()
        timestamp = self.timestamp or str(int(time.time()))
        sign = _sign(self.token, path, query, timestamp)
        headers = {**self._headers(timestamp, sign), "cred": self.credential, "token": self.token}
        suffix = f"?{query}" if query else ""
        value = _request(f"{SKLAND_BASE}{path}{suffix}", headers=headers)
        if value.get("code") != 0 or value.get("message") != "OK":
            raise SklandError(str(value.get("message") or "读取森空岛数据失败"))
        return value

    def bindings(self) -> list[dict]:
        value = self.get("/api/v1/game/player/binding")
        data = value.get("data") if isinstance(value.get("data"), dict) else {}
        accounts: list[dict] = []
        seen: set[str] = set()
        for group in data.get("list", []):
            if not isinstance(group, dict) or group.get("appCode") != "arknights":
                continue
            bindings = [x for x in group.get("bindingList", []) if isinstance(x, dict)]
            default_uid = str(group.get("defaultUid") or "")
            for binding in bindings:
                uid = str(binding.get("uid") or (default_uid if len(bindings) == 1 else ""))
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                accounts.append({
                    "uid": uid,
                    "nickname": str(binding.get("nickName") or binding.get("nickname") or uid),
                    "channel_name": str(binding.get("channelName") or binding.get("channel") or "官方"),
                    "is_default": uid == default_uid,
                })
        if not accounts:
            raise SklandError("森空岛账号未找到已绑定的明日方舟角色")
        return sorted(accounts, key=lambda x: not x["is_default"])

    def operators(self, uid: str, catalog: dict) -> list[dict]:
        query = urllib.parse.urlencode({"uid": uid})
        value = self.get("/api/v1/game/player/info", query)
        data = value.get("data") if isinstance(value.get("data"), dict) else {}
        chars = data.get("chars") if isinstance(data.get("chars"), list) else []
        result: list[dict] = []
        seen: set[str] = set()
        for raw in chars:
            if not isinstance(raw, dict):
                continue
            op_id = str(raw.get("charId") or raw.get("id") or "")
            if op_id not in catalog["operators"] or op_id in seen:
                continue
            seen.add(op_id)
            result.append({
                "id": op_id,
                "name": catalog["operators"][op_id]["name"],
                "elite": max(0, min(2, int(raw.get("evolvePhase", 0) or 0))),
                "level": max(1, min(90, int(raw.get("level", 1) or 1))),
                "potential": max(1, min(6, int(raw.get("potentialRank", 0) or 0) + 1)),
            })
        if not result:
            raise SklandError("森空岛返回的干员数据为空，或当前技能数据库版本无法匹配")
        return sorted(result, key=lambda x: x["name"])
