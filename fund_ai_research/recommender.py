from typing import Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .analytics import holding_scenarios
from .models import FundMetrics, Recommendation


def _normalise(series: pd.Series, inverse: bool = False) -> pd.Series:
    if series.nunique() <= 1:
        values = pd.Series(0.5, index=series.index)
    else:
        values = (series - series.min()) / (series.max() - series.min())
    return 1 - values if inverse else values


def _format_range(values: Tuple[float, float, float]) -> str:
    low, mid, high = values
    return f"{low:+.1%} / {mid:+.1%} / {high:+.1%}"


def build_personalized_recommendations(
    metrics: Sequence[FundMetrics],
    aggression: int,
    max_drawdown: float,
    horizon_days: int,
    commission_bps: float,
    slippage_bps: float,
    annual_fee_rate: float,
) -> Tuple[List[Recommendation], dict]:
    if not metrics:
        return [], {"core_weight": 0, "tactical_weight": 0, "cash_weight": 100, "message": "没有可用基金"}
    frame = pd.DataFrame([m.as_dict() for m in metrics])
    frame["drawdown_abs"] = frame["max_drawdown"].abs()
    frame["core_score"] = (
        _normalise(frame["annualized_return"]) * 0.35
        + _normalise(frame["drawdown_abs"], inverse=True) * 0.35
        + _normalise(frame["annualized_volatility"], inverse=True) * 0.20
        + frame["quality_score"] * 0.10
    )
    frame["tactical_score"] = (
        _normalise(frame["momentum_60d"]) * 0.40
        + _normalise(frame["annualized_return"]) * 0.25
        + _normalise(frame["drawdown_abs"], inverse=True) * 0.15
        + frame["quality_score"] * 0.20
    )
    core_weight = max(10, min(90, round(85 - aggression * 0.55)))
    tactical_weight = max(0, min(80, round(10 + aggression * 0.55)))
    if core_weight + tactical_weight > 100:
        tactical_weight = 100 - core_weight
    cash_weight = 100 - core_weight - tactical_weight
    ranked_core = frame.sort_values(["core_score", "quality_score"], ascending=False)
    ranked_tactical = frame.sort_values(["tactical_score", "quality_score"], ascending=False)
    core = ranked_core.iloc[0]
    tactical = ranked_tactical.iloc[0]
    if tactical["code"] == core["code"] and len(ranked_tactical) > 1:
        tactical = ranked_tactical.iloc[1]
    recommendations: List[Recommendation] = []
    for role, row, weight in (("核心仓", core, core_weight), ("战术仓", tactical, tactical_weight)):
        if weight <= 0:
            continue
        metric = next(m for m in metrics if m.code == row["code"])
        scenario = holding_scenarios(metric, horizon_days, commission_bps, slippage_bps, annual_fee_rate)
        flags: List[str] = []
        if abs(metric.max_drawdown) > max_drawdown / 100:
            flags.append(f"历史最大回撤 {metric.max_drawdown:.1%} 超过用户阈值")
        if metric.quality_score < 0.9:
            flags.append("数据质量未达到 90%")
        if role == "战术仓" and aggression >= 70:
            flags.append("激进参数较高，需重点关注盘中波动与滑点")
        action = "可继续研究" if not flags else "等待验证"
        if role == "战术仓" and abs(metric.max_drawdown) > max_drawdown / 100 * 1.5:
            action = "不碰"
        reason = (
            f"{role}候选得分 {row['core_score' if role == '核心仓' else 'tactical_score']:.2f}；"
            f"年化历史收益 {metric.annualized_return:+.1%}，60日动量 {metric.momentum_60d:+.1%}，"
            f"最大回撤 {metric.max_drawdown:.1%}。"
        )
        recommendations.append(
            Recommendation(
                role=role,
                code=metric.code,
                name=metric.name,
                target_weight=float(weight),
                action=action,
                net_return_range=_format_range(scenario),
                max_drawdown=metric.max_drawdown,
                reason=reason,
                evidence=[
                    f"历史区间 {metric.as_of.isoformat()} 截止",
                    f"数据质量 {metric.quality_score:.0%}",
                    f"净收益情景按 {horizon_days} 个交易日、手续费/滑点参数计算",
                ],
                risk_flags=flags or ["仍需人工核对基金合同、公告和最新持仓"],
            )
        )
    profile = {
        "core_weight": core_weight,
        "tactical_weight": tactical_weight,
        "cash_weight": cash_weight,
        "aggression": aggression,
        "max_drawdown": max_drawdown,
        "horizon_days": horizon_days,
        "cost_assumption": f"佣金 {commission_bps:.1f} bps + 滑点 {slippage_bps:.1f} bps + 年费 {annual_fee_rate:.2%}",
    }
    return recommendations, profile
