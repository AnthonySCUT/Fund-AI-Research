from datetime import date
from typing import Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from .models import FundMetrics, QualityReport


REQUIRED_COLUMNS = {"trade_date", "close", "aum", "volume"}


def normalize_history(history: pd.DataFrame, code: str) -> pd.DataFrame:
    frame = history.copy()
    rename_map = {"date": "trade_date", "price": "close", "nav": "close"}
    frame = frame.rename(columns={k: v for k, v in rename_map.items() if k in frame.columns})
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for column in ("close", "aum", "volume"):
        if column not in frame:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["code"] = code
    frame = frame.dropna(subset=["trade_date", "close"])
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    frame["daily_return"] = frame["close"].pct_change().fillna(0.0)
    frame["cumulative_return"] = (1.0 + frame["daily_return"]).cumprod() - 1.0
    running_peak = frame["close"].cummax()
    frame["drawdown"] = frame["close"] / running_peak - 1.0
    frame["rolling_vol_20d"] = frame["daily_return"].rolling(20).std() * np.sqrt(252)
    return frame.reset_index(drop=True)


def validate_history(history: pd.DataFrame, code: str) -> QualityReport:
    missing_columns = REQUIRED_COLUMNS.difference(history.columns)
    frame = normalize_history(history, code)
    raw_dates = pd.to_datetime(history.get("trade_date", history.get("date")), errors="coerce")
    duplicate_rows = int(raw_dates.duplicated().sum()) if raw_dates is not None else 0
    invalid_values = int((frame[["close", "aum", "volume"]] < 0).sum().sum())
    missing_dates = 0
    if len(frame) >= 2:
        expected = pd.date_range(frame["trade_date"].min(), frame["trade_date"].max(), freq="B")
        missing_dates = max(0, len(expected.difference(frame["trade_date"])))
    warnings: List[str] = []
    if missing_columns:
        warnings.append(f"缺少字段：{', '.join(sorted(missing_columns))}")
    if duplicate_rows:
        warnings.append(f"发现 {duplicate_rows} 条重复日期记录，已保留最后一条")
    if missing_dates:
        warnings.append(f"工作日序列缺失 {missing_dates} 天；节假日和停牌需人工确认")
    if invalid_values:
        warnings.append(f"发现 {invalid_values} 个负值字段")
    score = 1.0
    score -= min(0.35, duplicate_rows / max(1, len(history)) * 2)
    score -= min(0.30, missing_dates / max(1, len(frame)) * 1.5)
    score -= min(0.35, invalid_values / max(1, frame.size))
    if missing_columns:
        score -= 0.25
    if frame.empty:
        score = 0.0
        warnings.append("没有可用的有效行情记录")
    return QualityReport(
        code=code,
        rows=len(frame),
        start_date=frame["trade_date"].min().date() if not frame.empty else None,
        end_date=frame["trade_date"].max().date() if not frame.empty else None,
        duplicate_rows=duplicate_rows,
        missing_dates=missing_dates,
        invalid_values=invalid_values,
        quality_score=round(max(0.0, score), 4),
        warnings=warnings,
    )


def calculate_metrics(
    history: pd.DataFrame,
    code: str,
    name: str,
    category: str,
    quality: QualityReport,
    source: str,
) -> FundMetrics:
    frame = normalize_history(history, code)
    if frame.empty:
        raise ValueError(f"{code} 没有有效历史数据")
    returns = frame["daily_return"].replace([np.inf, -np.inf], np.nan).dropna()
    years = max((frame["trade_date"].iloc[-1] - frame["trade_date"].iloc[0]).days / 365.25, 1 / 252)
    total_return = float(frame["close"].iloc[-1] / frame["close"].iloc[0] - 1)
    annualized_return = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    annualized_volatility = float(returns.std(ddof=0) * np.sqrt(252))
    max_drawdown = float(frame["drawdown"].min())
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    momentum_60d = float(frame["close"].iloc[-1] / frame["close"].iloc[max(0, len(frame) - 61)] - 1)
    return FundMetrics(
        code=code,
        name=name,
        category=category,
        latest_value=float(frame["close"].iloc[-1]),
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        calmar_ratio=calmar_ratio,
        momentum_60d=momentum_60d,
        win_rate=float((returns > 0).mean()),
        current_aum=float(frame["aum"].iloc[-1]),
        avg_volume=float(frame["volume"].tail(60).mean()),
        as_of=frame["trade_date"].iloc[-1].date(),
        quality_score=quality.quality_score,
        source=source,
    )


def rolling_returns(history: pd.DataFrame, windows: Tuple[int, ...] = (21, 63, 252)) -> pd.DataFrame:
    """Return rolling total-return series for detail charts.

    Windows are trading-day counts.  The function keeps the date column and
    omits no rows, so callers can align it with the original history.
    """
    frame = normalize_history(history, str(history.get("code", "")))
    output = frame[["trade_date"]].copy()
    for window in windows:
        output[f"rolling_{window}d"] = frame["close"].pct_change(window)
    return output


def max_drawdown_recovery_days(history: pd.DataFrame) -> Optional[int]:
    """Return trading days needed to recover the historical worst drawdown.

    ``None`` means the series has not recovered to its prior peak by the end
    of the available sample.
    """
    frame = normalize_history(history, str(history.get("code", "")))
    if frame.empty:
        return None
    trough_index = int(frame["drawdown"].idxmin())
    recovered = frame.iloc[trough_index + 1 :]
    if recovered.empty:
        return None
    recovered = recovered[recovered["drawdown"] >= -1e-12]
    if recovered.empty:
        return None
    return int(recovered.index[0] - trough_index)


def holding_scenarios(
    metric: FundMetrics,
    horizon_days: int,
    commission_bps: float,
    slippage_bps: float,
    annual_fee_rate: float,
) -> Tuple[float, float, float]:
    horizon_years = horizon_days / 252
    gross = metric.annualized_return * horizon_years
    stress = metric.annualized_volatility * np.sqrt(horizon_years)
    round_trip_cost = 2 * (commission_bps + slippage_bps) / 10000
    fund_cost = annual_fee_rate * horizon_years
    low = gross - 0.8 * stress - round_trip_cost - fund_cost
    high = gross + 0.8 * stress - round_trip_cost - fund_cost
    return float(low), float(gross - round_trip_cost - fund_cost), float(high)
