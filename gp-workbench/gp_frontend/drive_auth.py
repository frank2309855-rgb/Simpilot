"""Desktop OAuth with PKCE; credentials and tokens live only in process memory."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from gp_eval.validation import require

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def http_session():
    try:
        import requests
    except ImportError:
        raise ValueError("Google Drive 模式需要 requests；請在工作台使用的 Python 安裝 requirements.txt。") from None
    session = requests.Session()
    # Keep environment proxy/TLS configuration, but do not use ambient netrc credentials.
    session.auth = lambda request: request
    return session


class DriveAuth:
    def __init__(self, session=None):
        self.session = session
        self.lock = threading.RLock()
        self.pending = None
        self.credentials = None
        self.tokens = None
        self.expires = 0

    def status(self):
        with self.lock:
            return dict(connected=bool(self.tokens), pending=bool(self.pending), scope=SCOPE)

    def begin(self, path, redirect, consent):
        require(consent is True, "請先確認唯讀權限範圍。")
        path = Path(str(path).strip().strip('"'))
        require(path.is_file() and path.stat().st_size <= 64*1024, "請提供 OAuth 桌面應用程式 JSON 路徑（最多 64 KiB）。")
        with path.open("rb") as stream:
            data = stream.read(64*1024 + 1)
        require(len(data) <= 64*1024, "OAuth JSON 過大。")
        try:
            config = json.loads(data)["installed"]
            client_id, client_secret = config["client_id"], config["client_secret"]
            require(isinstance(client_id, str) and client_id.endswith(".apps.googleusercontent.com"), "OAuth client ID 格式不正確。")
            require(isinstance(client_secret, str) and bool(client_secret), "OAuth client secret 缺失。")
        except (ValueError, KeyError, TypeError):
            raise ValueError("請使用 Google Cloud 的『桌面應用程式』OAuth JSON。") from None
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        with self.lock:
            self.pending = dict(state=state, verifier=verifier, redirect=redirect,
                                created=time.monotonic(), client_id=client_id, client_secret=client_secret)
        return dict(url="https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(dict(
            client_id=client_id, redirect_uri=redirect, response_type="code", scope=SCOPE,
            state=state, code_challenge=challenge, code_challenge_method="S256",
            access_type="offline", prompt="consent")))

    def _exchange(self, values):
        if self.session is None:
            self.session = http_session()
        try:
            with self.session.post(TOKEN_URL, data=values, timeout=(10, 30),
                                   allow_redirects=False, stream=True) as response:
                require(response.status_code == 200, "Google 登入或更新授權失敗；請重新登入並確認 OAuth 設定。")
                body = bytearray()
                for block in response.iter_content(8192):
                    body.extend(block)
                    require(len(body) <= 64*1024, "Google 授權回應異常。")
                result = json.loads(body)
            require(isinstance(result.get("access_token"), str) and bool(result["access_token"]), "授權回應缺少 access token。")
            if "scope" in result:
                require(SCOPE in result["scope"].split(), "未取得 Drive 唯讀授權，請重新登入。")
            lifetime = float(result.get("expires_in", 3600))
            require(60 <= lifetime <= 86400, "授權有效時間異常。")
            self.expires = time.monotonic() + lifetime - 45
            return result
        except ValueError:
            raise ValueError("Google 授權失敗；請確認桌面 OAuth 設定、測試使用者與 Drive 唯讀權限後重新登入。") from None
        except Exception:
            raise ValueError("無法完成 Google 授權連線；請檢查網路後重試。") from None

    def finish(self, params):
        with self.lock:
            pending = self.pending
            state = params.get("state", [""])[0]
            require(pending is not None and secrets.compare_digest(state, pending["state"]), "登入狀態驗證失敗；請從工作台重新登入。")
            self.pending = None
            require(time.monotonic() - pending["created"] < 600, "登入連結已過期，請重新登入。")
            require("error" not in params and bool(params.get("code", [""])[0]), "Google 登入未完成或權限未允許。")
            credentials = {k: pending[k] for k in ("client_id", "client_secret")}
            tokens = self._exchange(dict(**credentials, code=params["code"][0],
                redirect_uri=pending["redirect"], code_verifier=pending["verifier"], grant_type="authorization_code"))
            self.credentials, self.tokens = credentials, tokens

    def token(self):
        with self.lock:
            require(self.tokens is not None, "請先在 Google Drive 面板登入並完成授權。")
            if time.monotonic() >= self.expires:
                require(bool(self.tokens.get("refresh_token")), "授權已過期，請重新登入。")
                refreshed = self._exchange(dict(**self.credentials,
                    refresh_token=self.tokens["refresh_token"], grant_type="refresh_token"))
                self.tokens.update(refreshed)
            return self.tokens["access_token"]

    def disconnect(self):
        with self.lock:
            self.tokens = self.credentials = self.pending = None
            self.expires = 0
        return self.status()
