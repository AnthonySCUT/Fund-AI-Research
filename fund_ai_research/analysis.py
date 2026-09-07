import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

import requests

from .models import EventRecord, FundMetrics, QualityReport


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
        return ResearchCard(metric.code, status, facts, positive, risks, questions, conclusion, "规则化基线")


class OpenAICompatibleAnalyzer:
    """Optional JSON analyzer for an OpenAI-compatible endpoint.

    It is disabled unless LLM_API_KEY is explicitly configured, so the MVP never
    sends user holdings or private data by accident.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        # LLM_* is provider-neutral; GROK_* makes the Tailscale/CC Switch setup explicit.
        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("GROK_API_KEY")
        )
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("GROK_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = (
            model
            or os.getenv("LLM_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or os.getenv("GROK_MODEL")
            or "gpt-4o-mini"
        )
        try:
            self.timeout = max(5, int(os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("GROK_TIMEOUT_SECONDS") or "20"))
        except ValueError:
            self.timeout = 20

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
                source=f"LLM:{self.model}",
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
                    source=f"LLM:{self.model}",
                )
            return cards
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return {}


def analyze_metrics(metrics: Iterable[FundMetrics], quality: Iterable[QualityReport], events: Iterable[EventRecord]) -> Dict[str, ResearchCard]:
    quality_map = {item.code: item for item in quality}
    event_list = list(events)
    baseline = RuleBasedResearchAnalyzer()
    llm = OpenAICompatibleAnalyzer()
    cards: Dict[str, ResearchCard] = {}
    metric_list = list(metrics)
    llm_cards = llm.analyze_many(metric_list, quality_map.values(), event_list) if llm.enabled else {}
    for metric in metric_list:
        cards[metric.code] = llm_cards.get(metric.code) or baseline.analyze(metric, quality_map[metric.code], event_list)
    return cards
