"""Independent prediction-task contracts; shared GP math does not mix tasks."""
from __future__ import annotations

import copy
from pathlib import Path

from gp_eval.validation import nonempty, number, require

KINDS = ("condition", "early")
LABELS = {"condition": "條件預測", "early": "早期預測"}
ROW_METADATA = {"task_kind", "time_unit", "time_origin", "input_window_start", "input_window_end"}


def interval(value, name):
    require(isinstance(value, list) and len(value) == 2, f"{name}: require [start, end]")
    start, end = [number(v, name) for v in value]
    require(start <= end, f"{name}: start must not exceed end")
    return [start, end]


def validate_task(task, definitions, specs):
    require(isinstance(task, dict), "prediction_task must be an object")
    task = copy.deepcopy(task)
    allowed = {"kind", "stage", "time_unit", "time_origin", "target_window", "observation_window"}
    require(not set(task)-allowed, f"unknown prediction_task fields: {set(task)-allowed}")
    kind = task.get("kind")
    require(kind in KINDS, "prediction_task.kind must be condition or early")
    for field in ("stage", "time_unit", "time_origin"):
        task[field] = nonempty(task.get(field), f"prediction_task.{field}")
    task["target_window"] = interval(task.get("target_window"), "target_window")
    if kind == "early":
        task["observation_window"] = interval(task.get("observation_window"), "observation_window")
        require(task["observation_window"][0] < task["observation_window"][1], "observation_window must have positive duration")
        require(task["observation_window"][1] < task["target_window"][0],
                "early observation window must end before target window starts")
    else:
        require("observation_window" not in task, "condition task cannot have an observation_window")
    require(isinstance(definitions, dict) and definitions, "feature_definitions required for task")
    for name, feature in definitions.items():
        require(name not in ROW_METADATA, f"task metadata cannot be an input: {name}")
        require(isinstance(feature, dict), f"feature {name}: definition required")
        nonempty(feature.get("description"), f"{name}.description")
        require(feature.get("available_at_prediction") is True, f"{name}: available_at_prediction must be true")
        source = feature.get("source")
        require(source in ("condition", "trajectory"), f"{name}: source must be condition or trajectory")
        if source == "condition":
            require("sample_time" not in feature and "source_window" not in feature,
                    f"{name}: condition feature cannot declare trajectory timing")
        else:
            require(kind == "early", f"condition task cannot contain trajectory feature: {name}")
            require(("sample_time" in feature) != ("source_window" in feature),
                    f"{name}: declare exactly one of sample_time or source_window")
            used = (interval(feature["source_window"], f"{name}.source_window") if "source_window" in feature
                    else [number(feature["sample_time"], f"{name}.sample_time")]*2)
            start, end = task["observation_window"]
            require(start <= used[0] <= used[1] <= end,
                    f"{name}: feature timing is outside observation window")
    for spec in specs:
        require(all(name in definitions for name in spec["inputs"]), "task feature definition missing")
        if kind == "early" and spec.get("kind", "gp") == "gp":
            require(any(definitions[name]["source"] == "trajectory" for name in spec["inputs"]),
                    "every early GP must use at least one trajectory feature; keep condition GPs in a condition run")
    return task


def expected_task(actual, expected):
    if expected is not None:
        require(expected in KINDS, "unknown requested prediction task")
        require(actual is not None and actual.get("kind") == expected,
                f"task mismatch: this entry point requires {expected}; legacy or other-task inputs are not accepted")


def task_directory(root, task):
    root = Path(root).resolve()
    return root / task["kind"] if task else root


def metadata(task):
    """Required row declarations, shared by training tables and new-query tables."""
    result = dict(task_kind=task["kind"])
    if task["kind"] == "early":
        result.update(time_unit=task["time_unit"], time_origin=task["time_origin"],
                      input_window_start=task["observation_window"][0],
                      input_window_end=task["observation_window"][1])
    return result


def validate_row(row, task, label):
    for key, expected in metadata(task).items():
        actual = row.get(key)
        if key in ("input_window_start", "input_window_end"):
            actual = number(actual, f"{label}.{key}")
        require(actual == expected, f"{label}: task metadata mismatch for {key}, expected {expected!r}")
    if task["kind"] == "condition":
        require(all(row.get(k) in (None, "") for k in ("input_window_start", "input_window_end")),
                f"{label}: condition row cannot contain an observation window")


def describe(task):
    if task is None:
        return "Legacy task unspecified; not automatically classified as condition or early."
    text = f"{LABELS[task['kind']]} / {task['kind']}；階段：{task['stage']}；target 時窗：{task['target_window']} {task['time_unit']}"
    if task["kind"] == "early":
        text += f"；input 觀察窗：{task['observation_window']}；時間原點：{task['time_origin']}"
    return text
