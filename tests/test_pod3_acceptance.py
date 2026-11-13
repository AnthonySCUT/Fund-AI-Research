"""Pod 3 acceptance checks for the existing implementation; run against the pinned repository."""
from dataclasses import replace
from datetime import date
import math

import pytest

from fund_ai_research.analytics import holding_scenarios
from fund_ai_research.models import FundMetrics
from fund_ai_research.recommender import build_personalized_recommendations
from fund_ai_research.pipeline import run_pipeline


def metric(code="A", **changes):
    value = FundMetrics(code, code, "ETF", 100, .1, .1, .2, -.15,
                        2 / 3, .05, .5, 100, 100, date(2026, 11, 6), 1, "fixture")
    return replace(value, **changes)


def recommend(values, aggression=45, threshold=15):
    return build_personalized_recommendations(values, aggression, threshold, 20, 2.5, 5, .005)


@pytest.mark.parametrize("days", [1, 5, 20, 60, 126, 252])
@pytest.mark.parametrize("commission,slippage,fee", [(0, 0, 0), (2.5, 5, .005), (10, 20, .01)])
def test_scenarios_match_independent_arithmetic(days, commission, slippage, fee):
    years = days / 252
    middle = .1 * years - 2 * (commission + slippage) * .0001 - fee * years
    width = .16 * math.sqrt(years)
    assert holding_scenarios(metric(), days, commission, slippage, fee) == pytest.approx(
        (middle - width, middle, middle + width), abs=1e-12)


@pytest.mark.parametrize("days", [1, 20, 252])
@pytest.mark.parametrize("change", ["commission", "slippage"])
def test_increasing_one_side_cost_by_10bps_reduces_all_scenarios(days, change):
    before = holding_scenarios(metric(), days, 2.5, 5, .005)
    after = holding_scenarios(metric(), days, 12.5 if change == "commission" else 2.5,
                              15 if change == "slippage" else 5, .005)
    assert [a - b for a, b in zip(after, before)] == pytest.approx([-.002] * 3)


def test_all_ui_aggression_values_preserve_total_and_direction():
    profiles = [recommend([metric()], aggression=a)[1] for a in range(101)]
    assert all(sum(p[k] for k in ["core_weight", "tactical_weight", "cash_weight"]) == 100
               for p in profiles)
    assert all(p[k] >= 0 for p in profiles for k in ["core_weight", "tactical_weight", "cash_weight"])
    assert all(b["core_weight"] <= a["core_weight"] and b["tactical_weight"] >= a["tactical_weight"]
               for a, b in zip(profiles, profiles[1:]))
    assert tuple(profiles[50][k] for k in ["core_weight", "tactical_weight", "cash_weight"]) == (58, 38, 4)


def test_single_fund_keeps_two_roles_and_total_exposure():
    rows, p = recommend([metric()])
    assert [r.code for r in rows] == ["A", "A"]
    assert {r.role for r in rows} == {"核心仓", "战术仓"}
    assert sum(r.target_weight for r in rows) + p["cash_weight"] == 100


def test_multiple_candidates_use_different_codes():
    rows, _ = recommend([metric("A"), metric("B", annualized_return=.05)])
    assert rows[0].code != rows[1].code


@pytest.mark.parametrize("drawdown,warning,tactical_action", [
    (-.149, False, "可继续研究"), (-.15, False, "可继续研究"),
    (-.151, True, "等待验证"), (-.224, True, "等待验证"),
    (-.226, True, "不碰"),
])
def test_drawdown_warning_and_tactical_state(drawdown, warning, tactical_action):
    rows, _ = recommend([metric(max_drawdown=drawdown)])
    assert all(any("超过用户阈值" in f for f in r.risk_flags) == warning for r in rows)
    assert next(r.action for r in rows if r.role == "战术仓") == tactical_action


@pytest.mark.parametrize("quality,warning", [(.899, True), (.9, False), (.901, False)])
def test_quality_threshold(quality, warning):
    rows, _ = recommend([metric(quality_score=quality)])
    assert all(any("数据质量未达到" in f for f in r.risk_flags) == warning for r in rows)


@pytest.mark.parametrize("aggression,warning", [(69, False), (70, True), (80, True)])
def test_high_aggression_warning(aggression, warning):
    rows, _ = recommend([metric()], aggression=aggression)
    tactical = next(r for r in rows if r.role == "战术仓")
    assert any("激进参数较高" in f for f in tactical.risk_flags) == warning


def test_empty_universe_retains_cash():
    rows, p = recommend([])
    assert rows == [] and p["cash_weight"] == 100


def test_demo_pipeline_parameter_to_candidate_integration():
    result = run_pipeline(["510300", "510500", "159915"], source_mode="demo",
                          start=date(2024, 1, 1), end=date(2026, 11, 6),
                          aggression=80, max_drawdown=15, horizon_days=60,
                          commission_bps=10, slippage_bps=5, annual_fee_rate=.005)
    assert len(result.metrics) == 3 and len(result.recommendations) == 2
    assert result.profile["aggression"] == 80 and result.profile["horizon_days"] == 60
    for r in result.recommendations:
        m = next(m for m in result.metrics if m.code == r.code)
        expected = holding_scenarios(m, 60, 10, 5, .005)
        assert r.net_return_range == " / ".join(f"{v:+.1%}" for v in expected)
