"""Binary composition structure factors on the full periodic reciprocal lattice.

No FFT assignment, minimum-image Debye approximation, or random directions.
The spherical average is over discrete reciprocal vectors; anisotropy is lost.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import re
from pathlib import Path

import numpy as np

from gp_eval.validation import number, nonempty, require
from .quality import local_path

VERSION = "binary-reciprocal-partials-2.0"
FORMULA = "|cB*rhoA(k)-cA*rhoB(k)|^2/N; rhoX=sum_X exp(i*k.r); cX=NX/N"
REFERENCE = "https://isaacs.sourceforge.io/manual/page26_ct.html"


class Cancelled(ValueError):
    pass


def check_cancel(cancel):
    if cancel():
        raise Cancelled("已取消；未完成的輸出不會送入品質檢查。")


def settings(raw):
    require(isinstance(raw, dict), "請填寫 raw data 計算設定。")
    s = {}
    for key in ("type_a", "type_b", "step_start", "step_end", "stride",
                "length_scale", "time_scale", "time_offset", "q_max", "dq"):
        s[key] = number(raw.get(key), key)
    for key in ("type_a", "type_b", "step_start", "step_end", "stride"):
        require(float(s[key]).is_integer() and abs(s[key]) < 2**53, f"{key} 必須是精確整數。")
        s[key] = int(s[key])
    require(s["type_a"] != s["type_b"], "A、B 的粒子種類編號不可相同。")
    require(s["step_start"] <= s["step_end"], "時間步起點不可大於終點。")
    require(1 <= s["stride"] <= 100000, "frame 取樣間隔須為 1–100000。")
    require(s["length_scale"] > 0 and s["time_scale"] > 0, "長度與時間換算係數須大於零。")
    require(s["q_max"] > 0 and s["dq"] > 0, "q 上限與分箱寬度須大於零。")
    for key in ("length_unit", "time_unit"):
        s[key] = nonempty(raw.get(key), key)
    s["normalization"] = raw.get("normalization")
    require(s["normalization"] in ("scc", "scc_normalized"), "請選擇 Scc 正規化方式。")
    require(raw.get("periodic") is True, "此計算器要求三方向週期邊界。")
    s["periodic"] = True
    return s


def header(line):
    fields = line.split()
    require(len(fields) == 5, "檔頭需為 step N Lx Ly Lz，共五欄。")
    try:
        step, n = int(fields[0]), int(fields[1])
        box = np.array(fields[2:], dtype=float)
    except (ValueError, OverflowError):
        raise ValueError("檔頭的時間步與粒子數須為整數，盒長須為數值。") from None
    require(abs(step) < 2**53 and 0 < n <= 1000000, "時間步或粒子總數超出支援範圍。")
    require(np.isfinite(box).all() and (box > 0).all(), "三個盒長須為正有限數。")
    return step, n, box


def read_frame(path, s):
    path = Path(path)
    require(path.stat().st_size <= 128*1024*1024, "單一位置檔超過 128 MiB。")
    # Bounded read also detects a file that grows after stat().
    with path.open("rb") as stream:
        data = stream.read(128*1024*1024 + 1)
    return parse_frame(data, s)


def parse_frame(data, s):
    """Parse local or remotely fetched bytes with identical scientific checks."""
    require(len(data) <= 128*1024*1024, "單一位置檔超過 128 MiB。")
    lines = data.decode("utf-8-sig").splitlines()
    require(bool(lines), "位置檔為空。")
    step, n, box = header(lines[0])
    rows = [line.split() for line in lines[1:] if line.strip()]
    require(len(rows) == n, f"宣告 {n} 個粒子，實際有 {len(rows)} 列。")
    require(all(len(row) == 4 for row in rows), "每個粒子需為 x y z type，共四欄。")
    values = np.asarray(rows, dtype=float)
    require(np.isfinite(values).all(), "粒子資料不可包含 NaN 或無限大。")
    types = values[:, 3]
    require(np.isin(types, [s["type_a"], s["type_b"]]).all(), "發現未指定的粒子種類；不會默默略過。")
    is_a = types == s["type_a"]
    na = int(is_a.sum())
    require(0 < na < n, "組成波動計算需要 A、B 兩種類型皆存在。")
    # Fractional coordinates retain translation/wrapping invariance.
    frac = np.remainder(values[:, :3], box) / box
    return dict(step=step, n=n, box=box, frac=frac, is_a=is_a,
                counts=[na, n-na], sha256=hashlib.sha256(data).hexdigest())


def inventory(folder, s, cancel=lambda: False):
    folder = local_path(folder)
    require(folder.is_dir(), "raw data 來源必須是包含 pos_數字 檔案的資料夾。")
    entries = []
    count = 0
    for p in folder.iterdir():
        check_cancel(cancel)
        if re.fullmatch(r"pos_\d+", p.name) and p.is_file():
            count += 1
            require(count <= 20000, "資料夾超過 20000 個位置檔，請縮小來源範圍。")
            with p.open("r", encoding="utf-8-sig") as stream:
                line = stream.readline(4096)
            step, n, box = header(line)
            if s["step_start"] <= step <= s["step_end"]:
                entries.append((step, p, n, box))
    require(bool(entries), "選定時間步範圍內找不到 pos_數字 檔案。")
    entries.sort(key=lambda row: row[0])
    require(len({row[0] for row in entries}) == len(entries), "存在重複檔頭時間步；請釐清來源。")
    selected = entries[::s["stride"]]
    if len(selected) > 1:
        steps = np.array([row[0] for row in selected], dtype=np.int64)
        require(np.all(np.diff(steps) == steps[1]-steps[0]), "選取的時間步不等間距；不可直接進行等權時間平均。")
    return selected


def reciprocal_grid(box, s):
    box = np.asarray(box) * s["length_scale"]
    require(np.isfinite(box).all() and (box > 0).all(), "換算後盒長無效。")
    extents_float = np.floor(s["q_max"] * box / (2*np.pi))
    require(np.isfinite(extents_float).all() and (extents_float <= 64).all(),
            "q 上限造成過大的倒空間網格（單軸超過 64）；請降低 q 上限或檢查單位。")
    extents = extents_float.astype(int)
    require(int(np.prod(2*extents+1)) <= 2200000, "倒空間網格過大。")
    modes = []
    # +/- pairs have identical intensities for real weights. Keep exactly one.
    for triple in itertools.product(*(range(-int(m), int(m)+1) for m in extents)):
        first = next((v for v in triple if v), 0)
        if first <= 0:
            continue
        q = np.linalg.norm(2*np.pi*np.array(triple)/box)
        if q <= s["q_max"] * (1+1e-12):
            modes.append(triple)
            require(len(modes) <= 20000, "超過 20000 個獨立 q 向量；請降低 q 上限。")
    require(bool(modes), "q 上限低於盒子允許的第一個非零波向量。")
    modes = np.asarray(modes, dtype=int)
    magnitudes = np.linalg.norm(2*np.pi*modes/box, axis=1)
    bin_values = np.floor(magnitudes / s["dq"])
    require(np.isfinite(bin_values).all() and (bin_values < 2**52).all(), "q 分箱寬度過小。")
    _, indices = np.unique(bin_values, return_inverse=True)
    counts = np.bincount(indices)
    q = np.bincount(indices, weights=magnitudes) / counts
    require(len(q) >= 5, "有效 q 分箱不足五個；請減小分箱寬度或增加 q 上限。")
    return dict(modes=modes, indices=indices, counts=counts, q=q,
                q_low=np.array([magnitudes[indices == i].min() for i in range(len(q))]),
                q_high=np.array([magnitudes[indices == i].max() for i in range(len(q))]))


def partial_intensities(frame, modes, cancel=lambda: False):
    """Columns |rhoA|²/N, |rhoB|²/N, Re(rhoA*rhoB*)/N."""
    n = frame["n"]
    output = []
    for start in range(0, len(modes), 128):
        check_cancel(cancel)
        block = modes[start:start+128]
        a, b = np.zeros(len(block), complex), np.zeros(len(block), complex)
        for particle in range(0, n, 4096):
            phase = (2*np.pi*frame["frac"][particle:particle+4096]) @ block.T
            waves = np.exp(1j*phase)
            mask = frame["is_a"][particle:particle+4096]
            a += waves[mask].sum(axis=0)
            b += waves[~mask].sum(axis=0)
        output.extend(np.column_stack((abs(a)**2/n, abs(b)**2/n, (a*b.conjugate()).real/n)))
    return np.asarray(output)


def composition(partials, ca, normalization):
    value = (1-ca)**2*partials[:, 0] + ca**2*partials[:, 1] - 2*ca*(1-ca)*partials[:, 2]
    # Only numerical cancellation can produce negative values for a valid basis.
    require(np.all(value >= -1e-10*np.maximum(1, partials[:, :2].sum(axis=1))), "部分結構因子不一致。")
    value = np.maximum(value, 0)
    return value/(ca*(1-ca)) if normalization == "scc_normalized" else value


def intensities(frame, modes, normalization, cancel=lambda: False):
    return composition(partial_intensities(frame, modes, cancel), frame["counts"][0]/frame["n"], normalization)


def plan(folder, s, cancel=lambda: False, source=None):
    selected = inventory(folder, s, cancel) if source is None else source.inventory(cancel)
    first = read_frame(selected[0][1], s) if source is None else source.read_frame(selected[0][1], s)
    grid = reciprocal_grid(first["box"], s)
    for _, path, n, box in selected:
        require(n == first["n"] and np.array_equal(box, first["box"]),
                f"{path.name} 的粒子數或盒長改變；第一版要求選定窗口內固定。")
    times = [row[0]*s["time_scale"] + s["time_offset"] for row in selected]
    require(np.isfinite(times).all() and (len(times) < 2 or np.all(np.diff(times) > 0)),
            "換算後時間無效或精度不足。")
    return selected, first, grid, dict(
        folder=str(local_path(folder)) if source is None else str(folder), frames=len(selected), first_step=selected[0][0],
        last_step=selected[-1][0], time_start=times[0], time_end=times[-1],
        particles=first["n"], counts=first["counts"], particle_fraction_a=first["counts"][0]/first["n"],
        box_raw=first["box"].tolist(), modes_half=len(grid["modes"]),
        q=grid["q"].tolist(), q_low=grid["q_low"].tolist(), q_high=grid["q_high"].tolist(),
        directions_full=(2*grid["counts"]).tolist(),
        estimated_particle_mode_pairs=int(len(selected)*first["n"]*len(grid["modes"])))


def extract(folder, s, output, cache, progress=lambda text: None, cancel=lambda: False, source=None):
    """Immutable run output + content-addressed per-frame curve cache."""
    selected, first, grid, summary = plan(folder, s, cancel, source)
    require(len(selected)*len(grid["q"]) <= 1000000,
            "預計輸出超過一百萬列；請縮小時間範圍或調整取樣間隔。")
    output, cache = Path(output), Path(cache)
    output.mkdir(parents=True, exist_ok=False)
    cache.mkdir(parents=True, exist_ok=True)
    sources, hits = [], 0
    config = json.dumps(dict(version=VERSION, settings=s), sort_keys=True).encode()
    try:
        with (output / "sqt.partial").open("x", encoding="utf-8", newline="") as stream, (output / "partials.partial").open("x", encoding="utf-8", newline="") as partial_stream:
            writer = csv.writer(stream)
            writer.writerow(["time", "q", "S"])
            partial_writer = csv.writer(partial_stream)
            partial_writer.writerow(["time", "q", "PAA", "PBB", "PAB"])
            for index, (step, path, _, _) in enumerate(selected):
                check_cancel(cancel)
                progress(f"{index+1}/{len(selected)} frames：{path.name}")
                frame = read_frame(path, s) if source is None else source.read_frame(path, s)
                require(frame["step"] == step and frame["n"] == first["n"] and
                        np.array_equal(frame["box"], first["box"]) and frame["counts"] == first["counts"],
                        f"{path.name} 的時間步、盒長或種類數量不一致／檔案在處理時改變。")
                key = hashlib.sha256(config + frame["sha256"].encode()).hexdigest()
                cached = cache / (key + ".npz")
                curve = None
                if "cached_partials" in frame:
                    partials = frame["cached_partials"]
                    curve = composition(partials, frame["counts"][0]/frame["n"], s["normalization"])
                    hits += 1
                elif cached.is_file():
                    try:
                        with np.load(cached, allow_pickle=False) as saved:
                            candidate = saved["partials"]
                            if (np.array_equal(saved["q"], grid["q"]) and candidate.shape == (len(grid["q"]), 3)
                                    and np.isfinite(candidate).all() and (candidate[:, :2] >= 0).all()
                                    and np.all(candidate[:, 2]**2 <= candidate[:, 0]*candidate[:, 1] + 1e-8)):
                                partials = candidate.copy()
                                curve = composition(partials, frame["counts"][0]/frame["n"], s["normalization"])
                                hits += 1
                    except (OSError, ValueError, KeyError, EOFError):
                        pass  # Damaged caches are recomputed.
                if curve is None:
                    values = partial_intensities(frame, grid["modes"], cancel)
                    partials = np.column_stack([np.bincount(grid["indices"], weights=values[:, col])/grid["counts"] for col in range(3)])
                    curve = composition(partials, frame["counts"][0]/frame["n"], s["normalization"])
                    require(np.isfinite(curve).all(), "結構因子計算產生非有限數值。")
                    temporary = cache / (key + ".partial.npz")
                    np.savez_compressed(temporary, q=grid["q"], partials=partials)
                    temporary.replace(cached)
                if source is not None:
                    source.remember(path, frame, partials, grid["q"])
                t = step*s["time_scale"] + s["time_offset"]
                writer.writerows((t, float(q), float(v)) for q, v in zip(grid["q"], curve))
                partial_writer.writerows((t, float(q), *map(float, values)) for q, values in zip(grid["q"], partials))
                sources.append(dict(path=str(path), step=step, sha256=frame["sha256"],
                                    **({"drive": source.provenance(path)} if source is not None else {})))
        check_cancel(cancel)
        partial = output / "sqt.partial"
        require(partial.stat().st_size <= 64*1024*1024 and len(selected)*len(grid["q"]) <= 1000000,
                "結果超過現有品質檢查器上限；請縮小時間範圍或調整取樣間隔。")
        destination = output / "sqt.csv"
        partial.replace(destination)
        partial_destination = output / "partials.csv"
        (output / "partials.partial").replace(partial_destination)
        metadata = dict(version=VERSION, formula=FORMULA, reference=REFERENCE, settings=s,
                        summary=summary, sources=sources, cache_hits=hits, csv=str(destination),
                        csv_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                        partials_csv=str(partial_destination),
                        partials_sha256=hashlib.sha256(partial_destination.read_bytes()).hexdigest(),
                        partials_definition="PAA=|rhoA|²/N; PBB=|rhoB|²/N; PAB=Re(rhoA*rhoB*)/N; radial mean per frame",
                        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        notes=["PBC in all axes; orthorhombic fixed box; all reciprocal modes through q_max.",
                               "Radial mean intensity; q coordinate is mean magnitude of populated bin; q=0 excluded.",
                               "Not experimental SAXS intensity; bonds not used; frame samples are not independent seeds."])
        if source is not None:
            metadata["source_mode"] = "drive"
            metadata["download_bytes_this_extraction"] = source.client.transferred - source.start_bytes
        (output / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata
    except Exception as exc:
        (output / "failure.json").write_text(json.dumps(dict(error=str(exc)), ensure_ascii=False), encoding="utf-8")
        raise
