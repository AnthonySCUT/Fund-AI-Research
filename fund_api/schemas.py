from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FundResearchRequest:
    codes: List[str]
    start: Optional[date] = None
    end: Optional[date] = None
    aggression: int = 45
    max_drawdown: float = 15.0
    horizon_days: int = 20
    commission_bps: float = 2.5
    slippage_bps: float = 5.0
    annual_fee_rate: float = 0.005

    def to_payload(self) -> Dict[str, Any]:
        payload = asdict(self)
        for key in ("start", "end"):
            if payload[key] is not None:
                payload[key] = payload[key].isoformat()
        return payload


@dataclass
class FundResearchResponse:
    fetched_at: Optional[str] = None
    cache_hit: Optional[bool] = None
    cache_expires_at: Optional[str] = None
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    research_cards: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "FundResearchResponse":
        return cls(
            fetched_at=payload.get("fetched_at"),
            cache_hit=payload.get("cache_hit"),
            cache_expires_at=payload.get("cache_expires_at"),
            recommendations=payload.get("recommendations", []),
            research_cards=payload.get("research_cards", []),
            sources=payload.get("sources", payload.get("data_sources", [])),
            raw=payload,
        )
