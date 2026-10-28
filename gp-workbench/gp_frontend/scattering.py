"""Separate SANS/SAXS contrast projections of saved binary partial correlations.

Real effective bead amplitudes only. No instrument correction or experimental fit.
For q-dependent amplitudes, weights are evaluated at radial-bin mean q; this
approximation requires bin-width convergence, and is recorded in every output.
"""
import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from gp_eval.validation import require, number, nonempty

VERSION = "contrast-projection-1.0"
REFERENCE = "https://www.sasview.org/docs/user/qtgui/Calculators/sas_calculator_help.html"


def validate_profile(raw):
    require(isinstance(raw, dict), "散射設定格式錯誤。")
    p = {key: nonempty(raw.get(key), key) for key in
         ("technique", "amplitude_unit", "mapping_note", "sample_note", "mode")}
    require(p["technique"] in ("SANS", "SAXS"), "請指定 SANS 或 SAXS。")
    require(p["mode"] in ("constant", "table"), "散射權重須為常數或 q 相依表格。")
    if p["mode"] == "constant":
        p["b_a"], p["b_b"] = number(raw.get("b_a"), "A 有效散射振幅"), number(raw.get("b_b"), "B 有效散射振幅")
        require(max(abs(p["b_a"]), abs(p["b_b"])) > 0, "兩個散射振幅不能同時為零。")
    else:
        text = nonempty(raw.get("table"), "請提供 q,bA,bB 權重表。")
        require(len(text) < 100000, "權重表過大。")
        reader = csv.DictReader(io.StringIO(text))
        require(reader.fieldnames == ["q", "bA", "bB"], "權重表欄位依序須為 q,bA,bB。")
        rows = []
        for row in reader:
            require(None not in row, "權重表有多餘欄位。")
            rows.append([number(row[k], k) for k in reader.fieldnames])
        require(len(rows) >= 2, "q 相依權重表至少需要兩列。")
        values = np.asarray(rows)
        require(np.all(values[:, 0] >= 0) and np.all(np.diff(values[:, 0]) > 0), "權重表 q 須遞增、不重複且非負。")
        p["table"] = text
    return p


def amplitudes(q, p):
    if p["mode"] == "constant":
        return np.full(len(q), p["b_a"]), np.full(len(q), p["b_b"])
    rows = np.genfromtxt(io.StringIO(p["table"]), delimiter=",", names=True)
    require(rows["q"][0] <= q.min() and rows["q"][-1] >= q.max(), "散射權重表未涵蓋全部計算 q 範圍；不會外插。")
    return np.interp(q, rows["q"], rows["bA"]), np.interp(q, rows["q"], rows["bB"])


def project_values(partials, ca, ba, bb):
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        j = ba**2*partials[:, 0] + bb**2*partials[:, 1] + 2*ba*bb*partials[:, 2]
        denominator = ca*ba**2 + (1-ca)*bb**2
        require(np.isfinite(denominator).all() and np.all(denominator > 0), "散射權重為零或超出數值範圍。")
        require(np.isfinite(j).all() and np.all(j >= -1e-9*np.maximum(1, denominator)), "散射強度無效，請檢查部分相關項與權重。")
        j = np.maximum(j, 0)
        return j, j/denominator


def project_extraction(extraction, profiles, window, destination, progress=lambda text: None):
    start, end = number(window.get("start"), "對照時間起點"), number(window.get("end"), "對照時間終點")
    require(start < end, "對照時間窗起點須小於終點。")
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    curves = []
    try:
        for i, manifest in enumerate(extraction["results"]):
            progress(f"重新組合配方 {i+1}/5 的實驗對照曲線…")
            source = Path(manifest["partials_csv"])
            data = source.read_bytes()
            require(hashlib.sha256(data).hexdigest() == manifest["partials_sha256"], "部分相關項已被修改；請重新計算 raw data。")
            table = np.genfromtxt(io.StringIO(data.decode("utf-8")), delimiter=",", names=True)
            require(table.dtype.names == ("time", "q", "PAA", "PBB", "PAB"), "部分相關項欄位不符。")
            table = np.atleast_1d(table)
            table = table[(table["time"] >= start) & (table["time"] <= end)]
            times = np.unique(table["time"])
            require(len(times) >= 2 and times[0] == start and times[-1] == end, "對照時間窗端點須對應已保存 frames，至少兩個時間點。")
            q = np.asarray(manifest["summary"]["q"])
            require(len(table) == len(q)*len(times), "部分相關項網格不完整。")
            ca = manifest["summary"]["particle_fraction_a"]
            for p in profiles:
                ba, bb = amplitudes(q, p)
                path = root / f"recipe_{i+1}_{p['technique']}.csv"
                means, js = [], []
                with path.open("x", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["time", "q", "J_per_particle", "S_weighted"])
                    for t in times:
                        frame = table[table["time"] == t]
                        require(np.array_equal(frame["q"], q), "部分相關項 q 網格不一致。")
                        partials = np.column_stack([frame[k] for k in ("PAA", "PBB", "PAB")])
                        j, sw = project_values(partials, ca, ba, bb)
                        writer.writerows(zip(np.full(len(q), t), q, j, sw))
                        means.append(sw); js.append(j)
                curves.append(dict(label=f"配方 {i+1} · {p['technique']} · S_weighted",
                                   q=q.tolist(), mean=np.mean(means, axis=0).tolist(),
                                   mean_J=np.mean(js, axis=0).tolist(), blocks=[], q_peak=None,
                                   path=str(path), profile=p, recipe=i+1,
                                   source_partials_sha256=manifest["partials_sha256"]))
        result = dict(version=VERSION, extraction_id=extraction["id"], profiles=profiles,
                      window=dict(start=start, end=end), raw_settings=extraction["settings"],
                      curves=curves, reference=REFERENCE,
                      implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      formula="J=(bA² PAA+bB² PBB+2 bA bB PAB); S_weighted=J/(cA bA²+cB bB²)",
                      status="model_projection_only_not_experimentally_validated",
                      limitations=["Real effective bead amplitudes; no complex anomalous scattering or magnetic terms.",
                                   "J units are amplitude_unit squared per particle; not absolute experimental intensity.",
                                   "q-dependent amplitudes evaluated at radial-bin mean q; verify bin-width convergence.",
                                   "No background, resolution smearing, calibration fitting, experimental data import or score.",
                                   "Matching stage, temperature, solvent, swelling and bead mapping must be established.",
                                   "Composition q* used for GP remains unchanged."])
        (root/"comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return result
    except Exception as exc:
        (root/"failure.json").write_text(json.dumps(dict(error=str(exc)), ensure_ascii=False), encoding="utf-8")
        raise
