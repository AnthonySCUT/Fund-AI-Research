"""Price standardization for split-adjusted price returns.

The module is deliberately fund-agnostic: verified corporate actions come from a
data file (``data/corporate_actions.json``), and any discontinuity that the file
does not cover is detected from the price series itself and marked unverified.
No fund code is special-cased anywhere in this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

DEFAULT_ACTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "corporate_actions.json"

# A single trading day losing this much is treated as a share-unit change rather
# than a market move: an index ETF cannot genuinely fall 40% in one session.
DETECT_THRESHOLD = 0.40
# The observed ratio and the announced ratio are considered the same event when
# they agree within this relative tolerance.
RATIO_TOLERANCE = 0.15


@dataclass(frozen=True)
class CorporateAction:
    code: str
    ex_date: date
    ratio: float
    kind: str = "split"
    verified: bool = False
    evidence: str = ""


def load_actions(path: Optional[Path] = None) -> Dict[str, List[CorporateAction]]:
    """Read verified corporate actions keyed by fund code.

    A missing or malformed file yields an empty mapping so the pipeline keeps
    working for funds that never had a corporate action.
    """
    target = Path(path) if path is not None else DEFAULT_ACTIONS_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    actions: Dict[str, List[CorporateAction]] = {}
    for item in payload.get("actions", []) if isinstance(payload, dict) else []:
        try:
            action = CorporateAction(
                code=str(item["code"]).strip(),
                ex_date=date.fromisoformat(str(item["ex_date"])[:10]),
                ratio=float(item["ratio"]),
                kind=str(item.get("kind", "split")),
                verified=bool(item.get("verified", False)),
                evidence=str(item.get("evidence", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not action.code or action.ratio <= 0:
            continue
        actions.setdefault(action.code, []).append(action)
    for items in actions.values():
        items.sort(key=lambda entry: entry.ex_date)
    return actions


def _as_dates(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["trade_date"]).dt.normalize()


def detect_candidates(
    frame: pd.DataFrame,
    code: str,
    threshold: float = DETECT_THRESHOLD,
) -> List[CorporateAction]:
    """Find share-unit discontinuities inside a single source series."""
    if frame is None or len(frame) < 2:
        return []

    dates = _as_dates(frame)
    close = pd.to_numeric(frame["close"], errors="coerce")
    returns = close.pct_change(fill_method=None)

    candidates: List[CorporateAction] = []
    for position in np.flatnonzero(np.asarray(returns.to_numpy() <= -threshold)):
        if position == 0:
            continue
        previous = float(close.iloc[position - 1])
        current = float(close.iloc[position])
        if previous <= 0 or current <= 0:
            continue
        candidates.append(
            CorporateAction(
                code=code,
                ex_date=dates.iloc[position].date(),
                ratio=round(previous / current, 4),
                kind="split",
                verified=False,
                evidence="单源单日跌幅超过阈值，自动检测",
            )
        )
    return candidates


def _match_verified(
    verified: Sequence[CorporateAction],
    ex_date: date,
) -> Optional[CorporateAction]:
    for action in verified:
        if action.ex_date == ex_date:
            return action
    return None


def standardize(
    frame: pd.DataFrame,
    code: str,
    verified_actions: Optional[Sequence[CorporateAction]] = None,
) -> Tuple[pd.DataFrame, str]:
    """Return (split-adjusted frame, corporate action status).

    The adjustment is applied only where this particular source *shows* a
    discontinuity. A source that already delivers a continuous series (for
    example an adjusted feed) is therefore never adjusted twice.

    Status values:
        ``none``            no corporate action applies to this series
        ``split_adjusted``  every applied factor has announcement evidence
        ``unverified``      at least one factor came from detection only
    """
    if frame is None or frame.empty:
        return frame, "none"

    working = frame.copy()
    working.attrs = dict(frame.attrs)
    working = working.assign(trade_date=_as_dates(working))
    working = (
        working.sort_values("trade_date")
        .drop_duplicates("trade_date", keep="last")
        .reset_index(drop=True)
    )

    raw_close = pd.to_numeric(working["close"], errors="coerce")
    working["raw_close"] = raw_close
    verified = list(verified_actions or [])

    applied: List[Tuple[date, float, bool]] = []
    for candidate in detect_candidates(working, code):
        announced = _match_verified(verified, candidate.ex_date)
        if announced is not None:
            # The announcement is authoritative even when its ratio differs
            # slightly from the observed one; the difference is a data point
            # for the reconciliation report, not a reason to guess.
            applied.append((announced.ex_date, announced.ratio, True))
        else:
            applied.append((candidate.ex_date, candidate.ratio, False))

    factor = pd.Series(1.0, index=working.index, dtype="float64")
    for ex_date, ratio, _ in applied:
        factor.loc[working["trade_date"] < pd.Timestamp(ex_date)] /= ratio

    working["split_factor"] = factor
    working["adjust_state"] = np.where(factor.to_numpy() == 1.0, "raw", "adjusted")
    working["close"] = raw_close * working["split_factor"]

    if applied:
        status = "split_adjusted" if all(flag for _, _, flag in applied) else "unverified"
    elif verified:
        # A verified action exists for this code but this source already
        # delivers a continuous series, so no adjustment was needed.
        status = "split_adjusted"
    else:
        status = "none"
    return working, status
