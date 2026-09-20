import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

import requests

from .models import EventRecord, FundMetrics, QualityReport


FIVE_YEAR_TEN_X_ANNUALIZED = 10 ** (1 / 5) - 1

# Stable import surface used by the Streamlit app and scheduled job.  Keeping
# this explicit makes a partial or stale deployment fail at the module API
# boundary instead of with an ambiguous attribute lookup in the app.
__all__ = [
    "FIVE_YEAR_TEN_X_ANNUALIZED",
    "OpenAICompatibleAnalyzer",
    "ResearchCard",
    "analyze_metrics",
]


def _setting(name: str) -> Optional[str]:
    """Read a string setting from env first, then Streamlit Secrets.

    Streamlit Cloud Secrets are not guaranteed to be mirrored into
    ``os.environ`` in every runtime version. Values are normalized here so a
    malformed/non-string secret cannot crash app initialization.
    """
    value = os.getenv(name)
    if value is not None and str(value).strip():
        return str(value).strip()
    if "streamlit" not in sys.modules:
        return None
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        return None
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _first_setting(*names: str) -> Optional[str]:
    for name in names:
        value = _setting(name)
        if value:
            return value
    return None


@dataclass
class ResearchCard:
    code: str
    status: str
    facts: List[str]
    positive_evidence: List[str]
    risk_signals: List[str]
    verification_questions: List[str]
    conclusion: str
    source: str
    goal_fit: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class RuleBasedResearchAnalyzer:
    """Deterministic baseline. It is intentionally explainable and works offline."""

    def analyze(self, metric: FundMetrics, quality: QualityReport, events: Iterable[EventRecord]) -> ResearchCard:
        facts = [
            f"截至 {metric.as_of.isoformat()}，最新值 {metric.latest_value:.4f}；样本质量 {quality.quality_score:.0%}。",
            f"历史累计收益 {metric.total_return:+.1%}，年化历史收益 {metric.annualized_return:+.1%}。",
            f"年化波动 {metric.annualized_volatility:.1%}，历史最大回撤 {metric.max_drawdown:.1%}。",
        ]
        goal_fit = (
            f"五年十倍目标对应约 {FIVE_YEAR_TEN_X_ANNUALIZED:.1%} 年化收益；"
            f"该标的历史样本年化收益为 {metric.annualized_return:+.1%}，仅作压力测试比较，不能外推未来。"
        )
        positive: List[str] = []
        risks: List[str] = []
        if quality.quality_score >= 0.95:
            positive.append("行情字段完整度较高，暂未发现影响计算的质量问题。")
        if metric.annualized_return > 0:
            positive.append("历史样本的年化收益为正，但不代表未来收益。")
        if metric.calmar_ratio > 0.5:
            positive.append(f"收益/回撤比为 {metric.calmar_ratio:.2f}，可作为继续研究的量化证据。")
        if abs(metric.max_drawdown) > 0.20:
            risks.append(f"历史最大回撤达到 {metric.max_drawdown:.1%}，应与用户回撤阈值核对。")
        if metric.annualized_volatility > 0.25:
            risks.append(f"年化波动达到 {metric.annualized_volatility:.1%}，战术仓需控制仓位和交易频率。")
        if quality.quality_score < 0.90:
            risks.extend(quality.warnings or ["数据质量低于 90%，不应直接形成交易结论。"])
        if not risks:
            risks.append("当前规则未触发高风险阈值，但仍需核对公开披露文件。")
        questions = [
            "核对基金合同、招募说明书、最新定期报告和跟踪误差口径。",
            "确认最新数据是否覆盖停牌、分红、拆分、合并和基金更名。",
            "将实际账户费用、滑点和持有期成本替换为当前参数后再复核。",
        ]
        event_count = sum(1 for event in events if event.code == metric.code)
        if event_count:
            questions.append(f"已抓取 {event_count} 条事件线索；逐条回到原始公告核验，不把新闻摘要当事实。")
        severe = abs(metric.max_drawdown) > 0.35 or quality.quality_score < 0.80
        caution = abs(metric.max_drawdown) > 0.20 or metric.annualized_volatility > 0.25 or quality.quality_score < 0.95
        status = "红灯" if severe else ("黄灯" if caution else "绿灯")
        conclusion = {
            "绿灯": "可继续研究：量化指标和数据质量暂未触发明显硬阈值。",
            "黄灯": "等待验证：存在回撤、波动或数据口径风险，暂不因故事买入。",
            "红灯": "不碰：风险信号与数据/回撤约束叠加，先完成核查。",
        }[status]
        return ResearchCard(metric.code, status, facts, positive, risks, questions, conclusion, "规则化基线", goal_fit)


class OpenAICompatibleAnalyzer:
    """Optional JSON analyzer for an OpenAI-compatible endpoint.

    Provider-specific configuration is explicit so Grok can be the primary
    provider and DeepSeek can be used as a separate fallback.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: str = "auto",
    ):
        provider = str(provider or "auto").lower().strip()
        if provider not in {"auto", "grok", "deepseek"}:
            raise ValueError("provider must be auto, grok, or deepseek")
        self.provider = provider

        if provider == "grok":
            key_name, url_name, model_name = "GROK_API_KEY", "GROK_BASE_URL", "GROK_MODEL"
            default_url, default_model = "https://api.x.ai/v1", "grok-4.5"
        elif provider == "deepseek":
            key_name, url_name, model_name = "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"
            default_url, default_model = "https://api.deepseek.com/v1", "deepseek-chat"
        else:
            key_name = url_name = model_name = ""
            default_url, default_model = "https://api.openai.com/v1", "gpt-4o-mini"

        if provider == "auto":
            # Provider-neutral aliases remain supported for local experiments.
            self.api_key = api_key or _first_setting("LLM_API_KEY", "GROK_API_KEY", "DEEPSEEK_API_KEY")
            selected_url = base_url or _first_setting("LLM_BASE_URL", "GROK_BASE_URL", "DEEPSEEK_BASE_URL") or default_url
            selected_model = model or _first_setting("LLM_MODEL", "GROK_MODEL", "DEEPSEEK_MODEL") or default_model
        else:
            self.api_key = str(api_key).strip() if api_key else _setting(key_name)
            selected_url = base_url or _setting(url_name) or default_url
            selected_model = model or _setting(model_name) or default_model
        self.api_key = str(self.api_key).strip() if self.api_key else None
        self.base_url = str(selected_url).strip().rstrip("/")
        self.model = str(selected_model).strip()
        try:
            timeout_name = "DEEPSEEK_TIMEOUT_SECONDS" if provider == "deepseek" else "GROK_TIMEOUT_SECONDS"
            timeout_value = _first_setting("LLM_TIMEOUT_SECONDS", timeout_name) or "20"
            self.timeout = max(5, int(timeout_value))
        except (TypeError, ValueError):
            self.timeout = 20

    @property
    def label(self) -> str:
        return f"{self.provider.title() if self.provider != 'auto' else 'LLM'}:{self.model}"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze(self, metric: FundMetrics, quality: QualityReport, events: Iterable[EventRecord]) -> Optional[ResearchCard]:
        if not self.enabled:
            return None
        event_rows = [event.as_dict() for event in events if event.code == metric.code]
        prompt = {
            "role": "审慎的基本面与治理结构研究员",
            "rules": [
                "只基于输入事实，不得补写未提供的公告内容",
                "区分已披露事实、风险信号、仍需验证问题和普通投资者研究结论",
                "证据不足写未找到公开证据，不输出买卖指令或收益承诺",
                f"将五年十倍目标换算为约 {FIVE_YEAR_TEN_X_ANNUALIZED:.1%} 年化门槛，只作压力测试，不得承诺达到",
                "报告类公告要标注文档类型、发布日期和原文链接；公告索引不能替代原文核验",
            ],
            "metric": metric.as_dict(),
            "quality": {"score": quality.quality_score, "warnings": quality.warnings},
            "events": event_rows,
            "output_schema": {
                "status": "绿灯/黄灯/红灯",
                "facts": ["string"],
                "positive_evidence": ["string"],
                "risk_signals": ["string"],
                "verification_questions": ["string"],
                "conclusion": "string",
                "goal_fit": "string",
            },
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "只输出符合 schema 的 JSON。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            content = content.strip().removeprefix("```json").removesuffix("```").strip()
            parsed = json.loads(content)
            return ResearchCard(
                code=metric.code,
                status=parsed.get("status", "黄灯"),
                facts=parsed.get("facts", []),
                positive_evidence=parsed.get("positive_evidence", []),
                risk_signals=parsed.get("risk_signals", []),
                verification_questions=parsed.get("verification_questions", []),
                conclusion=parsed.get("conclusion", "等待人工复核。"),
                source=self.label,
                goal_fit=parsed.get("goal_fit", ""),
            )
        except (requests.RequestException, KeyError, IndexError, ValueError, json.JSONDecodeError):
            return None

    def analyze_many(
        self,
        metrics: Iterable[FundMetrics],
        quality: Iterable[QualityReport],
        events: Iterable[EventRecord],
    ) -> Dict[str, ResearchCard]:
        """Analyze all selected funds in one request to avoid N sequential calls."""
        metric_list = list(metrics)
        quality_map = {item.code: item for item in quality}
        event_list = list(events)
        prompt = {
            "role": "审慎的基本面与治理结构研究员",
            "rules": [
                "只基于输入事实，不得补写未提供的公告内容",
                "区分已披露事实、风险信号、仍需验证问题和普通投资者研究结论",
                "证据不足写未找到公开证据，不输出买卖指令或收益承诺",
                f"将五年十倍目标换算为约 {FIVE_YEAR_TEN_X_ANNUALIZED:.1%} 年化门槛，只作压力测试，不得承诺达到",
                "报告类公告要标注文档类型、发布日期和原文链接；公告索引不能替代原文核验",
            ],
            "funds": [
                {
                    "metric": metric.as_dict(),
                    "quality": {"score": quality_map[metric.code].quality_score, "warnings": quality_map[metric.code].warnings},
                    "events": [event.as_dict() for event in event_list if event.code == metric.code],
                }
                for metric in metric_list
            ],
            "output_schema": {
                "cards": [
                    {
                        "code": "string",
                        "status": "绿灯/黄灯/红灯",
                        "facts": ["string"],
                        "positive_evidence": ["string"],
                        "risk_signals": ["string"],
                        "verification_questions": ["string"],
                        "conclusion": "string",
                        "goal_fit": "string",
                    }
                ]
            },
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "只输出符合 schema 的 JSON。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            content = content.strip().removeprefix("```json").removesuffix("```").strip()
            parsed = json.loads(content)
            cards: Dict[str, ResearchCard] = {}
            for item in parsed.get("cards", []):
                code = item.get("code")
                if not code or code not in quality_map:
                    continue
                cards[code] = ResearchCard(
                    code=code,
                    status=item.get("status", "黄灯"),
                    facts=item.get("facts", []),
                    positive_evidence=item.get("positive_evidence", []),
                    risk_signals=item.get("risk_signals", []),
                    verification_questions=item.get("verification_questions", []),
                    conclusion=item.get("conclusion", "等待人工复核。"),
                    source=self.label,
                    goal_fit=item.get("goal_fit", ""),
                )
            return cards
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return {}


def analyze_metrics(metrics: Iterable[FundMetrics], quality: Iterable[QualityReport], events: Iterable[EventRecord]) -> Dict[str, ResearchCard]:
    quality_map = {item.code: item for item in quality}
    event_list = list(events)
    baseline = RuleBasedResearchAnalyzer()
    cards: Dict[str, ResearchCard] = {}
    metric_list = list(metrics)
    # Grok is primary. DeepSeek is tried for provider failures or partial
    # output. Both receive only structured facts already fetched by connectors.
    remaining = list(metric_list)
    for provider in ("grok", "deepseek"):
        if not remaining:
            break
        analyzer = OpenAICompatibleAnalyzer(provider=provider)
        if not analyzer.enabled:
            continue
        provider_cards = analyzer.analyze_many(
            remaining,
            [quality_map[item.code] for item in remaining],
            event_list,
        )
        cards.update(provider_cards)
        remaining = [item for item in remaining if item.code not in cards]
    for metric in metric_list:
        cards[metric.code] = cards.get(metric.code) or baseline.analyze(metric, quality_map[metric.code], event_list)
    return cards
