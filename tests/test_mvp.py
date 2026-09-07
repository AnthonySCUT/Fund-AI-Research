from datetime import date
from unittest.mock import patch

import pandas as pd

from fund_ai_research.analytics import calculate_metrics, normalize_history, validate_history
from fund_ai_research.connectors import DEFAULT_FUNDS, DemoConnector, EastmoneyConnector
from fund_ai_research.recommender import build_personalized_recommendations


def test_demo_history_is_normalized_and_validated():
    history = DemoConnector().fetch_history("510300", date(2023, 1, 1), date(2024, 1, 1))
    clean = normalize_history(history, "510300")
    report = validate_history(history, "510300")
    assert len(clean) > 200
    assert report.quality_score > 0.95
    assert {"daily_return", "drawdown"}.issubset(clean.columns)


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
