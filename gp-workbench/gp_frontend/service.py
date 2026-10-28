"""Frozen quality reviews -> separate condition runs using the existing trainer."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

from gp_eval.validation import nonempty, number, require
from gp_model.workflow import normalize_config, train_experiment
from .quality import VERSION, analyze_file, validate_settings
from . import raw as raw_data
from . import m_quality, low_q_quality, run_records
from .kernel_choices import validate_choices, model_specs, VERSION as KERNEL_VERSION
from .path_probe import friendly_error
from .scattering import validate_profile, project_extraction
from .drive_auth import DriveAuth
from . import drive


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def validate_project(raw):
    require(isinstance(raw, dict), "專案設定格式錯誤。")
    project = {key: nonempty(raw.get(key), key) for key in
               ("label", "ratio_definition", "q_unit", "time_unit", "time_origin", "structure_definition", "conditions_note")}
    require(raw.get("data_kind") in ("real", "synthetic_demo"), "請指定真實資料或合成示範。")
    project["data_kind"] = raw["data_kind"]
    project["kernel_choices"] = validate_choices(raw.get("kernel_choices", ["linear"]))
    # Old scalar projects retain their declared encoding; never invent A:B.
    mode = raw.get("ratio_encoding", "legacy_scalar")
    require(mode in ("fraction", "quotient", "legacy_scalar"), "未知比例換算方式。")
    project["ratio_encoding"] = mode
    project["source_mode"] = raw.get("source_mode", "csv")
    require(project["source_mode"] in ("csv", "raw", "drive"), "未知資料來源模式。")
    if project["source_mode"] in ("raw", "drive"):
        project["raw_settings"] = raw_data.settings(raw.get("raw_settings"))
        project["extraction_id"] = nonempty(raw.get("extraction_id"), "請先完成 raw data 計算。")
        require(project["q_unit"] == project["raw_settings"]["length_unit"] + "^-1" and
                project["time_unit"] == project["raw_settings"]["time_unit"],
                "研究單位與 raw 換算設定不一致；請按「套用單位與定義」。")
    project["target_kind"] = raw.get("target_kind", "q_peak")
    require(project["target_kind"] in ("q_peak", "composition_strength", "low_q_shell_mean"), "未知預測目標。")
    validator = {"composition_strength": m_quality.validate_settings, "low_q_shell_mean": low_q_quality.validate_settings}.get(project["target_kind"], validate_settings)
    project["settings"] = validator(raw.get("settings"))
    rows = raw.get("rows")
    require(isinstance(rows, list) and len(rows) == 5, "本次試跑要求五個比例、各一個 seed，請完整填入五列。")
    project["rows"] = []
    for i, row in enumerate(rows):
        require(isinstance(row, dict), f"第 {i+1} 列格式錯誤。")
        if mode == "legacy_scalar":
            require(row.get("amount_a") is None and row.get("amount_b") is None,
                    "舊版單值模式不可同時提供 A、B；請明確選擇換算方式。")
            ratio = number(row.get("ratio"), f"第 {i+1} 列 ratio")
            amounts = {}
        else:
            a = number(row.get("amount_a"), f"第 {i+1} 列 A")
            b = number(row.get("amount_b"), f"第 {i+1} 列 B")
            require(a >= 0 and b >= 0 and max(a, b) > 0, "A、B 需為非負數，且不可同時為零。")
            if mode == "fraction":
                scale = max(a, b)
                ratio = (a / scale) / (a / scale + b / scale)
            else:
                require(b > 0, "A/B 換算要求 B > 0；純 A 可改用 A/(A+B)。")
                ratio = a / b
            require(math.isfinite(ratio), "比例換算超出數值範圍。")
            if row.get("ratio") is not None:
                declared = number(row["ratio"], "前端 ratio 預覽")
                require(math.isclose(declared, ratio, rel_tol=1e-12, abs_tol=0), "ratio 預覽與 A:B 不一致，請重新整理比例設定。")
            amounts = dict(amount_a=a, amount_b=b)
        project["rows"].append(dict(observation_id=f"ratio_{i+1:02}",
                                    label=nonempty(row.get("label"), f"第 {i+1} 列配方名稱"),
                                    ratio=ratio, **amounts,
                                    seed_id=nonempty(row.get("seed_id"), f"第 {i+1} 列 seed"),
                                    path=nonempty(row.get("path"), f"第 {i+1} 列 S(q,t) 路徑")))
    require(len({r["ratio"] for r in project["rows"]}) == 5, "五個 ratio 必須互不相同。")
    return project


def build_config(project):
    s = project["settings"]
    window = [s["time_start"], s["time_end"]]
    config = dict(gp_config_version="1.1", dataset_label=project["label"], data_kind=project["data_kind"],
        target=dict(evaluator="q_peak", name="q_peak", units=project["q_unit"],
            observation_time=f"{window} {project['time_unit']}",
            extraction_rule=("Equal-weight time average of imported S(q,t), then highest identifiable interior grid peak. "
                             "No smoothing/interpolation. Quality settings: " + json.dumps(s, sort_keys=True) +
                             "; S definition: " + project["structure_definition"] +
                             ("; computed raw definition: " + raw_data.FORMULA + "; settings: " +
                              json.dumps(project["raw_settings"], sort_keys=True)
                              if project.get("source_mode") in ("raw", "drive") else "")),
            estimand="individual_run", distribution="gaussian_physical_scale", predictive_sd="observed_target",
            extraction_order="time_average_then_peak", column="q_peak"),
        feature_definitions=dict(ratio=dict(available_at_prediction=True, source="condition",
            description=project["ratio_definition"] + "; numerical encoding: " +
                {"fraction":"A/(A+B)", "quotient":"A/B", "legacy_scalar":"legacy declared scalar"}[project.get("ratio_encoding", "legacy_scalar")])),
        models=model_specs(project.get("kernel_choices", ["linear"])),
        baseline_inputs=["ratio"], training=dict(random_state=20261020, n_restarts_optimizer=2),
        selection_context="exploratory",
        practical_thresholds=dict(mae_improvement=None, crps_improvement=None, acceptable_mae=None),
        prediction_task=dict(kind="condition", stage="stage1", time_unit=project["time_unit"],
                             time_origin=project["time_origin"], target_window=window))
    if project.get("target_kind") == "composition_strength":
        config["target"] = dict(evaluator="composition_strength", name="M", units="dimensionless", column="M",
            observation_time=f"{window} {project['time_unit']}",
            extraction_rule="Mean over time of normalized Scc, then sum(n_b*(S_b-1))/sum(n_b), q=0 excluded. No peak rules. " +
                            json.dumps(s, sort_keys=True) + "; q unit: " + project["q_unit"] + "; S definition: " + project["structure_definition"],
            estimand="individual_run", distribution="gaussian_physical_scale", predictive_sd="observed_target",
            extraction_order="time_average_then_mode_weighted_excess")
    if project.get("target_kind") == "low_q_shell_mean":
        config["target"] = dict(evaluator="low_q_shell_mean", name="low_q_mean", units="dimensionless", column="low_q_mean",
            observation_time=f"{window} {project['time_unit']}",
            extraction_rule="Time mean of |c2*rho1-c1*rho2|^2/(N*c1*c2), then equal mean of complete exact shells in fixed inclusive q band; q=0 excluded; no subtraction. Version " + low_q_quality.VERSION + "; " + json.dumps(s,sort_keys=True) + "; q unit: " + project["q_unit"] + "; S definition: " + project["structure_definition"],
            estimand="individual_run",distribution="gaussian_physical_scale",predictive_sd="observed_target",
            extraction_order="time_average_then_equal_shell_mean")
    return normalize_config(config)


class Workbench:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.analyses = {}
        self.jobs = {}
        self.extractions = {}
        self.cancel_flags = {}
        self.drive_auth = DriveAuth()
        self.drive_plans = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gp-workbench")

    def start(self, kind, payload):
        require(kind in ("analyze", "train", "preview_raw", "extract_raw", "choose_folder", "project_scattering"), "未知工作。")
        # Validate immediately, before enqueueing a costly task.
        if kind == "analyze":
            payload = validate_project(payload)
            if payload["source_mode"] in ("raw", "drive"):
                with self.lock:
                    extraction = copy.deepcopy(self.extractions.get(payload["extraction_id"]))
                require(extraction is not None, "raw 計算紀錄不存在；請重新計算（可使用內容快取）。")
                require(extraction["settings"] == payload["raw_settings"] and
                        extraction["folders"] == [r["path"] for r in payload["rows"]] and
                        extraction.get("source_mode", "raw") == payload["source_mode"],
                        "raw 路徑或計算設定已變更，請重新計算。")
                payload["raw_extraction"] = extraction
        elif kind in ("preview_raw", "extract_raw"):
            require(isinstance(payload.get("folders"), list) and len(payload["folders"]) == 5,
                    "請填入五個配方的 raw data 資料夾。")
            original = payload
            payload = dict(settings=raw_data.settings(payload.get("settings")),
                           folders=[nonempty(v, "raw 資料夾") for v in payload["folders"]])
            payload["source_mode"] = original.get("source_mode", "raw")
            require(payload["source_mode"] in ("raw", "drive"), "未知 raw 資料來源模式。")
            if payload["source_mode"] == "drive":
                for folder in payload["folders"]:
                    drive.folder_id(folder)
                require(len({drive.folder_id(f) for f in payload["folders"]}) == 5, "五個配方不能使用同一個 Drive 資料夾。")
                require(self.drive_auth.status()["connected"], "請先完成 Google Drive 登入。")
                payload["drive_options"] = drive.options(original.get("drive_options"))
                if kind == "extract_raw":
                    with self.lock:
                        plan = copy.deepcopy(self.drive_plans.get(original.get("plan_id")))
                    require(plan is not None and all(plan[k] == payload[k] for k in payload),
                            "請先預覽這次 Drive 設定及傳輸量，再按計算。")
                    payload["plan_id"] = original["plan_id"]
        elif kind == "project_scattering":
            with self.lock:
                extraction = copy.deepcopy(self.extractions.get(payload.get("extraction_id")))
            require(extraction is not None, "請先完成 raw data 計算，取得部分相關項。")
            profiles = payload.get("profiles")
            require(isinstance(profiles, list) and 1 <= len(profiles) <= 2, "請啟用一至兩組 SANS／SAXS 對照設定。")
            profiles = [validate_profile(p) for p in profiles]
            require(len({p["technique"] for p in profiles}) == len(profiles), "散射技術不可重複。")
            require(isinstance(payload.get("window"), dict), "請指定對照時間窗。")
            payload = dict(extraction=extraction, profiles=profiles, window=payload["window"])
        elif kind == "choose_folder":
            payload = {}
        else:
            require(payload.get("reviewed") is True, "請先確認已檢查五張曲線與診斷。")
            nonempty(payload.get("review_note"), "請記錄這次品質判讀與門檻依據")
            with self.lock:
                analysis = self.analyses.get(payload.get("analysis_id"))
            require(analysis is not None, "檢查結果已失效，請重新檢查。")
            require(analysis["ready"], "五個比例尚未全部通過篩查；請先處理標籤問題，不會自動刪除配方。")
            choices = validate_choices(payload.get("kernel_choices", analysis["project"].get("kernel_choices", ["linear"])))
            payload = dict(analysis=copy.deepcopy(analysis), review_note=payload["review_note"], kernel_choices=choices)
        with self.lock:
            require(not any(job["status"] in ("queued", "running") for job in self.jobs.values()), "已有工作執行中，請等待完成。")
            job_id = uuid.uuid4().hex[:12]
            self.jobs[job_id] = dict(id=job_id, kind=kind, status="queued", progress="等待開始")
            self.cancel_flags[job_id] = threading.Event()
        self.pool.submit(self._worker, job_id, kind, payload)
        return dict(job_id=job_id)

    def job(self, job_id):
        with self.lock:
            require(job_id in self.jobs, "工作不存在。")
            return copy.deepcopy(self.jobs[job_id])

    def cancel(self, job_id):
        with self.lock:
            require(job_id in self.jobs and self.jobs[job_id]["kind"] in ("preview_raw", "extract_raw"),
                    "此工作不支援取消。")
            self.cancel_flags[job_id].set()
        return dict(message="已要求取消；會在目前檔案讀取／計算區塊結束後停止。")

    def _update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)

    def _worker(self, job_id, kind, payload):
        self._update(job_id, status="running")
        try:
            if kind in ("preview_raw", "extract_raw"):
                result = self._raw(job_id, kind, payload)
            elif kind == "choose_folder":
                from .folder_picker import choose
                result = dict(path=choose())
            elif kind == "project_scattering":
                result = project_extraction(payload["extraction"], payload["profiles"], payload["window"],
                    self.root / "scattering_runs" / job_id,
                    progress=lambda text: self._update(job_id, progress=text))
            else:
                result = self._analyze(job_id, payload) if kind == "analyze" else self._train(job_id, payload)
            self._update(job_id, status="complete", progress="完成", result=result)
        except Exception as exc:
            self._update(job_id, status="failed", progress="工作停止", error=friendly_error(exc))

    def _raw(self, job_id, kind, payload):
        results = []
        cancel = self.cancel_flags[job_id].is_set
        remote = payload.get("source_mode") == "drive"
        client = None
        records = []
        if remote:
            opts = payload["drive_options"]
            drive.disk_check(self.root, opts)
            client = drive.Client(self.drive_auth, opts["max_download_mib"]*drive.MIB, cancel)
            if kind == "extract_raw":
                with self.lock:
                    records = copy.deepcopy(self.drive_plans[payload["plan_id"]]["records"])
                drive.disk_check(self.root, opts, sum(r["summary"]["estimated_output_and_cache_bytes"] for r in records))
        for i, folder in enumerate(payload["folders"]):
            raw_data.check_cancel(cancel)
            self._update(job_id, progress=f"配方 {i+1}/5：讀取檔頭與規劃 q 網格…")
            if kind == "preview_raw":
                if remote:
                    record = drive.preview(client, folder, payload["settings"], self.root / "drive_cache", opts,
                        progress=lambda text, i=i: self._update(job_id, progress=f"配方 {i+1}/5 · {text}"))
                    source = drive.Source(client, record, payload["settings"], self.root / "drive_cache", opts)
                    record["summary"]["remaining_raw_bytes"] = source.remaining_bytes()
                    records.append(record)
                    result = record["summary"]
                else:
                    result = raw_data.plan(folder, payload["settings"], cancel)[3]
            else:
                source = drive.Source(client, records[i], payload["settings"], self.root / "drive_cache", opts) if remote else None
                result = raw_data.extract(folder, payload["settings"],
                    self.root / "raw_runs" / job_id / f"recipe_{i+1}",
                    self.root / "raw_cache",
                    progress=lambda text, i=i: self._update(job_id, progress=f"配方 {i+1}/5 · {text}"),
                    cancel=cancel, source=source)
            results.append(result)
        result = dict(id=job_id, **payload, results=results)
        if remote:
            result["transfer_bytes"] = client.transferred
            if kind == "preview_raw":
                remaining = sum(r["summary"]["remaining_raw_bytes"] for r in records)
                estimate = sum(r["summary"]["estimated_output_and_cache_bytes"] for r in records)
                # Metadata requests also count toward the enforced transfer ceiling.
                require(remaining + 2*client.transferred + 65536 <= opts["max_download_mib"]*drive.MIB,
                        "選定 frame 加預留清單流量超過傳輸上限；請縮小窗口／增加 stride，或明確提高上限後重新預覽。")
                drive.disk_check(self.root, opts, estimate)
                result["remaining_raw_bytes"] = remaining
                result["estimated_output_and_cache_bytes"] = estimate
                with self.lock:
                    if len(self.drive_plans) >= 10:
                        self.drive_plans.pop(next(iter(self.drive_plans)))
                    self.drive_plans[job_id] = dict(**payload, records=records)
        if kind == "extract_raw":
            save_json(self.root / "raw_runs" / job_id / "extraction.json", result)
            with self.lock:
                if len(self.extractions) >= 10:
                    self.extractions.pop(next(iter(self.extractions)))
                self.extractions[job_id] = copy.deepcopy(result)
        return result

    def _analyze(self, job_id, project):
        results = []
        for i, row in enumerate(project["rows"]):
            self._update(job_id, progress=f"檢查 {i+1}/5：{row['label']}")
            try:
                source = row["path"]
                metadata = None
                if project.get("source_mode") in ("raw", "drive"):
                    metadata = project["raw_extraction"]["results"][i]
                    source = metadata["csv"]
                if project.get("target_kind") in ("composition_strength", "low_q_shell_mean"):
                    extractor = low_q_quality if project["target_kind"] == "low_q_shell_mean" else m_quality
                    result = extractor.analyze_file(source, project["settings"], metadata,
                                                   project["q_unit"], project["time_unit"])
                else:
                    result = analyze_file(source, project["settings"])
                if metadata:
                    require(result["sha256"] == metadata["csv_sha256"],
                            "產生的 S(q,t) 已被修改，請重新執行 raw 計算。")
                    result["raw_manifest"] = metadata
            except (ValueError, OSError, UnicodeError) as exc:
                result = dict(path=row["path"], status="error", q_peak=None, reasons=[str(exc)])
            results.append({**row, **result})
        # The same trajectory may not masquerade as distinct formulations.
        hashes = [r.get("sha256") for r in results if r.get("sha256")]
        duplicate_hashes = {h for h in hashes if hashes.count(h) > 1}
        for result in results:
            if result.get("sha256") in duplicate_hashes:
                result["status"] = "review"
                result["reasons"].append("不同配方使用了完全相同的 S(q,t) 內容，請確認資料對應。")
        if project.get("target_kind") == "low_q_shell_mean":
            low_q_quality.check_comparable(results)
        analysis = dict(id=job_id, project=project, results=results,
                        ready=all(r["status"] == "ready" for r in results), quality_version={"composition_strength": m_quality.VERSION, "low_q_shell_mean": low_q_quality.VERSION}.get(project.get("target_kind"), VERSION),
                        limitation="Screening only, not an equilibrium test or uncertainty estimate. Raw provenance is recorded when source_mode=raw.")
        folder = self.root / "web_reviews" / job_id
        folder.mkdir(parents=True, exist_ok=False)
        analysis["review_path"] = str(folder / "quality_review.json")
        save_json(folder / "quality_review.json", analysis)
        with self.lock:
            # Keep bounded in-memory data, while complete reviews remain on disk.
            if len(self.analyses) >= 10:
                self.analyses.pop(next(iter(self.analyses)))
            self.analyses[job_id] = copy.deepcopy(analysis)
        return analysis

    def _train(self, job_id, payload):
        analysis = payload["analysis"]
        project = copy.deepcopy(analysis["project"])
        project["kernel_choices"] = validate_choices(payload.get("kernel_choices", project.get("kernel_choices", ["linear"])))
        config = build_config(project)
        # Use frozen extracted labels, never silently re-read edited CSV files.
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + job_id[:6]
        run = self.root / "web_runs" / run_id
        run.mkdir(parents=True, exist_ok=False)
        column = config["target"]["column"]
        value_key = {"composition_strength": "m_value", "low_q_shell_mean": "low_q_value"}.get(project.get("target_kind"), "q_peak")
        rows = [dict(observation_id=r["observation_id"], ratio=r["ratio"], seed_id=r["seed_id"],
                     target_n=1, **{column:r[value_key]}, task_kind="condition",
                     **{key:r[key] for key in ("amount_a", "amount_b") if key in r}) for r in analysis["results"]]
        with (run / "training_data.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        save_json(run / "config.json", config)
        audit = dict(analysis=analysis, human_review=payload["review_note"],
                     kernel_note="Selected signal kernels with shared training-only scaling, signal amplitude and WhiteKernel noise. Linear sigma_0=1 fixed; Matern nu fixed; remaining declared parameters optimized per training fold.",
                     kernel_selection=dict(version=KERNEL_VERSION, choices=project["kernel_choices"], models=config["models"]),
                     source_mode="Frozen reviewed targets; source CSV SHA256 records the analyzed content.",
                     implementation_sha256={str(p.relative_to(Path(__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in sorted(Path(__file__).parent.rglob("*"))
                                            if p.suffix in (".py", ".html", ".js")})
        save_json(run / "quality_review.json", audit)
        try:
            report = train_experiment(run / "training_data.csv", run / "config.json", run,
                         expected_kind="condition", progress=lambda text: self._update(job_id, progress=text))
            result = json.loads((report.parent / "results.json").read_text(encoding="utf-8"))
            summary = dict(run_id=run_id, label=project["label"], data_kind=project["data_kind"],
                           target_kind=project.get("target_kind", "q_peak"), kernel_choices=project["kernel_choices"],
                           report_url=f"/runs/{run_id}/condition/evaluation/report.html",
                           folder=str(run), summary=result["summary"], warnings=result["warnings"],
                           quality_review=str(run / "quality_review.json"))
            save_json(run / "workbench_result.json", summary)
            return summary
        except Exception as exc:
            save_json(run / "failure.json", dict(error=str(exc)))
            raise

    def preview_run_deletion(self,run_id):
        with self.lock:
            require(not any(j['status'] in ('queued','running') for j in self.jobs.values()),'請等目前工作完成後再管理執行紀錄。')
            return run_records.describe(self.root,run_id)

    def delete_run(self,payload):
        with self.lock:
            require(not any(j['status'] in ('queued','running') for j in self.jobs.values()),'請等目前工作完成後再刪除執行紀錄。')
            result=run_records.delete(self.root,payload.get('run_id'),payload.get('fingerprint'),payload.get('confirmed'))
            for key,job in list(self.jobs.items()):
                if job.get('result',{}).get('run_id')==result['run_id']:
                    self.jobs.pop(key,None);self.cancel_flags.pop(key,None)
            return result

    def history(self):
        output = []
        for path in sorted((self.root / "web_runs").glob("*/workbench_result.json"), reverse=True):
            data = json.loads(path.read_text(encoding="utf-8"))
            output.append({**{k: data[k] for k in ("run_id", "label", "data_kind", "report_url", "folder")},
                           "target_kind":data.get("target_kind", "q_peak"), "kernel_choices":data.get("kernel_choices", ["linear"]),
                           "run_id":path.parent.name, "folder":str(path.parent),
                           "report_url":f"/runs/{path.parent.name}/condition/evaluation/report.html"})
        return output

    def demo(self):
        folder = self.root / "web_examples" / "five_ratios"
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        for i, ratio in enumerate((.1, .3, .5, .7, .9)):
            path = folder / f"ratio_{i+1}.csv"
            if not path.exists():
                with path.open("x", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["time", "q", "S"])
                    for t in range(12):
                        center = .22 + .18*ratio + .0015*np.sin(t+i) + .002*np.cos(i)
                        for q in np.linspace(.05, .6, 111):
                            writer.writerow([t, round(float(q), 8), float(.15+np.exp(-.5*((q-center)/.035)**2))])
            rows.append(dict(label=f"示範配方 {i+1}", amount_a=(i*2+1), amount_b=(9-i*2),
                             ratio=ratio, seed_id="demo_seed1", path=str(path)))
        return dict(label="五比例 Linear GP｜合成流程驗證", data_kind="synthetic_demo",
                    ratio_encoding="fraction",
                    ratio_definition="Synthetic fraction x; not a physical HEA/PDMS definition.",
                    q_unit="demo_length^-1", time_unit="demo_time", time_origin="synthetic t=0",
                    structure_definition="Synthetic Gaussian-shaped S(q,t), not computed from MD.",
                    conditions_note="Synthetic example only; no physical inference.", rows=rows,
                    settings=dict(time_start=0, time_end=11, q_min=.05, q_max=.6,
                                  min_prominence=.15, competitor_fraction=.9, stability_tolerance=.02, blocks=3))
