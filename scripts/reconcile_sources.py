"""Compare the two market-data sources for the whole ETF universe.

This is an offline evidence tool: it never runs inside the app. For every fund
it fetches Yahoo (unadjusted ``close``) and Eastmoney (``fqt=0``) histories,
aligns them on the dates both sources report, and prints the metrics before and
after price standardization as well as the dual-source selection outcome.

Outputs:
    data/reconciliation/summary.json
    data/reconciliation/summary.md

Environment:
    RESEARCH_RECONCILE_START  default 2024-01-01
    RESEARCH_RECONCILE_END    default today
    RESEARCH_RECONCILE_CODES  comma separated subset, default all 15
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fund_ai_research.adjustments import detect_candidates, load_actions, standardize  # noqa: E402
from fund_ai_research.analytics import calculate_metrics, validate_history  # noqa: E402
from fund_ai_research.connectors import (  # noqa: E402
    DEFAULT_FUNDS,
    DataFetchError,
    EastmoneyConnector,
    YahooFinanceConnector,
    cross_verify_sources,
)
from fund_ai_research.pipeline import load_trading_calendar  # noqa: E402

OUTPUT_DIR = ROOT / "data" / "reconciliation"


def _parse_date(name: str, default: date) -> date:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return default


def _fetch_with_retry(connector, code, start, end, attempts: int = 3, **kwargs) -> pd.DataFrame:
    """Public endpoints drop connections intermittently; retry before giving up."""
    last_error = None
    for attempt in range(attempts):
        try:
            return connector.fetch_history(code, start, end, **kwargs)
        except DataFetchError as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise DataFetchError(str(last_error))


def _slice(frame: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.normalize()
    return working[working["trade_date"].isin(dates)].reset_index(drop=True)


def _metrics(
    frame: pd.DataFrame,
    profile,
    calendar,
    source: str,
    corporate_action_status: str = "none",
) -> dict:
    report = validate_history(frame, profile.code, trading_days=calendar)
    metric = calculate_metrics(
        frame,
        profile.code,
        profile.name,
        profile.category,
        report,
        source,
        trading_days=calendar,
    )
    metric.price_basis = source
    metric.corporate_action_status = corporate_action_status
    return {
        "total_return": round(metric.total_return, 6),
        "annualized_return": round(metric.annualized_return, 6),
        "annualized_volatility": round(metric.annualized_volatility, 6),
        "max_drawdown": round(metric.max_drawdown, 6),
        "quality_score": metric.quality_score,
        "rows": report.rows,
        "missing_dates": report.missing_dates,
        "missing_policy": metric.missing_policy,
        "corporate_action_status": metric.corporate_action_status,
    }


def _diff(left: dict, right: dict, key: str) -> float:
    return round(abs(float(left[key]) - float(right[key])), 6)


def _level_ratio(yahoo: pd.DataFrame, eastmoney: pd.DataFrame) -> float:
    """Median price level ratio between the two sources on common dates."""
    merged = yahoo[["trade_date", "close"]].merge(
        eastmoney[["trade_date", "close"]], on="trade_date", suffixes=("_y", "_e")
    )
    ratio = merged["close_y"] / merged["close_e"].replace(0, np.nan)
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
    return float(round(ratio.median(), 4)) if not ratio.empty else float("nan")


def reconcile(code: str, profile, start: date, end: date, actions) -> dict:
    yahoo = YahooFinanceConnector([profile])
    eastmoney = EastmoneyConnector([profile])

    raw_yahoo = _fetch_with_retry(yahoo, code, start, end)
    raw_eastmoney = _fetch_with_retry(eastmoney, code, start, end, fqt="0")
    raw_yahoo["trade_date"] = pd.to_datetime(raw_yahoo["trade_date"]).dt.normalize()
    raw_eastmoney["trade_date"] = pd.to_datetime(raw_eastmoney["trade_date"]).dt.normalize()

    union = pd.DatetimeIndex(
        sorted(set(raw_yahoo["trade_date"]) | set(raw_eastmoney["trade_date"]))
    )
    common = pd.DatetimeIndex(
        sorted(set(raw_yahoo["trade_date"]) & set(raw_eastmoney["trade_date"]))
    )
    if len(common) < 30:
        raise DataFetchError(f"{code} 共同交易日不足：{len(common)}")

    ref_calendar = load_trading_calendar(start, end) or list(union)
    quality_full = {
        "yahoo": validate_history(raw_yahoo, code, trading_days=ref_calendar),
        "eastmoney": validate_history(raw_eastmoney, code, trading_days=ref_calendar),
    }

    aligned_yahoo = _slice(raw_yahoo, common)
    aligned_eastmoney = _slice(raw_eastmoney, common)

    std_yahoo, status_y = standardize(raw_yahoo, code, actions.get(code, []))
    std_eastmoney, status_e = standardize(raw_eastmoney, code, actions.get(code, []))
    std_yahoo_common = _slice(std_yahoo, common)
    std_eastmoney_common = _slice(std_eastmoney, common)

    before = {
        "yahoo": _metrics(aligned_yahoo, profile, common, "yahoo:quote.close", "none"),
        "eastmoney": _metrics(aligned_eastmoney, profile, common, "eastmoney:fqt=0", "none"),
    }
    after = {
        "yahoo": _metrics(std_yahoo_common, profile, common, "yahoo:quote.close", status_y),
        "eastmoney": _metrics(std_eastmoney_common, profile, common, "eastmoney:fqt=0", status_e),
    }

    level = _level_ratio(raw_yahoo, raw_eastmoney)
    check = cross_verify_sources(raw_yahoo, raw_eastmoney, code, actions.get(code, []))
    selected_source = check["selected"]
    selected_frame = std_yahoo if selected_source == "yahoo" else std_eastmoney
    selected_source_name = "yahoo:quote.close" if selected_source == "yahoo" else "eastmoney:fqt=0"
    selected_status = status_y if selected_source == "yahoo" else status_e
    selected_metrics = _metrics(
        selected_frame, profile, ref_calendar, selected_source_name, selected_status
    )

    return {
        "code": code,
        "name": profile.name,
        "common_dates": int(len(common)),
        "yahoo_only": int(len(set(raw_yahoo["trade_date"]) - set(common))),
        "eastmoney_only": int(len(set(raw_eastmoney["trade_date"]) - set(common))),
        "level_ratio_yahoo_over_eastmoney": level,
        "level_mismatch": bool(not np.isnan(level) and abs(level - 1.0) > 0.05),
        "selection": {
            "selected_source": selected_source,
            "source_check_status": check["source_check_status"],
            "reason": check["reason"],
            "anomaly_dates": check["anomaly_dates"],
        },
        "selected_metrics": selected_metrics,
        "detected": {
            "yahoo": [
                {"ex_date": action.ex_date.isoformat(), "ratio": action.ratio, "verified": action.verified}
                for action in detect_candidates(raw_yahoo, code)
            ],
            "eastmoney": [
                {"ex_date": action.ex_date.isoformat(), "ratio": action.ratio, "verified": action.verified}
                for action in detect_candidates(raw_eastmoney, code)
            ],
        },
        "quality_full": {
            side: {
                "rows": report.rows,
                "missing_dates": report.missing_dates,
                "quality_score": report.quality_score,
            }
            for side, report in quality_full.items()
        },
        "standardization_status": {"yahoo": status_y, "eastmoney": status_e},
        "before": before,
        "after": after,
        "diff_before": {
            "annualized_return": _diff(before["yahoo"], before["eastmoney"], "annualized_return"),
            "annualized_volatility": _diff(before["yahoo"], before["eastmoney"], "annualized_volatility"),
            "max_drawdown": _diff(before["yahoo"], before["eastmoney"], "max_drawdown"),
        },
        "diff_after": {
            "annualized_return": _diff(after["yahoo"], after["eastmoney"], "annualized_return"),
            "annualized_volatility": _diff(after["yahoo"], after["eastmoney"], "annualized_volatility"),
            "max_drawdown": _diff(after["yahoo"], after["eastmoney"], "max_drawdown"),
        },
    }


def _markdown(rows: list[dict], start: date, end: date) -> str:
    lines = [
        "# 主备源标准化对账",
        "",
        f"- 区间：{start.isoformat()} 至 {end.isoformat()}",
        f"- 生成时间：{pd.Timestamp.now().isoformat(timespec='seconds')}",
        "- 口径：拆分调整后价格收益，现金分红不进入再投资",
        "- 比较基准：两源共同交易日集合",
        "",
        "| 代码 | 名称 | 共同日 | 标准化前年化差 | 标准化后年化差 | 波动差 | 回撤差 | 源间价位比 | 拆分状态(源/东财) | 选源决策 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        selection = row.get("selection", {})
        sel_label = f"{selection.get('selected_source', 'yahoo')} ({selection.get('source_check_status', 'verified')})"
        lines.append(
            "| {code} | {name} | {common} | {b:.4%} | {a:.4%} | {v:.4%} | {d:.4%} | {lvl} | {sy}/{se} | {sel} |".format(
                code=row["code"],
                name=row["name"],
                common=row["common_dates"],
                b=row["diff_before"]["annualized_return"],
                a=row["diff_after"]["annualized_return"],
                v=row["diff_after"]["annualized_volatility"],
                d=row["diff_after"]["max_drawdown"],
                lvl=row["level_ratio_yahoo_over_eastmoney"],
                sy=row["standardization_status"]["yahoo"],
                se=row["standardization_status"]["eastmoney"],
                sel=sel_label,
            )
        )
    mismatches = [row["code"] for row in rows if row["level_mismatch"]]
    if mismatches:
        lines += [
            "",
            f"**源间价位不一致（需人工核实价格单位/公司行动）：** {', '.join(mismatches)}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    start = _parse_date("RESEARCH_RECONCILE_START", date(2024, 1, 1))
    end = _parse_date("RESEARCH_RECONCILE_END", date.today())
    wanted = [item.strip() for item in os.getenv("RESEARCH_RECONCILE_CODES", "").split(",") if item.strip()]
    profiles = [profile for profile in DEFAULT_FUNDS if not wanted or profile.code in wanted]
    actions = load_actions()

    rows: list[dict] = []
    failures: list[dict] = []
    for profile in profiles:
        try:
            rows.append(reconcile(profile.code, profile, start, end, actions))
            print(f"[ok] {profile.code} {profile.name}")
        except (DataFetchError, ValueError, KeyError) as exc:
            failures.append({"code": profile.code, "error": str(exc)})
            print(f"[fail] {profile.code} {exc}")

    if not rows:
        # Never replace a previous good evidence file with an empty one.
        print("没有成功对账的基金，保留原有证据文件不变")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "basis": "split_adjusted_close_price_return",
        "funds": rows,
        "failures": failures,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "summary.md").write_text(_markdown(rows, start, end), encoding="utf-8")

    print(f"\n{len(rows)} funds reconciled, {len(failures)} failed")
    print(f"written: {OUTPUT_DIR / 'summary.json'}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
