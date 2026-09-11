from datetime import date
import os
from unittest.mock import patch

import pandas as pd
import requests

from fund_ai_research.analysis import analyze_metrics
from fund_ai_research.analytics import calculate_metrics, normalize_history, validate_history
from fund_ai_research.connectors import DEFAULT_FUNDS, DemoConnector, EastmoneyConnector, EastmoneyFundDisclosureConnector, OfficialDisclosureConnector
from fund_ai_research.models import EventRecord
from fund_ai_research.recommender import build_personalized_recommendations


def test_demo_history_is_normalized_and_validated():
    history = DemoConnector().fetch_history("510300", date(2023, 1, 1), date(2024, 1, 1))
    clean = normalize_history(history, "510300")
    report = validate_history(history, "510300")
    assert len(clean) > 200
    assert report.quality_score > 0.95
    assert {"daily_return", "drawdown"}.issubset(clean.columns)


def test_default_universe_covers_at_least_ten_passive_funds():
    assert len(DEFAULT_FUNDS) >= 10
    assert len({profile.code for profile in DEFAULT_FUNDS}) == len(DEFAULT_FUNDS)


def test_metrics_and_personalized_weights_include_costs():
    connector = DemoConnector()
    metrics = []
    quality = []
    for profile in DEFAULT_FUNDS[:3]:
        raw = connector.fetch_history(profile.code, date(2022, 1, 1), date(2024, 1, 1))
        report = validate_history(raw, profile.code)
        quality.append(report)
        metrics.append(calculate_metrics(raw, profile.code, profile.name, profile.category, report, "demo"))
    recommendations, profile = build_personalized_recommendations(metrics, 80, 20, 20, 2.5, 5.0, 0.005)
    assert recommendations
    assert profile["core_weight"] + profile["tactical_weight"] + profile["cash_weight"] == 100
    assert all("/" in item.net_return_range for item in recommendations)


def test_eastmoney_history_parser_uses_real_close_and_volume():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"klines": [
                "2026-09-04,4.600,4.620,4.650,4.590,123456,570000000,1.30,0.43,0.02,0.50",
                "2026-09-07,4.630,4.634,4.670,4.610,234567,1080000000,1.30,0.30,0.01,0.70",
            ]}}

    with patch("fund_ai_research.connectors.requests.get", return_value=FakeResponse()):
        frame = EastmoneyConnector().fetch_history("510300", date(2026, 9, 1), date(2026, 9, 7))

    assert list(frame["close"]) == [4.62, 4.634]
    assert list(frame["volume"]) == [123456.0, 234567.0]
    assert frame["source_id"].iloc[0] == "eastmoney_kline:510300.SS"


def test_official_sse_disclosure_parser_filters_by_fund():
    html = '''
    <div class="disclosure-item"><div><a href="/a.pdf">关于沪深300ETF定期报告的公告</a></div>
    <div>2026-09-08</div></div>
    <div class="disclosure-item"><div><a href="/b.pdf">其他基金公告</a></div>
    <div>2026-09-08</div></div>
    '''
    class FakeResponse:
        text = html

        def raise_for_status(self):
            return None

    with patch("fund_ai_research.connectors.requests.get", return_value=FakeResponse()):
        events = OfficialDisclosureConnector().fetch_events("510300")

    assert len(events) == 1
    assert events[0].source == "sse_official_disclosure"
    assert events[0].url.endswith("/a.pdf")


def test_eastmoney_public_disclosure_parser_classifies_reports():
    class FakeResponse:
        text = 'jQuery({"Data":[{"TITLE":"沪深300ETF 2026年中期报告","PUBLISHDATE":"2026-08-29T00:00:00","ID":"AN202608291234567890","NEWCATEGORY":"3"}],"ErrCode":0})'

        def raise_for_status(self):
            return None

    with patch("fund_ai_research.connectors.requests.get", return_value=FakeResponse()):
        events = EastmoneyFundDisclosureConnector().fetch_events("510300")

    assert len(events) == 1
    assert events[0].document_type == "半年报"
    assert events[0].source == "eastmoney_fund_disclosure"
    assert "AN202608291234567890" in events[0].url


def test_deepseek_fallback_is_used_when_grok_request_fails():
    metric = calculate_metrics(
        normalize_history(DemoConnector().fetch_history("510300", date(2025, 1, 1), date(2026, 1, 1)), "510300"),
        "510300",
        DEFAULT_FUNDS[0].name,
        DEFAULT_FUNDS[0].category,
        validate_history(DemoConnector().fetch_history("510300", date(2025, 1, 1), date(2026, 1, 1)), "510300"),
        "demo",
    )
    quality = validate_history(DemoConnector().fetch_history("510300", date(2025, 1, 1), date(2026, 1, 1)), "510300")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"cards":[{"code":"510300","status":"黄灯","facts":["ok"],"positive_evidence":[],"risk_signals":[],"verification_questions":[],"conclusion":"fallback"}]}'}}]}

    with patch.dict(os.environ, {
        "GROK_API_KEY": "grok-test",
        "GROK_BASE_URL": "https://grok.example/v1",
        "DEEPSEEK_API_KEY": "deepseek-test",
        "DEEPSEEK_BASE_URL": "https://deepseek.example/v1",
    }, clear=False), patch("fund_ai_research.analysis.requests.post", side_effect=[requests.Timeout(), FakeResponse()]) as post:
        cards = analyze_metrics([metric], [quality], [])

    assert cards["510300"].source == "Deepseek:deepseek-chat"
    assert cards["510300"].conclusion == "fallback"
    assert post.call_count == 2
