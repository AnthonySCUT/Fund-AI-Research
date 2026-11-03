from datetime import date

from fund_api import FundResearchClient, FundResearchRequest


request = FundResearchRequest(
    codes=["510300", "510500"],
    start=date(2018, 1, 1),
    end=date.today(),
    aggression=45,
    max_drawdown=15,
    horizon_days=20,
)
response = FundResearchClient().research(request)
print({
    "fetched_at": response.fetched_at,
    "cache_hit": response.cache_hit,
    "cache_expires_at": response.cache_expires_at,
    "recommendation_count": len(response.recommendations),
    "research_card_count": len(response.research_cards),
})
