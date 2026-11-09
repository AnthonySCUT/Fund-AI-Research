from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence

import pandas as pd

from .adjustments import load_actions, standardize
from .analytics import calculate_metrics, normalize_history, validate_history
from .connectors import CompositeConnector, DEFAULT_FUNDS
from .models import EventRecord, FundMetrics, FundProfile, QualityReport, Recommendation
from .recommender import build_personalized_recommendations


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

# Mainland exchange (SSE/SZSE) non-weekend closure intervals (2017–2026).
_CN_MARKET_CLOSURES: tuple[str, ...] = (
    "2017-01-02", "2017-01-27:2017-02-02", "2017-04-03:2017-04-04", "2017-05-01",
    "2017-05-29:2017-05-30", "2017-10-02:2017-10-06", "2018-01-01", "2018-02-15:2018-02-21",
    "2018-04-05:2018-04-06", "2018-04-30:2018-05-01", "2018-06-18", "2018-09-24",
    "2018-10-01:2018-10-05", "2018-12-31:2019-01-01", "2019-02-04:2019-02-08", "2019-04-05",
    "2019-05-01:2019-05-03", "2019-06-07", "2019-09-13", "2019-10-01:2019-10-07",
    "2020-01-01", "2020-01-24:2020-01-31", "2020-04-06", "2020-05-01:2020-05-05",
    "2020-06-25:2020-06-26", "2020-10-01:2020-10-08", "2021-01-01", "2021-02-11:2021-02-17",
    "2021-04-05", "2021-05-03:2021-05-05", "2021-06-14", "2021-09-20:2021-09-21",
    "2021-10-01:2021-10-07", "2022-01-03", "2022-01-31:2022-02-04", "2022-04-04:2022-04-05",
    "2022-05-02:2022-05-04", "2022-06-03", "2022-09-12", "2022-10-03:2022-10-07",
    "2023-01-02", "2023-01-23:2023-01-27", "2023-04-05", "2023-05-01:2023-05-03",
    "2023-06-22:2023-06-23", "2023-09-29:2023-10-06", "2024-01-01", "2024-02-09:2024-02-16",
    "2024-04-04:2024-04-05", "2024-05-01:2024-05-03", "2024-06-10", "2024-09-16:2024-09-17",
    "2024-10-01:2024-10-07", "2025-01-01", "2025-01-28:2025-02-04", "2025-04-04",
    "2025-05-01:2025-05-05", "2025-06-02", "2025-10-01:2025-10-08", "2026-01-01:2026-01-02",
    "2026-02-16:2026-02-23", "2026-04-06", "2026-05-01:2026-05-05", "2026-06-19",
    "2026-09-25", "2026-10-01:2026-10-07",
)


@dataclass
class PipelineResult:
    histories: Dict[str, pd.DataFrame]
    metrics: List[FundMetrics]
    quality: List[QualityReport]
    events: List[EventRecord]
    recommendations: List[Recommendation]
    profile: dict
    fetched_at: str

    @property
    def metrics_frame(self) -> pd.DataFrame:
        return pd.DataFrame([metric.as_dict() for metric in self.metrics])

    @property
    def recommendations_frame(self) -> pd.DataFrame:
        return pd.DataFrame([item.as_dict() for item in self.recommendations])

    @property
    def quality_frame(self) -> pd.DataFrame:
        rows = []
        for item in self.quality:
            rows.append(
                {
                    "code": item.code,
                    "rows": item.rows,
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "duplicate_rows": item.duplicate_rows,
                    "missing_dates": item.missing_dates,
                    "invalid_values": item.invalid_values,
                    "quality_score": item.quality_score,
                    "status": item.status,
                    "warnings": "；".join(item.warnings) or "无",
                }
            )
        return pd.DataFrame(rows)


def _union_calendar(histories: Sequence[pd.DataFrame]) -> List[pd.Timestamp]:
    """Exchange trading days actually observed across the fetched funds."""
    dates = set()
    for history in histories:
        if history is None or history.empty or "trade_date" not in history:
            continue
        dates.update(pd.to_datetime(history["trade_date"]).dt.normalize().tolist())
    return sorted(dates)


def load_trading_calendar(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> List[pd.Timestamp]:
    """Return reference exchange trading days independent of user fund selection."""
    start_dt = pd.Timestamp(start or date(2017, 1, 1)).normalize()
    end_dt = pd.Timestamp(end or date.today()).normalize()
    if end_dt < start_dt:
        return []
    weekdays = pd.bdate_range(start_dt, end_dt)
    closures = set()
    for entry in _CN_MARKET_CLOSURES:
        if ":" in entry:
            left, right = entry.split(":", 1)
            closures.update(pd.bdate_range(left, right))
        else:
            closures.add(pd.Timestamp(entry).normalize())
    return sorted(set(weekdays) - closures)


def run_pipeline(
    codes: Sequence[str],
    source_mode: str = "demo",
    start: Optional[date] = None,
    end: Optional[date] = None,
    aggression: int = 45,
    max_drawdown: float = 15.0,
    horizon_days: int = 20,
    commission_bps: float = 2.5,
    slippage_bps: float = 5.0,
    annual_fee_rate: float = 0.005,
    profiles: Optional[Sequence[FundProfile]] = None,
) -> PipelineResult:
    profile_list = list(profiles or DEFAULT_FUNDS)
    profile_map = {profile.code: profile for profile in profile_list}
    connector = CompositeConnector(source_mode, profile_list)
    histories: Dict[str, pd.DataFrame] = {}
    metrics: List[FundMetrics] = []
    quality: List[QualityReport] = []
    events: List[EventRecord] = []
    end = end or date.today()
    start = start or max(date(2017, 1, 1), end - timedelta(days=365 * 8))
    valid_codes = [code for code in codes if code in profile_map]

    def fetch_one(code: str):
        history, source = connector.fetch_history(code, start, end)
        return code, history, source, connector.fetch_events(code)

    # Yahoo history and news are network-bound. Fetch each selected fund in its
    # own worker so a slow symbol does not block all other symbols in sequence.
    workers = min(4, max(1, len(valid_codes))) if source_mode in {"auto", "yahoo", "eastmoney"} else 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        fetched = list(executor.map(fetch_one, valid_codes))

    # Use a fixed reference exchange calendar so missing-day counts, gap-return
    # exclusion and volatility stay identical whether 1 fund or 15 funds are selected.
    calendar = load_trading_calendar(start, end)
    if not calendar:
        calendar = _union_calendar([history for _, history, _, _ in fetched])

    actions = load_actions()

    for code, history, source, code_events in fetched:
        is_demo = "演示数据" in source
        eval_calendar = None if is_demo else calendar

        standardized, action_status = standardize(history, code, actions.get(code, []))
        clean = normalize_history(standardized, code)
        report = validate_history(standardized, code, trading_days=eval_calendar)
        histories[code] = clean
        quality.append(report)
        profile = profile_map[code]
        events.extend(history.attrs.get("chart_events", []) or [])
        events.extend(code_events)
        if not clean.empty:
            metric = calculate_metrics(
                clean,
                code,
                profile.name,
                profile.category,
                report,
                source,
                trading_days=eval_calendar,
            )
            metric.price_basis = "demo" if is_demo else "split_adjusted_close"
            metric.corporate_action_status = action_status
            metric.source_check_status = history.attrs.get(
                "source_check_status", "demo" if is_demo else "verified"
            )
            metrics.append(metric)
    recommendations, profile = build_personalized_recommendations(
        metrics,
        aggression=aggression,
        max_drawdown=max_drawdown,
        horizon_days=horizon_days,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        annual_fee_rate=annual_fee_rate,
    )
    fetched_at = datetime.now(BEIJING_TZ).isoformat(timespec="seconds")
    return PipelineResult(histories, metrics, quality, events, recommendations, profile, fetched_at)
