"""T07 acceptance reproductions; run from the pinned application root."""
from datetime import date
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from fund_ai_research.connectors import CompositeConnector, DemoConnector
from fund_ai_research.analysis import OpenAICompatibleAnalyzer
from fund_ai_research.pipeline import run_pipeline
from fund_ai_research.recommender import build_personalized_recommendations

@pytest.fixture
def page_env():
    st.cache_data.clear()
    control = {"empty": False, "partial": False, "source": "demo"}
    def history(self, code, start, end):
        frame = DemoConnector().fetch_history(code, start, end)
        if control["empty"] or (control["partial"] and code == "510500"):
            frame = frame.iloc[:0].copy()
        label = "演示数据"
        if control["source"] == "real" or (control["source"] == "mixed" and code == "510300"):
            label = "Yahoo Finance public chart"
        return frame, label
    with patch.object(CompositeConnector, "fetch_history", history), patch.object(CompositeConnector, "fetch_events", lambda self, code: []), patch.object(OpenAICompatibleAnalyzer, "enabled", new=property(lambda self: False)):
        yield control

def page():
    app = AppTest.from_file(Path.cwd()/"app.py", default_timeout=60).run()
    assert not app.exception
    return app

def submit(app):
    app.button[0].click().run()
    assert not app.exception, [x.message for x in app.exception]

def test_P01_invalid_dates_preserve_and_retry(page_env):
    app=page();old=app.session_state["params"].copy()
    app.date_input[0].set_value(date(2024,12,31));app.date_input[1].set_value(date(2024,1,1));submit(app)
    assert app.session_state["params"]==old
    assert any("日期" in x.value or "起" in x.value for x in list(app.error)+list(app.warning))
    app.date_input[0].set_value(date(2024,1,1));app.date_input[1].set_value(date(2024,12,31));submit(app)
    assert app.session_state["params"]["start"]==date(2024,1,1)

def test_P01_empty_preserves_last_result_and_retry(page_env):
    app=page();old=app.session_state["result"];params=app.session_state["params"].copy()
    page_env["empty"]=True
    app.date_input[0].set_value(date(2024,1,1));submit(app)
    assert app.session_state["result"].fetched_at==old.fetched_at
    assert app.session_state["params"]==params
    page_env["empty"]=False
    app.date_input[0].set_value(date(2024,2,1));submit(app)
    assert app.session_state["result"].metrics

def test_P01_initial_empty_can_retry(page_env):
    page_env["empty"]=True
    app=AppTest.from_file(Path.cwd()/"app.py",default_timeout=60).run()
    assert not app.exception, [x.message for x in app.exception]
    page_env["empty"]=False
    app.date_input[0].set_value(date(2024,1,1));submit(app)
    assert app.session_state["result"].metrics

def test_P01_partial_empty_survives(page_env):
    app=page();page_env["partial"]=True
    app.multiselect[0].set_value(["510300","510500"]);submit(app)
    assert [x.code for x in app.session_state["result"].metrics]==["510300"]

def test_P02_remove_readd_restores_cards(page_env):
    app=page();app.multiselect[0].set_value(["510300"]);submit(app)
    app.multiselect[0].set_value(["510300","510500"]);submit(app)
    assert {x.code for x in app.session_state["result"].metrics} <= set(app.session_state["cards"])

def test_P02_date_change_refreshes_cards(page_env):
    app=page();app.multiselect[0].set_value(["510300"]);submit(app)
    before=repr(app.session_state["cards"]["510300"])
    app.date_input[0].set_value(date(2024,1,1));app.date_input[1].set_value(date(2024,12,31));submit(app)
    after=repr(app.session_state["cards"]["510300"])
    assert after != before, "changed sample retained identical research card"

def test_P03_demo_table_and_detail_state_agree(page_env):
    app=page()
    tables=[x.value for x in app.dataframe if "研究状态" in x.value.columns]
    assert tables and set(tables[0]["研究状态"])=={"仅演示，不可执行"}
    titles=[x.label for x in app.expander if "核心仓 ·" in x.label or "战术仓 ·" in x.label]
    assert titles and all("仅演示，不可执行" in x for x in titles),titles

@pytest.mark.parametrize("drawdown,expected",[(.2249,"等待验证"),(.225,"等待验证"),(.2251,"不碰")])
def test_P04_strict_boundary(drawdown,expected):
    result=run_pipeline(["510300"],"demo",date(2024,1,1),date(2024,12,31))
    metric=replace(result.metrics[0],quality_score=1.0,max_drawdown=-drawdown)
    rows,profile=build_personalized_recommendations([metric],aggression=45,max_drawdown=15,horizon_days=20,commission_bps=2.5,slippage_bps=5,annual_fee_rate=.005)
    tactical=next(x for x in rows if x.role=="战术仓")
    assert tactical.action==expected
    assert tactical.target_weight==35
    assert any("超过用户阈值" in x for x in tactical.risk_flags)


def test_P01_partial_empty_detail_selection(page_env):
    app=page();page_env["partial"]=True
    app.multiselect[0].set_value(["510300","510500"]);submit(app)
    detail=next(x for x in app.selectbox if x.label=="选择基金")
    assert len(detail.options)==1
    assert any("510300" in str(x) for x in detail.options)

def test_P01_retained_result_dates_and_sources(page_env):
    app=page();params=app.session_state["params"].copy()
    page_env["empty"]=True
    app.date_input[0].set_value(date(2024,1,1));submit(app)
    text=" ".join(x.value for x in app.caption)
    assert params["start"].isoformat() in text and params["end"].isoformat() in text
    assert "演示数据" in text

@pytest.mark.parametrize("source",["real","mixed"])
def test_P03_table_and_detail_sources(page_env,source):
    page_env["source"]=source
    app=page();app.multiselect[0].set_value(["510300","510500"]);submit(app)
    table=next(x.value for x in app.dataframe if "研究状态" in x.value.columns)
    titles=[x.label for x in app.expander if "核心仓 ·" in x.label or "战术仓 ·" in x.label]
    assert len(titles)==len(table)
    for row,title in zip(table.to_dict("records"),titles):
        assert row["研究状态"] in title
    if source=="mixed":
        assert set(table["研究状态"])=={"仅演示，不可执行"}
    else:
        assert "仅演示，不可执行" not in set(table["研究状态"])

def test_P03_old_preview_uses_previous_source(page_env):
    app=page()
    page_env["source"]="real"
    app.date_input[0].set_value(date(2024,1,1))
    with patch.object(st,"dataframe",wraps=st.dataframe) as capture:
        submit(app)
    tables=[call.args[0] for call in capture.call_args_list if call.args and hasattr(call.args[0],"columns") and "研究状态" in call.args[0].columns]
    assert tables and set(tables[0]["研究状态"])=={"仅演示，不可执行"}
    assert "仅演示，不可执行" not in set(tables[-1]["研究状态"])

def test_P02_date_cards_match_new_metrics(page_env):
    app=page();app.multiselect[0].set_value(["510300"])
    app.date_input[0].set_value(date(2024,1,1));app.date_input[1].set_value(date(2024,12,31));submit(app)
    metric=app.session_state["result"].metrics[0]
    card=app.session_state["cards"]["510300"]
    assert any(metric.as_of.isoformat() in fact and f"{metric.latest_value:.4f}" in fact for fact in card.facts)


@pytest.mark.parametrize("matching",[True,False])
def test_P02_snapshot_reuse_requires_matching_facts(page_env,matching):
    from dataclasses import asdict
    import json
    app=page()
    result=app.session_state["result"]
    code=result.metrics[0].code
    card=asdict(app.session_state["cards"][code])
    card["source"]="固定后台快照"
    payload={"fetched_at":result.fetched_at,"metrics":[x.as_dict() for x in result.metrics],"quality":[asdict(x) for x in result.quality],"events":[],"research_cards":[card]}
    if not matching:
        payload["metrics"][0]["latest_value"]+=1
    read_text=Path.read_text
    def read(path,*args,**kwargs):
        if path.name=="latest_research.json":
            return json.dumps(payload,ensure_ascii=False,default=str)
        return read_text(path,*args,**kwargs)
    with patch.object(Path,"read_text",read):
        fresh=page()
    selected=fresh.session_state["cards"][code]
    if matching:
        assert selected.source=="固定后台快照"
        assert any("后台快照卡片" in x.value and "固定后台快照" in x.value for x in fresh.caption)
    else:
        assert selected.source!="固定后台快照"
        metric=fresh.session_state["result"].metrics[0]
        assert any(f"{metric.latest_value:.4f}" in fact for fact in selected.facts)

def test_new_source_fields_reach_page(page_env):
    app=page()
    table=next(x.value for x in app.dataframe if "来源校验状态" in x.value.columns and "接口标签" in x.value.columns)
    assert set(table["来源校验状态"])=={"demo"}
    assert set(table["价格口径"])=={"demo"}
    assert {"公司行动状态","缺口处理"} <= set(table.columns)
