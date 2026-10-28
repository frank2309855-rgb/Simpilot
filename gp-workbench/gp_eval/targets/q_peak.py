"""q* domain rules and derived length diagnostics.

Receives already-extracted scalar labels. Does not extract peaks from S(q,t).
Time averaging refers to S(q,t) before peak extraction, not averaging peak positions.
"""
import math
from statistics import fmean

from .base import GaussianScalarTarget
from ..validation import require


class QPeakTarget(GaussianScalarTarget):
    evaluator_id = "q_peak"
    diagnostic_fields = (
        dict(key="nonpositive_mass", label="P(q ≤ 0) 平均機率", format="percent"),
        dict(key="length_relative_error", label="特徵長度相對誤差", format="percent", missing="不可計算"),
        dict(key="invalid_length_count", label="非正預測平均值數", format="number"),
    )
    diagnostic_note = ("長度誤差來自 2π／預測平均 q 的代入值，不是預測長度的期望值。"
                       "若有非正的預測平均值，整體長度誤差顯示「不可計算」。")

    def draft_definition(self):
        target = super().draft_definition()
        target.update(name="q_peak", extraction_order="time_average_then_peak")
        return target

    def validate_definition(self, target, protocol):
        super().validate_definition(target, protocol)
        order = target.get("extraction_order")
        if protocol["schema_version"] == "1.0" and "extraction_order" not in target:
            return  # Compatibility only; never invent an extraction order for old data.
        allowed = {"time_average_then_peak"}
        if protocol["data_kind"] == "synthetic_demo":
            allowed.add("synthetic_scalar")
        require(isinstance(order, str) and order in allowed,
                "q_peak target.extraction_order must be time_average_then_peak "
                "(synthetic_scalar is allowed only for synthetic_demo)")

    def validate_observation(self, value, observation_id):
        require(value > 0, f"{observation_id}: q_peak truth must be positive")

    def observation_metrics(self, y, mu, sd):
        relative_error = abs(y / mu - 1) if mu > 0 else None
        if relative_error is not None:
            require(math.isfinite(relative_error), "derived length error overflow")
        return dict(nonpositive_mass=0.5 * math.erfc(mu / sd / math.sqrt(2)),
                    length_relative_error=relative_error)

    def aggregate(self, records):
        invalid = sum(row["length_relative_error"] is None for row in records)
        return dict(nonpositive_mass=fmean(row["nonpositive_mass"] for row in records),
                    invalid_length_count=invalid,
                    length_relative_error=None if invalid else fmean(row["length_relative_error"] for row in records))

    def summarize(self, ratio_rows):
        invalid = sum(row["invalid_length_count"] for row in ratio_rows)
        return dict(nonpositive_mass=fmean(row["nonpositive_mass"] for row in ratio_rows),
                    invalid_length_count=invalid,
                    length_relative_error=None if invalid else fmean(row["length_relative_error"] for row in ratio_rows))

    def warnings(self, protocol, records):
        messages = ["特徵長度誤差使用 2π／預測平均 q 的代入值；沒有推定長度的預測分布或期望值。"]
        if any(row["pred_mean"] <= 0 for row in records):
            messages.append("部分預測平均值非正，對應長度誤差無定義；彙總時不會靜默捨棄這些樣本。")
        if "extraction_order" not in protocol["target"]:
            messages.append("舊版 q* 設定未結構化記錄取峰順序；保留原 extraction_rule，不推定已先做時間平均。")
        else:
            messages.append("取峰順序與時間窗口依設定聲明；評估器接收已提取的 q*，未讀取 S(q,t) 核對提取過程。")
        return messages

    def describe(self, target):
        result = super().describe(target)
        order = target.get("extraction_order", "legacy_unspecified")
        result.update(axis_label="q*", extraction_order=order,
                      extraction_order_label={
                          "time_average_then_peak": "先對 S(q,t) 做時間平均，再取峰",
                          "synthetic_scalar": "合成純量，未從 S(q,t) 取峰",
                          "legacy_unspecified": "舊版設定：取峰順序未結構化記錄",
                      }[order])
        return result
