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
    """Exchange trading days actually observed across the fetched funds.

    Deriving the calendar from the data avoids a hard-coded holiday list and
    keeps the check fund-agnostic: a date missing from every source is a
    holiday, not a data gap.
    """
    dates = set()
    for history in histories:
        if history is None or history.empty or "trade_date" not in history:
            continue
        dates.update(pd.to_datetime(history["trade_date"]).dt.normalize().tolist())
    return sorted(dates)


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

    # The union of the fetched dates is the exchange calendar for this run:
    # holidays are absent from every source, so they are never counted missing.
    calendar = _union_calendar([history for _, history, _, _ in fetched])
    actions = load_actions()

    for code, history, source, code_events in fetched:
        standardized, action_status = standardize(history, code, actions.get(code, []))
        clean = normalize_history(standardized, code)
        report = validate_history(standardized, code, trading_days=calendar)
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
                trading_days=calendar,
            )
            metric.price_basis = "demo" if "演示数据" in source else "split_adjusted_close"
            metric.corporate_action_status = action_status
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
