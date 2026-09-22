"""Run the unattended research snapshot used by GitHub Actions.

The job stores only derived metrics, source links, quality reports and research
cards. API keys are read from the process environment and are never serialized.
"""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fund_ai_research.analysis import ResearchCard, analyze_metrics  # noqa: E402
from fund_ai_research.connectors import DEFAULT_FUNDS  # noqa: E402
from fund_ai_research.incremental import fingerprints_for_records, fingerprints_for_snapshot  # noqa: E402
from fund_ai_research.pipeline import run_pipeline  # noqa: E402


def _integer(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _load_previous_snapshot() -> dict:
    path = ROOT / "data" / "latest_research.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _card_from_dict(item: dict) -> ResearchCard:
    return ResearchCard(
        code=item.get("code", ""),
        status=item.get("status", "黄灯"),
        facts=item.get("facts", []),
        positive_evidence=item.get("positive_evidence", []),
        risk_signals=item.get("risk_signals", []),
        verification_questions=item.get("verification_questions", []),
        conclusion=item.get("conclusion", "等待人工复核。"),
        source=item.get("source", "后台快照"),
        goal_fit=item.get("goal_fit", ""),
    )


def build_snapshot() -> dict:
    previous_snapshot = _load_previous_snapshot()
    today = date.today()
    result = run_pipeline(
        codes=[profile.code for profile in DEFAULT_FUNDS],
        source_mode=os.getenv("RESEARCH_SOURCE_MODE", "auto"),
        start=today - timedelta(days=365 * _integer("RESEARCH_YEARS", 8)),
        end=today,
        aggression=_integer("RESEARCH_AGGRESSION", 45),
        max_drawdown=_number("RESEARCH_MAX_DRAWDOWN", 15.0),
        horizon_days=_integer("RESEARCH_HORIZON_DAYS", 20),
        commission_bps=_number("RESEARCH_COMMISSION_BPS", 2.5),
        slippage_bps=_number("RESEARCH_SLIPPAGE_BPS", 5.0),
        annual_fee_rate=_number("RESEARCH_ANNUAL_FEE_RATE", 0.005),
    )
    current_fingerprints = fingerprints_for_records(result.metrics, result.quality, result.events)
    previous_fingerprints = fingerprints_for_snapshot(previous_snapshot)
    previous_cards = {
        item.get("code"): item
        for item in previous_snapshot.get("research_cards", [])
        if item.get("code")
    }
    changed_codes = {
        code
        for code, fingerprint in current_fingerprints.items()
        if previous_fingerprints.get(code) != fingerprint or code not in previous_cards
    }
    changed_metrics = [metric for metric in result.metrics if metric.code in changed_codes]
    changed_quality = [item for item in result.quality if item.code in changed_codes]
    changed_events = [event for event in result.events if event.code in changed_codes]
    cards = {
        code: _card_from_dict(card)
        for code, card in previous_cards.items()
        if code in current_fingerprints and code not in changed_codes
    }
    cards.update(analyze_metrics(changed_metrics, changed_quality, changed_events))
    return {
        "fetched_at": result.fetched_at,
        "source_mode": os.getenv("RESEARCH_SOURCE_MODE", "auto"),
        "profile": result.profile,
        "metrics": [item.as_dict() for item in result.metrics],
        "quality": result.quality_frame.to_dict(orient="records"),
        "events": [item.as_dict() for item in result.events],
        "recommendations": [item.as_dict() for item in result.recommendations],
        "research_cards": [cards[metric.code].as_dict() for metric in result.metrics if metric.code in cards],
    }


def write_snapshot(snapshot: dict) -> None:
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "latest_research.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# AI 基金智能投研后台快照",
        "",
        f"抓取时间：{snapshot['fetched_at']}",
        f"数据模式：{snapshot['source_mode']}（价格使用真实行情回退链，事件优先使用交易所公告）",
        "",
        "## 个性化参数",
        "",
        f"核心仓：{snapshot['profile'].get('core_weight', '-')}% · "
        f"战术仓：{snapshot['profile'].get('tactical_weight', '-')}% · "
        f"现金：{snapshot['profile'].get('cash_weight', '-')}%",
        "",
        "## 指标摘要",
        "",
        "| 代码 | 基金 | 累计收益 | 年化收益 | 年化波动 | 最大回撤 | 数据源 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in snapshot["metrics"]:
        lines.append(
            f"| {item['code']} | {item['name']} | {item['total_return']:.2%} | "
            f"{item['annualized_return']:.2%} | {item['annualized_volatility']:.2%} | "
            f"{item['max_drawdown']:.2%} | {item['source']} |"
        )
    lines.extend(["", "## 研究卡片", ""])
    for card in snapshot["research_cards"]:
        lines.extend([f"### {card['code']} · {card['status']}", "", card["conclusion"], ""])
        if card.get("risk_signals"):
            lines.append("风险信号：" + "；".join(card["risk_signals"]))
            lines.append("")
    lines.extend(["## 事件线索（优先官方披露）", ""])
    if snapshot["events"]:
        for event in snapshot["events"]:
            lines.append(f"- {event['published_at']} · {event['code']} · [{event['title']}]({event['url']}) · {event['publisher']}")
    else:
        lines.append("本次未抓到匹配的官方公告；请检查交易所页面可用性和代码映射。")
    (data_dir / "latest_research.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_snapshot(build_snapshot())
    print("Wrote data/latest_research.json and data/latest_research.md")
