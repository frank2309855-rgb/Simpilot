"""Deterministic, auditable peak screening of long-form S(q,t) CSV files.

This is a screening rule, not an equilibrium test or confidence interval.
Frames/blocks never become separate training observations.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from gp_eval.validation import number, nonempty, require

VERSION = "1.0.0"
MAX_BYTES = 64 * 1024 * 1024


def local_path(value):
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    value = nonempty(value, "檔案路徑")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    require(bool(value), "請填入檔案或資料夾路徑。")
    require(not value.startswith(("\\\\", "//")), "第一版只接受本機磁碟路徑，不接受 UNC 網路路徑。")
    path = Path(value).expanduser()
    if not path.is_absolute():
        root=Path(__file__).resolve().parents[1]
        candidate=(root/path).resolve()
        require((root/'examples').resolve() in candidate.parents and candidate.is_file(),
                "Relative paths are supported only for bundled examples; otherwise select an absolute local path.")
        path=candidate
    return path


def inspect_path(value):
    path = local_path(value)
    if path.is_dir():
        # Bounded enumeration: never recursively walk a cloud drive.
        entries = []
        with os.scandir(path) as stream:
            for item in stream:
                entries.append(dict(name=item.name, directory=item.is_dir()))
                if len(entries) == 12:
                    break
        return dict(kind="directory", path=str(path), entries=entries, usable_for_quality=False,
                    note="資料夾可列出；最多顯示 12 筆，尚未確認其中所有檔案可讀。",
                    next_step="若這是 pos_* 資料夾，請選 Raw data 模式並完成下方 S(q,t) 計算，再進行 q* 品質檢查。CSV 模式則需指定 time,q,S 檔案。")
    size = path.stat().st_size
    with path.open("rb") as stream:
        sample = stream.read(2048)
    preview = sample.decode("utf-8-sig", errors="replace").splitlines()[:6]
    first = preview[0].split(",") if preview else []
    sqt = set(first) == {"time", "q", "S"} and len(first) == 3
    return dict(kind="sqt_csv" if sqt else "other_file", path=str(path), size=size, preview=preview,
                usable_for_quality=sqt,
                next_step="請到 q* 品質檢查設定時間窗與取峰規則。" if sqt else "目前只能測試此檔可讀；品質檢查需要 time,q,S CSV。",
                note=("CSV 表頭符合 time,q,S；完整數值與網格將在品質檢查時驗證。" if sqt else
                      "前 2 KB 可讀。位置檔請改用 Raw data 模式選取其資料夾；此按鈕只測試可讀性。"))


def validate_settings(raw):
    require(isinstance(raw, dict), "品質設定必須是物件。")
    fields = ("time_start", "time_end", "q_min", "q_max", "min_prominence", "competitor_fraction", "stability_tolerance", "blocks")
    s = {key: number(raw.get(key), key) for key in fields}
    require(s["time_start"] < s["time_end"], "時間窗口起點須小於終點。")
    require(0 < s["q_min"] < s["q_max"], "q 搜尋範圍須滿足 0 < q_min < q_max。")
    require(0 < s["min_prominence"] <= 1, "相對 prominence 必須在 (0,1]。")
    require(0 < s["competitor_fraction"] <= 1, "競爭峰 prominence 比例必須在 (0,1]。")
    require(s["stability_tolerance"] >= 0, "峰位容許變化不可為負值。")
    require(s["blocks"].is_integer() and 2 <= s["blocks"] <= 10, "時間分段數須為 2 到 10 的整數。")
    s["blocks"] = int(s["blocks"])
    return s


def peak(q, values, settings):
    span = float(np.ptp(values))
    result = dict(q_peak=None, reasons=[], candidates=[])
    if span <= max(1., float(np.max(np.abs(values)))) * 1e-12:
        result["reasons"].append("曲線近乎平坦，無法辨識峰。")
        return result
    # The primary peak is the highest point in the declared range. A boundary
    # maximum must not be silently replaced by a smaller interior local maximum.
    primary = int(np.argmax(values))
    if primary in (0, len(q)-1):
        result["reasons"].append("最大值位於 q 搜尋邊界，峰位未解析。")
        return result
    indices, properties = find_peaks(values, prominence=0, plateau_size=True)
    if primary not in indices:
        result["reasons"].append("最高點未形成唯一的局部峰（可能有平台）。")
        return result
    j = int(np.where(indices == primary)[0][0])
    prominence = float(properties["prominences"][j])
    result.update(q_peak=float(q[primary]), relative_prominence=prominence/span)
    for index, prom in zip(indices, properties["prominences"]):
        result["candidates"].append(dict(q=float(q[index]), height=float(values[index]), relative_prominence=float(prom/span)))
    if properties["plateau_sizes"][j] > 1:
        result["reasons"].append("最高峰有平台，單一峰位不明確。")
    if prominence/span < settings["min_prominence"]:
        result["reasons"].append("主峰的相對 prominence 未達宣告門檻。")
    competitors = [i for i, p in zip(indices, properties["prominences"])
                   if i != primary and p >= settings["competitor_fraction"]*prominence]
    if competitors:
        result["reasons"].append("存在 prominence 接近的競爭峰，需確認峰的物理指派。")
    return result


def analyze_file(value, settings):
    path = local_path(value)
    require(path.is_file(), "品質檢查需要一個 time,q,S CSV 檔案；資料夾或原始位置檔尚不支援。")
    require(path.stat().st_size <= MAX_BYTES, "S(q,t) CSV 超過第一版 64 MiB 上限；請先輸出較小的結構因子表格。")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "檔案超過 64 MiB。")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    require(reader.fieldnames is not None and len(reader.fieldnames) == 3 and set(reader.fieldnames) == {"time", "q", "S"},
            "S(q,t) CSV 必須恰好具有 time,q,S 三個欄位。")
    frames = {}
    for line, row in enumerate(reader, 2):
        require(line <= 1_000_001, "CSV 超過第一版一百萬列上限。")
        require(None not in row, f"第 {line} 列欄位過多。")
        t, q, intensity = (number(row[key], f"第 {line} 列 {key}") for key in ("time", "q", "S"))
        require(q >= 0, f"第 {line} 列 q 不可為負。")
        # Validate all scalars, retain only the declared time window.
        if settings["time_start"] <= t <= settings["time_end"]:
            frame = frames.setdefault(t, {})
            require(q not in frame, f"重複的 (time,q)：({t},{q})。")
            frame[q] = intensity
    times = np.array(sorted(frames))
    require(len(times) >= settings["blocks"]*2, "時間窗內資料不足：每個分段至少需要兩個 frame。")
    require(np.allclose(np.diff(times), np.diff(times)[0], rtol=1e-6, atol=1e-12),
            "第一版要求等時間間隔，避免把不等間隔資料誤當等權時間平均。")
    require(times[0] <= settings["time_start"] and times[-1] >= settings["time_end"],
            "時間窗端點必須對應實際輸出時間；請調整為檔案中存在的 time。")
    q_all = np.array(sorted(frames[times[0]]))
    require(all(np.array_equal(np.array(sorted(frames[t])), q_all) for t in times), "各 frame 的 q 網格必須完全一致，不可缺點。")
    require(q_all[0] <= settings["q_min"] and q_all[-1] >= settings["q_max"], "檔案的 q 範圍未涵蓋指定搜尋範圍。")
    mask = (q_all >= settings["q_min"]) & (q_all <= settings["q_max"])
    q = q_all[mask]
    require(len(q) >= 5, "搜尋範圍內至少需要五個 q 網格點。")
    curves = np.array([[frames[t][float(v)] for v in q] for t in times])
    mean = curves.mean(axis=0)
    main = peak(q, mean, settings)
    blocks = []
    for indices in np.array_split(np.arange(len(times)), settings["blocks"]):
        average = curves[indices].mean(axis=0)
        blocks.append(dict(time_start=float(times[indices[0]]), time_end=float(times[indices[-1]]),
                           n_frames=len(indices), mean=average.tolist(), **peak(q, average, settings)))
    reasons = list(main["reasons"])
    valid_blocks = all(not b["reasons"] for b in blocks)
    spread = None
    if valid_blocks:
        peaks = [b["q_peak"] for b in blocks]
        spread = max(peaks)-min(peaks)
        # Compare the full-window peak too, to detect averaging-induced switching.
        if main["q_peak"] is not None:
            spread = max(peaks+[main["q_peak"]])-min(peaks+[main["q_peak"]])
        if spread > settings["stability_tolerance"]:
            reasons.append("全窗口與分段峰位的最大差距超過宣告容許值。")
    else:
        reasons.append("部分時間分段無法辨識唯一峰；目前不能確認峰位穩定性。")
    return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                status="ready" if not reasons else "review", reasons=reasons, q_peak=main["q_peak"],
                n_frames=len(times), q=q.tolist(), mean=mean.tolist(), candidates=main["candidates"],
                blocks=blocks, peak_spread=spread, q_grid_min_step=float(np.min(np.diff(q))),
                q_grid_max_step=float(np.max(np.diff(q))), actual_window=[float(times[0]), float(times[-1])],
                note="固定網格取峰，未平滑或插值。分段差距是敏感度診斷，並非平衡證明、標準誤或 seed 間變異。")
