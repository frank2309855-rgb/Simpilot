"""Bounded local read probe. A stalled cloud file cannot lock the UI forever."""
import json
import os
import subprocess
import sys
from pathlib import Path


def friendly_error(exc):
    if isinstance(exc, PermissionError):
        return "存取被拒：啟動工作台的 Python 環境無權讀取此路徑。請確認 Google Drive 已掛載，並從可讀取 H 槽的一般 Anaconda 啟動工作台。"
    if isinstance(exc, FileNotFoundError):
        return "找不到路徑：請確認磁碟已掛載、資料夾／檔名完整，且不是只貼上檔案捷徑。"
    return str(exc)


def run_probe(path, timeout=8):
    try:
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "gp_frontend.path_probe"],
            input=json.dumps(dict(path=path), ensure_ascii=False), text=True, encoding="utf-8",
            capture_output=True, timeout=timeout, cwd=Path(__file__).resolve().parents[1],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise ValueError(f"超過 {timeout:g} 秒仍未完成讀取。雲端磁碟可能正在回應或下載；已停止本次測試，可確認檔案狀態後重試。") from None
    if result.returncode != 0:
        raise ValueError("路徑檢查程序未完成。請重新啟動工作台，並確認使用原本的 Anaconda 環境。")
    response = json.loads(result.stdout)
    if "error" in response:
        raise ValueError(response["error"])
    return response


if __name__ == "__main__":
    try:
        from .quality import inspect_path
        value = inspect_path(json.load(sys.stdin).get("path"))
    except Exception as exc:
        value = dict(error=friendly_error(exc))
    print(json.dumps(value, ensure_ascii=False))
