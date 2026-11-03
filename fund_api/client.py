import os
from typing import Optional

import requests

from .schemas import FundResearchRequest, FundResearchResponse


class FundResearchAPIError(RuntimeError):
    """Raised when the research service returns an invalid response."""


class FundResearchClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = (base_url or os.getenv("FUND_RESEARCH_API_URL", "")).rstrip("/")
        self.token = token or os.getenv("FUND_RESEARCH_API_TOKEN")
        self.timeout = timeout
        self.session = session or requests.Session()
        if not self.base_url:
            raise ValueError("FUND_RESEARCH_API_URL is required")
        if not self.token:
            raise ValueError("FUND_RESEARCH_API_TOKEN is required")

    def research(self, request: FundResearchRequest) -> FundResearchResponse:
        response = self.session.post(
            f"{self.base_url}/v1/research",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json=request.to_payload(),
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise FundResearchAPIError(f"Research request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise FundResearchAPIError("Research service returned a non-object JSON response")
        return FundResearchResponse.from_payload(payload)
