"""Independent T07 evidence; deliberately assert recovery with unchanged query."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from fund_ai_research.analysis import OpenAICompatibleAnalyzer
from fund_ai_research.connectors import CompositeConnector, DemoConnector
from fund_ai_research.presentation import concise_source_label

@pytest.mark.parametrize("initial_failure", [False, True], ids=["with_previous_result", "first_load"])
def test_P01_same_parameters_can_retry_after_upstream_recovers(initial_failure):
    st.cache_data.clear()
    control = {"empty": initial_failure, "calls": 0}
    def history(self, code, start, end):
        control["calls"] += 1
        frame = DemoConnector().fetch_history(code, start, end)
        return (frame.iloc[:0].copy() if control["empty"] else frame), "演示数据"

    with patch.object(CompositeConnector, "fetch_history", history), \
         patch.object(CompositeConnector, "fetch_events", return_value=[]), \
         patch.object(OpenAICompatibleAnalyzer, "enabled", new=property(lambda self: False)):
        app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=60).run()
        assert not app.exception, [x.message for x in app.exception]
        if not initial_failure:
            old = app.session_state["params"].copy()
            control["empty"] = True
            app.date_input[0].set_value(date(2024, 1, 1))
            app.button[0].click().run()
            assert not app.exception
            assert app.session_state["params"] == old
        calls_before_retry = control["calls"]
        assert calls_before_retry > 0
        assert any("没有可用行情" in x.value for x in app.warning)
        control["empty"] = False
        app.button[0].click().run()
        assert not app.exception
        assert control["calls"] > calls_before_retry, (
            f"same-parameter submit did not reach the recovered connector: "
            f"before={calls_before_retry} after={control['calls']}"
        )
        assert app.session_state["result"].metrics
        assert not any("没有可用行情" in x.value for x in app.warning)

@pytest.mark.parametrize("status,label,basis", [
    ("verified", "东方财富公开日线｜价格口径:拆分调整后收盘价", "split_adjusted_close"),
    ("switched", "东方财富公开日线（双源校验换源）｜价格口径:拆分调整后收盘价", "split_adjusted_close"),
    ("source_unverified", "Yahoo Finance public chart（交叉校验未完成）", "split_adjusted_close"),
    ("fallback_demo", "演示数据（双源校验异常回退）", "demo"),
    ("demo", "演示数据", "demo"),
])
def test_t07_source_contract_reaches_page(status, label, basis):
    st.cache_data.clear()
    def history(self, code, start, end):
        frame = DemoConnector().fetch_history(code, start, end)
        frame.attrs["source_check_status"] = status
        return frame, label

    with patch.object(CompositeConnector, "fetch_history", history), \
         patch.object(CompositeConnector, "fetch_events", return_value=[]), \
         patch.object(OpenAICompatibleAnalyzer, "enabled", new=property(lambda self: False)):
        app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=60).run()
    assert not app.exception, [x.message for x in app.exception]
    metrics = app.session_state["result"].metrics
    assert metrics and all(m.as_dict()["source_check_status"] == status for m in metrics)
    assert all(m.price_basis == basis and m.source == label for m in metrics)
    table = next(x.value for x in app.dataframe if "来源校验状态" in x.value.columns and "接口标签" in x.value.columns)
    assert set(table["来源校验状态"]) == {status}
    assert set(table["价格口径"]) == {basis}
    assert set(table["接口标签"]) == {concise_source_label(label)}
    summary = next(item.value for item in app.caption if str(item.value).startswith("当前结果查询区间："))
    assert concise_source_label(label) in summary
    assert "交叉校验未完成" not in summary
    assert "备用源不可用且主源待核实回退" not in summary
    assert set(table["公司行动状态"]) == {m.corporate_action_status for m in metrics}
    assert set(table["缺口处理"]) == {m.missing_policy for m in metrics}
    if status == "verified":
        assert set(table["状态"]) == {"真实行情"}
    if status == "source_unverified":
        assert set(table["状态"]) == {"真实行情（交叉校验未完成）"}


@pytest.mark.parametrize("scenario",["success_cache","repeat_empty"])
def test_cache_policy_after_empty_query(scenario):
    st.cache_data.clear()
    control={"empty":scenario=="repeat_empty","calls":0}
    def history(self,code,start,end):
        control["calls"]+=1
        frame=DemoConnector().fetch_history(code,start,end)
        return (frame.iloc[:0].copy() if control["empty"] else frame),"演示数据"
    with patch.object(CompositeConnector,"fetch_history",history),patch.object(CompositeConnector,"fetch_events",return_value=[]),patch.object(OpenAICompatibleAnalyzer,"enabled",new=property(lambda self:False)):
        app=AppTest.from_file(Path.cwd()/"app.py",default_timeout=60).run()
        assert not app.exception
        before=control["calls"]
        if scenario=="repeat_empty":
            app.button[0].click().run()
            assert not app.exception and control["calls"]>before
            assert any("没有可用行情" in x.value for x in app.warning)
            return
        original_start=app.session_state["params"]["start"]
        original_result=app.session_state["result"].fetched_at
        app.button[0].click().run()
        assert not app.exception and control["calls"]==before
        control["empty"]=True
        app.date_input[0].set_value(date(2024,1,1));app.button[0].click().run()
        assert not app.exception and control["calls"]>before
        assert app.session_state["result"].fetched_at==original_result
        assert app.session_state["params"]["start"]==original_start
        calls=control["calls"];control["empty"]=False
        app.date_input[0].set_value(original_start);app.button[0].click().run()
        assert not app.exception and control["calls"]==calls
        assert app.session_state["result"].fetched_at==original_result
        assert not any("没有可用行情" in x.value for x in app.warning)
