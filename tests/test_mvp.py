from datetime import date
import os
from unittest.mock import patch

import pandas as pd
import requests

from fund_ai_research.adjustments import CorporateAction, load_actions, standardize
from fund_ai_research.analysis import analyze_metrics
from fund_ai_research.analytics import (
    calculate_metrics,
    max_drawdown_recovery_days,
    normalize_history,
    rolling_returns,
    validate_history,
)
from fund_ai_research.connectors import DEFAULT_FUNDS, CompositeConnector, DemoConnector, EastmoneyConnector, EastmoneyFundDisclosureConnector, OfficialDisclosureConnector, cross_verify_sources
from fund_ai_research.incremental import fingerprints_for_records
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


def test_detail_metrics_include_rolling_returns_and_recovery_time():
    history = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=5, freq="B"),
            "close": [100, 120, 60, 80, 120],
            "aum": [100] * 5,
            "volume": [10] * 5,
        }
    )
    rolling = rolling_returns(history, windows=(2,))
    assert rolling["rolling_2d"].iloc[2] == -0.4
    assert max_drawdown_recovery_days(history) == 2


def test_eastmoney_history_parser_uses_real_close_and_volume():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            # Real layout: date, close, high, low, volume, amount, amplitude,
            # pct_chg, change, turnover (fields2 skips f52/open).
            return {"data": {"klines": [
                "2026-09-04,4.620,4.650,4.590,123456,570000000,1.30,0.43,0.02,0.50",
                "2026-09-07,4.634,4.670,4.610,234567,1080000000,1.30,0.30,0.01,0.70",
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


def test_incremental_fingerprints_change_only_the_affected_fund():
    connector = DemoConnector()
    metrics = []
    quality = []
    for profile in DEFAULT_FUNDS[:2]:
        history = connector.fetch_history(profile.code, date(2025, 1, 1), date(2026, 1, 1))
        report = validate_history(history, profile.code)
        quality.append(report)
        metrics.append(calculate_metrics(history, profile.code, profile.name, profile.category, report, "demo"))

    before = fingerprints_for_records(metrics, quality, [])
    changed_metrics = list(metrics)
    changed_metrics[0] = calculate_metrics(
        connector.fetch_history("510300", date(2024, 1, 1), date(2026, 1, 1)),
        "510300",
        DEFAULT_FUNDS[0].name,
        DEFAULT_FUNDS[0].category,
        quality[0],
        "demo",
    )
    after = fingerprints_for_records(changed_metrics, quality, [])

    assert before["510300"] != after["510300"]
    assert before["510500"] == after["510500"]


def _synthetic_frame(dates, closes):
    return pd.DataFrame(
        {
            "trade_date": pd.DatetimeIndex(dates),
            "close": closes,
            "aum": 1.0,
            "volume": 1.0,
        }
    )


def test_first_daily_return_is_not_zero_filled():
    dates = pd.bdate_range("2026-01-05", periods=5)
    history = _synthetic_frame(dates, [1.0, 1.1, 1.2, 1.1, 1.3])
    clean = normalize_history(history, "T")
    assert pd.isna(clean["daily_return"].iloc[0])
    assert clean["cumulative_return"].iloc[0] == 0.0


def test_holidays_are_not_counted_as_missing_days():
    full = pd.bdate_range("2026-02-09", "2026-02-27")
    trading = [d for d in full if not pd.Timestamp("2026-02-16") <= d <= pd.Timestamp("2026-02-20")]
    history = _synthetic_frame(trading, [1.0 + 0.01 * i for i in range(len(trading))])
    report = validate_history(history, "T", trading_days=trading)
    assert report.missing_dates == 0
    assert report.quality_score == 1.0


def test_split_adjustment_bridges_price_unit_change():
    dates = pd.bdate_range("2024-01-01", periods=10)
    history = _synthetic_frame(dates, [2.0] * 5 + [1.0] * 5)
    actions = [CorporateAction("T", date(2024, 1, 8), 2.0, "split", True, "test")]
    adjusted, status = standardize(history, "T", actions)
    assert status == "split_adjusted"
    assert adjusted["close"].round(6).nunique() == 1
    assert float(adjusted["close"].pct_change().abs().max() or 0) == 0.0


def test_already_adjusted_source_is_not_adjusted_twice():
    dates = pd.bdate_range("2024-01-01", periods=10)
    history = _synthetic_frame(dates, [1.0] * 10)
    actions = [CorporateAction("T", date(2024, 1, 8), 2.0, "split", True, "test")]
    adjusted, status = standardize(history, "T", actions)
    assert status == "split_adjusted"
    assert sorted(adjusted["split_factor"].unique()) == [1.0]


def test_unverified_split_is_flagged_without_changing_prices():
    dates = pd.bdate_range("2024-01-01", periods=10)
    history = _synthetic_frame(dates, [3.0] * 5 + [1.0] * 5)
    adjusted, status = standardize(history, "T", [])
    assert status == "unverified"
    assert (adjusted["split_factor"] == 1.0).all()
    pd.testing.assert_series_equal(adjusted["close"], history["close"])


def test_unresolved_dual_source_anomaly_falls_back_to_demo():
    dates = pd.bdate_range("2024-01-01", periods=2)
    yahoo = _synthetic_frame(dates, [10.0, 5.0])
    eastmoney = _synthetic_frame(dates, [10.0, 4.0])
    result = cross_verify_sources(yahoo, eastmoney, "510300")
    assert result["status_yahoo"] == result["status_eastmoney"] == "unverified"
    assert result["selected"] == result["source_check_status"] == "fallback_demo"

    connector = CompositeConnector("auto")
    with patch.object(connector.yahoo, "fetch_history", return_value=yahoo), \
         patch.object(connector.eastmoney, "fetch_history", return_value=eastmoney):
        frame, label = connector.fetch_history("510300", dates[0].date(), dates[-1].date())
    assert frame.attrs["source_check_status"] == "fallback_demo"
    assert frame.attrs["cross_check"]["selected"] == "fallback_demo"
    assert "演示数据（双源校验异常回退）" in label


def test_price_disagreement_with_unverified_eastmoney_falls_back():
    dates = pd.bdate_range("2024-01-01", periods=2)
    result = cross_verify_sources(
        _synthetic_frame(dates, [10.0, 10.0]),
        _synthetic_frame(dates, [10.0, 4.0]),
        "510300",
    )
    assert result["selected"] == result["source_check_status"] == "fallback_demo"


def test_insufficient_common_dates_remain_unverified():
    dates = pd.bdate_range("2024-01-01", periods=3)
    yahoo = _synthetic_frame(dates[:2], [10.0, 10.0])
    for east_dates in (dates[2:], dates[1:]):
        eastmoney = _synthetic_frame(east_dates, [10.0] * len(east_dates))
        result = cross_verify_sources(yahoo, eastmoney, "510300")
        assert result["selected"] == "yahoo"
        assert result["source_check_status"] == "source_unverified"
        connector = CompositeConnector("auto")
        with patch.object(connector.yahoo, "fetch_history", return_value=yahoo.copy()), \
             patch.object(connector.eastmoney, "fetch_history", return_value=eastmoney):
            frame, label = connector.fetch_history("510300")
        assert frame.attrs["source_check_status"] == "source_unverified"
        assert "交叉校验未完成" in label


def test_insufficient_common_dates_with_suspect_primary():
    dates = pd.bdate_range("2024-01-01", periods=4)
    yahoo = _synthetic_frame(dates[:2], [10.0, 5.0])
    eastmoney = _synthetic_frame(dates[2:], [10.0, 10.0])
    for code in ("510300", "512480"):
        primary = yahoo if code == "510300" else _synthetic_frame(dates[:2], [10.0, 10.0])
        result = cross_verify_sources(primary, eastmoney, code)
        assert result["selected"] == "eastmoney"
        assert result["source_check_status"] == "source_unverified"
        connector = CompositeConnector("auto")
        with patch.object(connector.yahoo, "fetch_history", return_value=primary), \
             patch.object(connector.eastmoney, "fetch_history", return_value=eastmoney.copy()):
            frame, label = connector.fetch_history(code)
        assert frame.attrs["source_check_status"] == "source_unverified"
        assert "交叉校验未完成" in label

    bad_eastmoney = _synthetic_frame(dates[2:], [10.0, 4.0])
    result = cross_verify_sources(yahoo, bad_eastmoney, "510300")
    assert result["selected"] == result["source_check_status"] == "fallback_demo"


def test_reconciliation_fallback_metrics_use_demo_data():
    from scripts.reconcile_sources import _metrics, reconcile

    profile = DEFAULT_FUNDS[0]
    dates = pd.bdate_range("2024-01-01", periods=40)
    yahoo = _synthetic_frame(dates, [10.0] * 39 + [5.0])
    eastmoney = _synthetic_frame(dates, [10.0] * 39 + [4.0])
    start, end = dates[0].date(), dates[-1].date()
    with patch("scripts.reconcile_sources._fetch_with_retry", side_effect=[yahoo, eastmoney]):
        result = reconcile(profile.code, profile, start, end, {})

    demo = DemoConnector([profile]).fetch_history(profile.code, start, end)
    standardized, status = standardize(demo, profile.code, [])
    expected = _metrics(standardized, profile, None, "demo_deterministic", status)
    expected["source"] = "demo_deterministic"
    assert result["selection"]["selected_source"] == "fallback_demo"
    assert result["selected_metrics"] == expected
    assert result["selected_metrics"]["total_return"] != result["after"]["eastmoney"]["total_return"]


def test_gap_returns_are_excluded_and_flagged():
    full = pd.bdate_range("2026-01-05", "2026-01-30")
    trading = [d for d in full if not pd.Timestamp("2026-01-12") <= d <= pd.Timestamp("2026-01-14")]
    history = _synthetic_frame(trading, [1.0 + 0.01 * i for i in range(len(trading))])
    report = validate_history(history, "T", trading_days=full)
    metric = calculate_metrics(history, "T", "T", "x", report, "test", trading_days=full)
    assert report.missing_dates == 3
    assert metric.missing_policy == "gap_excluded"


def test_new_metric_fields_have_safe_defaults():
    dates = pd.bdate_range("2026-01-05", periods=5)
    history = _synthetic_frame(dates, [1.0, 1.1, 1.2, 1.1, 1.3])
    report = validate_history(history, "T")
    metric = calculate_metrics(history, "T", "T", "x", report, "test")
    payload = metric.as_dict()
    assert payload["price_basis"] == "split_adjusted_close"
    assert payload["corporate_action_status"] == "none"
    assert payload["missing_policy"] == "none"
    assert load_actions("does-not-exist.json") == {}
