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

from fund_ai_research.analysis import analyze_metrics  # noqa: E402
from fund_ai_research.connectors import DEFAULT_FUNDS  # noqa: E402
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


def build_snapshot() -> dict:
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
    cards = analyze_metrics(result.metrics, result.quality, result.events)
    return {
        "fetched_at": result.fetched_at,
        "source_mode": os.getenv("RESEARCH_SOURCE_MODE", "auto"),
        "profile": result.profile,
        "metrics": [item.as_dict() for item in result.metrics],
        "quality": result.quality_frame.to_dict(orient="records"),
        "events": [item.as_dict() for item in result.events],
        "recommendations": [item.as_dict() for item in result.recommendations],
        "research_cards": [item.as_dict() for item in cards.values()],
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
