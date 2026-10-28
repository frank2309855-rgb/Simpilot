"""User-initiated local folder dialog; no file upload or directory copying."""
import json
import os
import subprocess
import sys
from pathlib import Path


def choose():
    try:
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "gp_frontend.folder_picker"],
                                capture_output=True, text=True, encoding="utf-8", timeout=120,
                                cwd=Path(__file__).resolve().parents[1],
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise ValueError("資料夾選取已逾時；可重新選取或直接貼上完整路徑。") from None
    if result.returncode:
        raise ValueError("無法開啟本機資料夾視窗；請直接貼上完整路徑。")
    return json.loads(result.stdout)["path"]


if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(parent=root, title="選取包含 pos_數字 的 raw data 資料夾")
        print(json.dumps(dict(path=selected), ensure_ascii=False))
    finally:
        root.destroy()
