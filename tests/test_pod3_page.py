"""Streamlit page regression using deterministic offline data and no model calls.

Run from the pinned repository root with this file passed to pytest.
"""
import pytest
from pathlib import Path
from unittest.mock import patch
import streamlit as st
from streamlit.testing.v1 import AppTest
from fund_ai_research.connectors import CompositeConnector, DemoConnector
from fund_ai_research.analysis import OpenAICompatibleAnalyzer


@pytest.fixture
def page():
    st.cache_data.clear()
    with patch.object(CompositeConnector, "fetch_history",
                      lambda self, code, start, end: (
                          DemoConnector().fetch_history(code, start, end), "演示数据")), \
         patch.object(CompositeConnector, "fetch_events", lambda self, code: []), \
         patch.object(OpenAICompatibleAnalyzer, "enabled", new=property(lambda self: False)):
        app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=60).run()
        assert not app.exception
        yield app


def test_aggression_submit_updates_weights(page):
    page.slider[0].set_value(80)
    page.button[0].click().run()
    assert not page.exception
    shown = {m.label: m.value for m in page.metric}
    assert (shown["核心仓目标"], shown["战术仓目标"], shown["现金缓冲"]) == ("41%", "54%", "5%")
    assert page.session_state["result"].profile["aggression"] == 80


def test_cost_and_horizon_reach_calculation(page):
    before = page.session_state["result"].recommendations[0].net_return_range
    page.number_input[0].set_value(12.5)
    page.button[0].click().run()
    after = page.session_state["result"].recommendations[0].net_return_range
    assert not page.exception
    parse = lambda value: [float(x.strip().removesuffix("%")) for x in value.split("/")]
    assert [b - a for a, b in zip(parse(before), parse(after))] == pytest.approx([-.2] * 3)
    page.select_slider[0].set_value(60)
    page.button[0].click().run()
    assert not page.exception
    assert page.session_state["result"].profile["horizon_days"] == 60
    assert "12.5 bps" in page.session_state["result"].profile["cost_assumption"]


def test_single_fund_keeps_roles_and_demo_notice(page):
    page.multiselect[0].set_value(["510300"])
    page.button[0].click().run()
    assert not page.exception
    assert [r.code for r in page.session_state["result"].recommendations] == ["510300", "510300"]
    assert any("演示数据" in x.value for x in page.warning)
    tables = [x.value for x in page.dataframe if "研究状态" in x.value.columns]
    assert any(set(table["研究状态"]) == {"仅演示，不可执行"} for table in tables)


def test_risk_threshold_reaches_recommendations(page):
    page.slider[1].set_value(5.0)
    page.button[0].click().run()
    assert not page.exception
    result = page.session_state["result"]
    assert result.profile["max_drawdown"] == 5
    assert all(any("超过用户阈值" in flag for flag in row.risk_flags)
               for row in result.recommendations)
