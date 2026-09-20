from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FundProfile:
    code: str
    name: str
    symbol: str
    market: str
    category: str
    benchmark: str
    inception_date: date


@dataclass
class QualityReport:
    code: str
    rows: int
    start_date: Optional[date]
    end_date: Optional[date]
    duplicate_rows: int
    missing_dates: int
    invalid_values: int
    quality_score: float
    warnings: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.quality_score >= 0.95:
            return "通过"
        if self.quality_score >= 0.80:
            return "需关注"
        return "不通过"


@dataclass
class FundMetrics:
    code: str
    name: str
    category: str
    latest_value: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    calmar_ratio: float
    momentum_60d: float
    win_rate: float
    current_aum: float
    avg_volume: float
    as_of: date
    quality_score: float
    source: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "latest_value": self.latest_value,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "max_drawdown": self.max_drawdown,
            "calmar_ratio": self.calmar_ratio,
            "momentum_60d": self.momentum_60d,
            "win_rate": self.win_rate,
            "current_aum": self.current_aum,
            "avg_volume": self.avg_volume,
            "as_of": self.as_of.isoformat(),
            "quality_score": self.quality_score,
            "source": self.source,
        }


@dataclass
class Recommendation:
    role: str
    code: str
    name: str
    target_weight: float
    action: str
    net_return_range: str
    max_drawdown: float
    reason: str
    evidence: List[str]
    risk_flags: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "code": self.code,
            "name": self.name,
            "target_weight": self.target_weight,
            "action": self.action,
            "net_return_range": self.net_return_range,
            "max_drawdown": self.max_drawdown,
            "reason": self.reason,
            "evidence": "；".join(self.evidence),
            "risk_flags": "；".join(self.risk_flags),
        }


@dataclass
class EventRecord:
    code: str
    title: str
    publisher: str
    published_at: datetime
    url: str
    source: str
    document_type: str = "其他公告"
    evidence_level: str = "待核验"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "publisher": self.publisher,
            "published_at": self.published_at.strftime("%Y-%m-%d %H:%M"),
            "url": self.url,
            "source": self.source,
            "document_type": self.document_type,
            "evidence_level": self.evidence_level,
        }
