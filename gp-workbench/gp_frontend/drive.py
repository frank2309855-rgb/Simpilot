"""Read-only Drive blobs, bounded transfers and derived-data-only resume cache.

No Drive Desktop paths, raw-file writes, uploads, deletes or server computation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

from gp_eval.validation import require, number
from . import raw
from .drive_auth import http_session

MIB = 1024*1024
FIELDS = "id,name,mimeType,size,md5Checksum,version,modifiedTime,trashed,capabilities(canDownload)"
API = "https://www.googleapis.com/drive/v3/files"
HEADER_WORKERS = 3


def folder_id(value):
    value = str(value).strip().strip('"')
    if re.fullmatch(r"[A-Za-z0-9_-]{5,200}", value):
        return value
    url = urlparse(value)
    match = re.fullmatch(r"/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]{5,200})/?", url.path)
    require(url.scheme == "https" and url.netloc == "drive.google.com" and match is not None,
            "Google Drive 模式需貼上網頁版的資料夾網址或 ID；不能由 H:\\ 路徑自動換算。")
    require("resourcekey" not in parse_qs(url.query), "此連結含 resourcekey；第一版請由擁有者直接分享資料夾給登入帳號，再使用無 resourcekey 的網址。")
    return match[1]


def options(value):
    value = value or {}
    result = {}
    for key, default, lower, upper in (("max_download_mib", 512, 1, 1048576),
            ("max_frame_mib", 32, 1, 128), ("reserve_disk_mib", 256, 64, 1048576)):
        result[key] = number(value.get(key, default), key)
        require(lower <= result[key] <= upper, f"{key} 須介於 {lower}–{upper} MiB。")
    return result


def identity(meta):
    return {key: meta[key] for key in ("id", "name", "size", "md5Checksum", "version", "modifiedTime")}


def validate_blob(meta):
    require(meta.get("trashed") is False and meta.get("capabilities", {}).get("canDownload") is True,
            "檔案已移入垃圾桶或擁有者禁止下載；請由資料擁有者確認權限。")
    require(re.fullmatch(r"[A-Za-z0-9_-]+", str(meta.get("id", ""))) is not None, "Drive 檔案 ID 無效。")
    require(not str(meta.get("mimeType", "")).startswith("application/vnd.google-apps."), "來源必須是原始位置檔，不能是 Google 文件、資料夾或捷徑。")
    require(re.fullmatch(r"[0-9a-f]{32}", meta.get("md5Checksum", "")) is not None,
            "Drive 未提供 MD5，無法驗證原始位置檔；請確認是一般檔案。")
    require(int(meta.get("size", 0)) > 0 and bool(meta.get("version")) and bool(meta.get("modifiedTime")), "Drive 檔案大小或版本資訊缺失。")
    return identity(meta)


class Client:
    def __init__(self, auth, limit, cancel=lambda: False, session=None):
        self.auth, self.cancel, self.limit = auth, cancel, int(limit)
        self.session = session or http_session()
        self._injected_session = session
        self._transfer_lock = threading.Lock()
        self._budget = dict(transferred=0, reserved=0)

    @property
    def transferred(self):
        with self._transfer_lock:
            return self._budget["transferred"]

    @contextmanager
    def header_worker(self, stop):
        # Separate HTTP sessions; shared auth (already locked) and transfer budget.
        worker = copy.copy(self)
        worker.cancel = lambda: self.cancel() or stop.is_set()
        worker.session = self._injected_session if self._injected_session is not None else http_session()
        try:
            yield worker
        finally:
            if self._injected_session is None:
                worker.session.close()

    def get(self, suffix="", params=None, byte_range=None, cap=MIB):
        raw.check_cancel(self.cancel)
        headers = {"Authorization": "Bearer " + self.auth.token(), "Accept-Encoding": "identity"}
        if byte_range is not None:
            headers["Range"] = f"bytes=0-{byte_range-1}"
        reserved = 0
        try:
            with self.session.get(API + suffix, params=params, headers=headers,
                                  timeout=(10, 30), stream=True, allow_redirects=False) as response:
                require(response.status_code in (200, 206),
                    f"Drive 回應 HTTP {response.status_code}。請確認權限／API 設定；若為 429 或 5xx，稍後重新預覽後再計算，已完成的 frame 可重用。")
                if byte_range is not None:
                    require(response.status_code == 206,
                            "Drive 未接受局部讀取；已停止，避免預覽時下載完整 raw 檔。")
                    match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    require(match is not None and int(match[1])+1 <= cap, "Drive Range 回應範圍異常。")
                declared = response.headers.get("Content-Length")
                allowance = int(declared) if declared is not None else cap
                require(0 <= allowance <= cap, "預計傳輸超過單檔上限；已停止。")
                # Reserve response bytes before consuming its body. Unknown lengths
                # reserve the per-request cap so concurrent reads cannot overspend.
                with self._transfer_lock:
                    require(self._budget["transferred"] + self._budget["reserved"] + allowance <= self.limit,
                            "預計傳輸超過本次傳輸上限；已停止。")
                    self._budget["reserved"] += allowance
                    reserved = allowance
                body = bytearray()
                for block in response.iter_content(chunk_size=64*1024):
                    with self._transfer_lock:
                        self._budget["transferred"] += len(block)
                        consumed = min(len(block), reserved)
                        self._budget["reserved"] -= consumed
                        reserved -= consumed
                        require(self._budget["transferred"] <= self.limit and len(body)+len(block) <= allowance,
                                "已達本次傳輸／單檔上限；未將原始檔寫入硬碟。")
                    raw.check_cancel(self.cancel)
                    body.extend(block)
                if declared is not None:
                    require(len(body) == int(declared), "Drive 傳輸中斷；請重試。")
                if byte_range is not None:
                    require(len(body) == int(match[1])+1, "Drive 局部讀取不完整。")
                return bytes(body)
        except ValueError:
            raise
        except Exception:
            raise ValueError("Drive 連線失敗或傳輸中斷。請檢查網路後重新預覽／計算；已完成的衍生快取會保留。") from None
        finally:
            with self._transfer_lock:
                self._budget["reserved"] -= reserved

    def metadata(self, file_id):
        require(re.fullmatch(r"[A-Za-z0-9_-]+", file_id) is not None, "Drive ID 無效。")
        return json.loads(self.get("/"+file_id, dict(fields=FIELDS, supportsAllDrives="true")))

    def files(self, folder):
        meta = self.metadata(folder)
        require(meta.get("mimeType") == "application/vnd.google-apps.folder" and meta.get("trashed") is False,
                "來源不是可用的 Google Drive 資料夾。")
        result, page, seen, pages = [], None, set(), set()
        while True:
            params = dict(q=f"'{folder}' in parents and trashed = false", pageSize=1000,
                          fields=f"nextPageToken,incompleteSearch,files({FIELDS})",
                          supportsAllDrives="true", includeItemsFromAllDrives="true")
            if page:
                params["pageToken"] = page
            data = json.loads(self.get(params=params))
            require(not data.get("incompleteSearch"), "Drive 回報清單搜尋不完整；請縮小來源或確認共用雲端硬碟權限。")
            for item in data.get("files", []):
                require(item["id"] not in seen, "Drive 清單重複，請重新預覽。")
                seen.add(item["id"])
                require(len(seen) <= 20000, "資料夾超過 20000 個項目；請縮小來源。")
                if re.fullmatch(r"pos_\d+", item.get("name", "")):
                    result.append(validate_blob(item))
            page = data.get("nextPageToken")
            if not page:
                break
            require(page not in pages and len(pages) < 100, "Drive 分頁異常或項目過多；請縮小來源。")
            pages.add(page)
        require(bool(result), "資料夾中找不到 pos_數字 原始位置檔（不遞迴子資料夾）。")
        return sorted(result, key=lambda item: item["id"])

    def blob(self, meta, cap):
        require(int(meta["size"]) <= cap, "原始位置檔超過單一 frame 大小上限。")
        require(validate_blob(self.metadata(meta["id"])) == meta, "Drive 檔案已變更，請重新預覽。")
        data = self.get("/"+meta["id"], dict(alt="media", supportsAllDrives="true"), cap=cap)
        require(len(data) == int(meta["size"]) and hashlib.md5(data).hexdigest() == meta["md5Checksum"],
                "原始位置檔的大小或 MD5 不符，結果不會送入模型。")
        require(validate_blob(self.metadata(meta["id"])) == meta, "讀取期間 Drive 檔案版本改變，請重新預覽。")
        return data


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_header(client, meta, cache):
    path = cache / (key(meta)+".header.json")
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            require(saved["identity"] == meta and saved["sha256"] == hashlib.sha256(saved["line"].encode()).hexdigest(), "header cache mismatch")
            return raw.header(saved["line"])
        except (ValueError, KeyError, OSError, TypeError):
            pass
    data = client.get("/"+meta["id"], dict(alt="media", supportsAllDrives="true"), byte_range=4096, cap=4096)
    require(b"\n" in data, "前 4 KiB 找不到完整檔頭。")
    line = data.decode("utf-8-sig").split("\n", 1)[0]
    parsed = raw.header(line)
    require(validate_blob(client.metadata(meta["id"])) == meta, "讀取檔頭時來源版本改變，請重新預覽。")
    path.write_text(json.dumps(dict(identity=meta, line=line, sha256=hashlib.sha256(line.encode()).hexdigest())), encoding="utf-8")
    return parsed


def preview(client, folder, s, cache, opts, progress=lambda text: None):
    cache.mkdir(parents=True, exist_ok=True)
    progress("讀取資料夾檔名清單（不讀位置檔內容）")
    listing = client.files(folder_id(folder))
    # Drive mode requires pos_<step>; filter metadata before any media request.
    candidates = sorted(
        ((int(meta["name"].split("_", 1)[1]), meta) for meta in listing),
        key=lambda item: item[0])
    candidates = [(step, meta) for step, meta in candidates
                  if s["step_start"] <= step <= s["step_end"]]
    require(bool(candidates), "指定步數範圍沒有對應檔名；Drive 模式要求 pos_數字 的數字等於檔頭時間步，未掃描區間外檔頭。")
    require(len({step for step, _ in candidates}) == len(candidates), "指定區間存在重複檔名時間步，請確認來源。")
    selected = candidates[::s["stride"]]
    stop = threading.Event()
    progress_lock = threading.Lock()
    errors = []
    completed = 0
    workers = min(HEADER_WORKERS, len(selected))

    def report():
        progress(f"選定檔頭 {completed}/{len(selected)} 完成（最多同時 {workers} 個；清單 {len(listing)} 檔；每 {s['stride']} 個取一個；最多 4 KiB／檔）")

    def read_batch(batch):
        nonlocal completed
        entries = []
        try:
            with client.header_worker(stop) as worker:
                for filename_step, meta in batch:
                    raw.check_cancel(worker.cancel)
                    disk_check(cache, opts, 16384)
                    step, n, box = read_header(worker, meta, cache)
                    require(step == filename_step,
                            f"{meta['name']} 的檔名時間步 {filename_step} 與檔頭 {step} 不一致；已停止，未改為掃描全部檔頭。請確認檔名與時間步對應。")
                    entries.append(dict(step=step, n=n, box=box.tolist(), remote=meta))
                    with progress_lock:
                        completed += 1
                        report()
        except Exception as exc:
            with progress_lock:
                errors.append(exc)
                stop.set()
        return entries

    report()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="drive-header") as pool:
        batches = list(pool.map(read_batch, (selected[i::workers] for i in range(workers))))
    if errors:
        raise errors[0]
    raw.check_cancel(client.cancel)
    entries = sorted((entry for batch in batches for entry in batch), key=lambda entry: entry["step"])
    first = entries[0]
    steps = np.array([e["step"] for e in entries], dtype=np.int64)
    require(len(steps) < 2 or np.all(np.diff(steps) == steps[1]-steps[0]), "選取的時間步不等間距，無法等權平均。")
    require(all(e["n"] == first["n"] and e["box"] == first["box"] for e in entries), "窗口內粒子數／盒長改變。")
    require(all(int(e["remote"]["size"]) <= opts["max_frame_mib"]*MIB for e in entries), "選定檔案超過單一 frame 上限，請調整設定。")
    grid = raw.reciprocal_grid(first["box"], s)
    require(len(entries)*len(grid["q"]) <= 1000000, "預計輸出超過一百萬列，請縮小時間窗或增加取樣間隔。")
    times = steps*s["time_scale"] + s["time_offset"]
    require(np.isfinite(times).all() and (len(times)<2 or np.all(np.diff(times)>0)), "換算後時間無效。")
    summary = dict(folder=folder, frames=len(entries), first_step=int(steps[0]), last_step=int(steps[-1]),
        time_start=float(times[0]), time_end=float(times[-1]), particles=first["n"], counts=None,
        particle_fraction_a=None, box_raw=first["box"], modes_half=len(grid["modes"]),
        q=grid["q"].tolist(), q_low=grid["q_low"].tolist(), q_high=grid["q_high"].tolist(),
        directions_full=(2*grid["counts"]).tolist(),
        estimated_particle_mode_pairs=len(entries)*first["n"]*len(grid["modes"]),
        selected_raw_bytes=sum(int(e["remote"]["size"]) for e in entries),
        estimated_output_and_cache_bytes=len(entries)*(len(grid["q"])*320+8192))
    return dict(folder=folder, listing=listing, entries=entries, summary=summary)


def disk_check(root, opts, estimate=0):
    require(shutil.disk_usage(root).free >= opts["reserve_disk_mib"]*MIB + estimate,
            "本機可用空間低於保留空間加預估輸出，已停止；不會刪除 Google Drive 檔案。")


class Source:
    """Adapt verified remote frames to the existing local structure-factor engine."""
    def __init__(self, client, record, s, cache, opts):
        self.client, self.record, self.s, self.cache, self.opts = client, record, s, cache, opts
        self.start_bytes = client.transferred
        self.entries = {e["remote"]["id"]: e for e in record["entries"]}
        self.last = None
        self.cache.mkdir(parents=True, exist_ok=True)
        self.code = hashlib.sha256(Path(raw.__file__).read_bytes()).hexdigest()
        self.expected_q = raw.reciprocal_grid(record["entries"][0]["box"], s)["q"]

    def paths(self, file_id):
        value = key(dict(remote=self.entries[file_id]["remote"], settings=self.s,
                         version=raw.VERSION, implementation=self.code))
        return self.cache / (value+".curve.npz"), self.cache / (value+".curve.json")

    def cached(self, file_id):
        data_path, manifest_path = self.paths(file_id)
        try:
            require(data_path.stat().st_size <= 32*MIB and manifest_path.stat().st_size <= 16384, "cache too large")
            meta = json.loads(manifest_path.read_text(encoding="utf-8"))
            require(meta["remote"] == self.entries[file_id]["remote"] and
                    meta["sha256_npz"] == hashlib.sha256(data_path.read_bytes()).hexdigest(), "cache changed")
            with np.load(data_path, allow_pickle=False) as saved:
                partials, q = saved["partials"].copy(), saved["q"].copy()
            entry = self.entries[file_id]
            expected = self.expected_q
            require(np.array_equal(expected, q) and partials.shape == (len(q), 3) and
                np.isfinite(partials).all() and (partials[:, :2] >= 0).all() and
                np.all(partials[:, 2]**2 <= partials[:, 0]*partials[:, 1] + 1e-8), "invalid curve cache")
            counts = meta["counts"]
            require(isinstance(counts, list) and len(counts) == 2 and all(isinstance(n, int) and n>0 for n in counts)
                    and sum(counts) == entry["n"] and re.fullmatch(r"[0-9a-f]{64}", meta["raw_sha256"]), "invalid frame cache")
            return dict(step=entry["step"], n=entry["n"], box=np.array(entry["box"]),
                        counts=counts, sha256=meta["raw_sha256"], cached_partials=partials)
        except (OSError, ValueError, KeyError, EOFError, TypeError):
            return None

    def inventory(self, cancel):
        raw.check_cancel(cancel)
        require(self.client.files(folder_id(self.record["folder"])) == self.record["listing"],
                "Drive 檔案清單或版本已變更，請重新預覽後再計算。")
        return [(e["step"], Path(e["remote"]["id"]), e["n"], np.array(e["box"])) for e in self.record["entries"]]

    def read_frame(self, path, s):
        file_id = path.name
        disk_check(self.cache, self.opts)
        if self.last is not None and self.last[0] == file_id:
            return self.last[1]
        # Release previous coordinates before fetching the next frame.
        self.last = None
        remote = self.entries[file_id]["remote"]
        require(validate_blob(self.client.metadata(file_id)) == remote, "Drive 來源已變更，請重新預覽。")
        frame = self.cached(file_id)
        if frame is None:
            data = self.client.blob(remote, int(self.opts["max_frame_mib"]*MIB))
            frame = raw.parse_frame(data, s)
        entry = self.entries[file_id]
        require(frame["step"] == entry["step"] and frame["n"] == entry["n"] and np.array_equal(frame["box"], entry["box"]),
                "原始座標與預覽檔頭不符；請重新預覽。")
        self.last = (file_id, frame)
        return frame

    def remember(self, path, frame, partials, q):
        if "cached_partials" in frame:
            return
        disk_check(self.cache, self.opts, partials.nbytes*2+8192)
        data_path, manifest_path = self.paths(path.name)
        tmp = data_path.with_suffix(".partial.npz")
        np.savez_compressed(tmp, q=q, partials=partials)
        tmp.replace(data_path)
        meta = dict(remote=self.entries[path.name]["remote"], counts=frame["counts"],
                    raw_sha256=frame["sha256"], sha256_npz=hashlib.sha256(data_path.read_bytes()).hexdigest())
        temp_meta = manifest_path.with_suffix(".partial.json")
        temp_meta.write_text(json.dumps(meta), encoding="utf-8")
        temp_meta.replace(manifest_path)

    def provenance(self, path):
        return self.entries[path.name]["remote"]

    def remaining_bytes(self):
        return sum(int(e["remote"]["size"]) for id_, e in self.entries.items() if self.cached(id_) is None)
