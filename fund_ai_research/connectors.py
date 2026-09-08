from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional
from html import unescape
import re
import time
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests

from .models import EventRecord, FundProfile


class DataFetchError(RuntimeError):
    pass


DEFAULT_FUNDS: List[FundProfile] = [
    FundProfile("510300", "沪深300ETF", "510300.SS", "中国场内", "宽基指数", "沪深300", date(2013, 5, 28)),
    FundProfile("510500", "中证500ETF", "510500.SS", "中国场内", "宽基指数", "中证500", date(2013, 3, 15)),
    FundProfile("159915", "创业板ETF", "159915.SZ", "中国场内", "成长指数", "创业板指", date(2011, 12, 9)),
    FundProfile("159949", "创业板50ETF", "159949.SZ", "中国场内", "成长指数", "创业板50", date(2016, 6, 30)),
    FundProfile("513100", "纳指ETF", "513100.SS", "中国场内", "海外指数", "纳斯达克100", date(2013, 4, 25)),
]


class DemoConnector:
    """Deterministic demo data so the complete pipeline works without network access."""

    def __init__(self, profiles: Optional[Iterable[FundProfile]] = None):
        self.profiles: Dict[str, FundProfile] = {p.code: p for p in (profiles or DEFAULT_FUNDS)}

    def fetch_history(self, code: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        profile = self.profiles[code]
        start = start or max(profile.inception_date, date.today() - timedelta(days=365 * 8))
        end = end or date.today()
        dates = pd.bdate_range(start=start, end=end)
        seed = sum(ord(ch) for ch in code)
        rng = np.random.default_rng(seed)
        category_drift = {"宽基指数": 0.00025, "成长指数": 0.00038, "海外指数": 0.00033}.get(profile.category, 0.0002)
        volatility = {"宽基指数": 0.010, "成长指数": 0.016, "海外指数": 0.014}.get(profile.category, 0.012)
        shocks = rng.normal(category_drift, volatility, len(dates))
        if len(dates) > 150:
            shock_index = np.arange(130, len(dates), 263)
            shocks[shock_index] -= rng.uniform(0.025, 0.06, len(shock_index))
        price = 1.0 * np.exp(np.cumsum(shocks))
        shares = 80_000_000 * np.exp(rng.normal(0, 0.08, len(dates))).cumprod() ** 0.02
        volume = np.maximum(50_000, rng.lognormal(14.4, 0.45, len(dates)))
        return pd.DataFrame(
            {
                "trade_date": dates,
                "close": price,
                "aum": price * shares,
                "volume": volume,
                "source_id": "demo_deterministic",
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    def fetch_events(self, code: str, limit: int = 8) -> List[EventRecord]:
        profile = self.profiles[code]
        now = datetime.now()
        titles = [
            f"{profile.name}：示例公告与指数跟踪信息待核验",
            f"{profile.name}：定期报告与规模变化示例事件",
            f"{profile.name}：基准指数调整及成分变化示例",
        ]
        return [
            EventRecord(code, title, "演示数据", now - timedelta(days=i * 19), "https://example.com/demo-event", "demo")
            for i, title in enumerate(titles[:limit])
        ]


class YahooFinanceConnector:
    """Public Yahoo chart/search endpoints. Treat returned news as secondary evidence."""

    chart_url = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    search_url = "https://query1.finance.yahoo.com/v1/finance/search"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def __init__(self, profiles: Optional[Iterable[FundProfile]] = None, timeout: int = 10):
        self.profiles = {p.code: p for p in (profiles or DEFAULT_FUNDS)}
        self.timeout = timeout

    def fetch_history(self, code: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        profile = self.profiles[code]
        start = start or profile.inception_date
        end = end or date.today()
        params = {
            "period1": int(datetime.combine(start, datetime.min.time()).timestamp()),
            "period2": int(datetime.combine(end + timedelta(days=1), datetime.min.time()).timestamp()),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
        try:
            response = requests.get(
                self.chart_url.format(symbol=profile.symbol),
                params=params,
                headers=self.headers,
                timeout=self.timeout,
            )
            if response.status_code == 429:
                time.sleep(0.8)
                response = requests.get(
                    self.chart_url.format(symbol=profile.symbol),
                    params=params,
                    headers=self.headers,
                    timeout=self.timeout,
                )
            response.raise_for_status()
            result = response.json()["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            quote = result["indicators"]["quote"][0]
            values = quote.get("close", [])
            frame = pd.DataFrame({"trade_date": pd.to_datetime(timestamps, unit="s"), "close": values})
            frame["aum"] = np.nan
            frame["volume"] = quote.get("volume", [np.nan] * len(frame))
            frame["source_id"] = f"yahoo_chart:{profile.symbol}"
            frame["fetched_at"] = datetime.now().isoformat(timespec="seconds")
            return frame.dropna(subset=["close"])
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise DataFetchError(f"Yahoo 行情抓取失败：{profile.symbol}，{exc}") from exc

    def fetch_events(self, code: str, limit: int = 8) -> List[EventRecord]:
        profile = self.profiles[code]
        try:
            response = requests.get(
                self.search_url,
                params={"q": profile.name, "newsCount": limit},
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            news = response.json().get("news", [])
        except (requests.RequestException, ValueError):
            return []
        events: List[EventRecord] = []
        for item in news[:limit]:
            published = item.get("providerPublishTime")
            published_at = datetime.fromtimestamp(published) if published else datetime.now()
            events.append(
                EventRecord(
                    code=code,
                    title=item.get("title", "未命名新闻"),
                    publisher=item.get("publisher", "Yahoo Finance"),
                    published_at=published_at,
                    url=item.get("link", ""),
                    source="yahoo_news_secondary",
                )
            )
        return events


class EastmoneyConnector:
    """Eastmoney public daily K-line endpoint for mainland-listed ETFs."""

    history_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, profiles: Optional[Iterable[FundProfile]] = None, timeout: int = 8):
        self.profiles = {p.code: p for p in (profiles or DEFAULT_FUNDS)}
        self.timeout = timeout

    @staticmethod
    def _secid(symbol: str) -> str:
        market = "1" if symbol.endswith(".SS") else "0"
        return f"{market}.{symbol.split('.')[0]}"

    def fetch_history(self, code: str, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        profile = self.profiles[code]
        start = start or profile.inception_date
        end = end or date.today()
        params = {
            "secid": self._secid(profile.symbol),
            "klt": "101",
            "fqt": "1",
            "beg": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }
        try:
            response = requests.get(self.history_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            rows = (payload.get("data") or {}).get("klines") or []
            if not rows:
                raise DataFetchError(f"东方财富没有返回 {profile.symbol} 的日线数据")
            parsed = [row.split(",") for row in rows]
            frame = pd.DataFrame(
                {
                    "trade_date": [row[0] for row in parsed],
                    "close": [row[2] for row in parsed],
                    "aum": np.nan,
                    "volume": [row[5] for row in parsed],
                    "source_id": f"eastmoney_kline:{profile.symbol}",
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
            return frame.dropna(subset=["close"])
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise DataFetchError(f"东方财富行情抓取失败：{profile.symbol}，{exc}") from exc


class OfficialDisclosureConnector:
    """Primary-source fund disclosures from the exchange-operated ETF portals.

    These pages are used for event evidence (reports, listings, distributions and
    other fund notices). They are deliberately kept separate from price history:
    the exchange disclosure pages do not expose a complete long-range daily close
    series for every ETF.
    """

    sse_url = "https://etf.sse.com.cn/disclosure/"
    szse_url = "https://www.szse.cn/disclosure/notice/fund/index.html"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FundResearchBot/1.0)"}

    def __init__(self, profiles: Optional[Iterable[FundProfile]] = None, timeout: int = 12):
        self.profiles = {p.code: p for p in (profiles or DEFAULT_FUNDS)}
        self.timeout = timeout

    @staticmethod
    def _clean(value: str) -> str:
        value = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", unescape(value)).strip()

    @classmethod
    def _parse_sse(cls, html: str) -> List[tuple[str, str, str]]:
        pattern = re.compile(
            r'<div class="disclosure-item".*?<a href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<div>\s*(\d{4}-\d{2}-\d{2})\s*</div>',
            re.S,
        )
        return [(href, cls._clean(title), published) for href, title, published in pattern.findall(html)]

    @classmethod
    def _parse_szse(cls, html: str) -> List[tuple[str, str, str]]:
        pattern = re.compile(
            r"var\s+curHref\s*=\s*['\"]([^'\"]+)['\"].*?"
            r"(?<!/)var\s+curTitle\s*=\s*['\"](.*?)['\"].*?"
            r'<span class="time">\s*(\d{4}-\d{2}-\d{2})',
            re.S,
        )
        return [(href, cls._clean(title), published) for href, title, published in pattern.findall(html)]

    def fetch_events(self, code: str, limit: int = 8) -> List[EventRecord]:
        profile = self.profiles[code]
        if profile.symbol.endswith(".SS"):
            page_url, parser, source_name = self.sse_url, self._parse_sse, "sse_official_disclosure"
        elif profile.symbol.endswith(".SZ"):
            page_url, parser, source_name = self.szse_url, self._parse_szse, "szse_official_disclosure"
        else:
            return []
        try:
            response = requests.get(page_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            # Both exchange pages occasionally omit a usable charset header;
            # requests otherwise decodes Chinese titles as ISO-8859-1 mojibake.
            apparent_encoding = getattr(response, "apparent_encoding", None)
            response.encoding = apparent_encoding or getattr(response, "encoding", None)
            rows = parser(response.text)
        except (requests.RequestException, ValueError):
            return []

        # Do not match on the benchmark alone: an exchange page can contain
        # many different ETFs tracking the same index. A loose benchmark match
        # would attach another fund's announcement to the selected code.
        keywords = {code, profile.name}
        events: List[EventRecord] = []
        for href, title, published in rows:
            if not title or not any(keyword and keyword in title for keyword in keywords):
                continue
            try:
                published_at = datetime.strptime(published, "%Y-%m-%d")
            except ValueError:
                published_at = datetime.now()
            events.append(
                EventRecord(
                    code=code,
                    title=title,
                    publisher="上海证券交易所" if source_name.startswith("sse") else "深圳证券交易所",
                    published_at=published_at,
                    url=urljoin(page_url, href),
                    source=source_name,
                )
            )
            if len(events) >= limit:
                break
        return events


class CompositeConnector:
    def __init__(self, mode: str = "demo", profiles: Optional[Iterable[FundProfile]] = None):
        self.mode = mode
        self.demo = DemoConnector(profiles)
        self.yahoo = YahooFinanceConnector(profiles)
        self.eastmoney = EastmoneyConnector(profiles)
        self.official = OfficialDisclosureConnector(profiles)

    def fetch_history(self, code: str, start: Optional[date] = None, end: Optional[date] = None) -> tuple[pd.DataFrame, str]:
        if self.mode == "eastmoney":
            try:
                return self.eastmoney.fetch_history(code, start, end), "东方财富公开日线"
            except DataFetchError:
                return self.demo.fetch_history(code, start, end), "演示数据（东方财富不可用时回退）"
        if self.mode in {"auto", "yahoo"}:
            try:
                return self.yahoo.fetch_history(code, start, end), "Yahoo Finance public chart"
            except DataFetchError:
                try:
                    return self.eastmoney.fetch_history(code, start, end), "东方财富公开日线（Yahoo 限流回退）"
                except DataFetchError:
                    return self.demo.fetch_history(code, start, end), "演示数据（真实行情不可用）"
        return self.demo.fetch_history(code, start, end), "演示数据"

    def fetch_events(self, code: str) -> List[EventRecord]:
        if self.mode in {"auto", "yahoo", "eastmoney"}:
            official_events = self.official.fetch_events(code)
            if official_events:
                return official_events
        if self.mode in {"auto", "yahoo"}:
            events = self.yahoo.fetch_events(code)
            if events:
                return events
            return []
        if self.mode == "eastmoney":
            return []
        return self.demo.fetch_events(code)
