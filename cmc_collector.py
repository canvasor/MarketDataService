#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宏观市场与市值数据采集器。

兼容旧的 CMCCollector 名称，但内部优先支持 CoinGecko Demo（免费）,
其次支持 CoinMarketCap Free。Fear & Greed 继续走免费接口。

新增：
1. 本地 provider usage/budget 跟踪。
2. auto 模式下预算感知回退（CoinGecko -> CMC）。
3. `/key` 远端 usage 拉取（CoinGecko，best effort）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from cachetools import TTLCache

from provider_budget import ProviderBudgetTracker

logger = logging.getLogger(__name__)


@dataclass
class CMCCoinData:
    symbol: str
    name: str
    cmc_rank: int
    price: float
    market_cap: float
    volume_24h: float
    percent_change_1h: float
    percent_change_24h: float
    percent_change_7d: float
    circulating_supply: float
    total_supply: float
    max_supply: Optional[float] = None
    last_update: float = field(default_factory=time.time)


@dataclass
class CMCTrendingData:
    symbol: str
    name: str
    cmc_rank: int
    price: float
    percent_change_24h: float
    volume_change_24h: float
    trending_score: float = 0.0
    last_update: float = field(default_factory=time.time)


@dataclass
class FearGreedData:
    value: int
    value_classification: str
    timestamp: int
    time_until_update: Optional[int] = None


@dataclass
class MarketSentiment:
    fear_greed_index: int = 50
    fear_greed_label: str = "Neutral"
    btc_dominance: float = 0.0
    eth_dominance: float = 0.0
    total_market_cap: float = 0.0
    total_market_cap_change_24h: float = 0.0
    total_volume_24h: float = 0.0
    altcoin_season_index: int = 50
    market_trend: str = "neutral"
    timestamp: float = field(default_factory=time.time)


class CMCCollector:
    FEAR_GREED_API = "https://api.alternative.me/fng/"

    def __init__(
        self,
        api_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        coingecko_api_endpoint: str = "https://api.coingecko.com/api/v3",
        coingecko_api_key: Optional[str] = None,
        provider: str = "auto",
        usage_storage_path: str = "data/provider_usage.json",
        coingecko_monthly_soft_limit: int = 9500,
        coingecko_minute_soft_limit: int = 25,
        cmc_monthly_soft_limit: int = 9500,
        cmc_minute_soft_limit: int = 25,
    ):
        self.api_endpoint = (api_endpoint or "https://pro-api.coinmarketcap.com").rstrip("/")
        self.api_key = api_key
        self.coingecko_api_endpoint = coingecko_api_endpoint.rstrip("/")
        self.coingecko_api_key = coingecko_api_key
        self.provider = provider
        self.session: Optional[aiohttp.ClientSession] = None
        self._market_cache: TTLCache = TTLCache(maxsize=100, ttl=300)
        self._trending_cache: TTLCache = TTLCache(maxsize=100, ttl=180)
        self._fear_greed_cache: TTLCache = TTLCache(maxsize=20, ttl=600)
        self._usage_cache: TTLCache = TTLCache(maxsize=20, ttl=120)

        self.budget_tracker = ProviderBudgetTracker(storage_path=usage_storage_path)
        self.provider_limits = {
            "coingecko": {
                "monthly_soft_limit": coingecko_monthly_soft_limit,
                "minute_limit": coingecko_minute_soft_limit,
            },
            "cmc": {
                "monthly_soft_limit": cmc_monthly_soft_limit,
                "minute_limit": cmc_minute_soft_limit,
            },
        }

    @property
    def configured_providers(self) -> List[str]:
        providers: List[str] = []
        if self.coingecko_api_key:
            providers.append("coingecko")
        if self.api_key:
            providers.append("cmc")
        return providers

    @property
    def active_provider(self) -> str:
        # 返回“当前优先使用者”，真实请求时仍可能 budget-aware fallback
        if self.provider in {"coingecko", "cmc", "none"}:
            return self.provider
        if self.coingecko_api_key:
            return "coingecko"
        if self.api_key:
            return "cmc"
        return "none"

    @property
    def is_available(self) -> bool:
        return self.active_provider in {"coingecko", "cmc"}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"Accept": "application/json"})
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ---------- provider selection / usage ----------
    def _is_provider_allowed(self, provider: str) -> bool:
        if provider == "coingecko":
            return bool(self.coingecko_api_key)
        if provider == "cmc":
            return bool(self.api_key)
        return False

    def _pick_provider(self, preferred: Optional[str] = None) -> str:
        if preferred in {"coingecko", "cmc"} and self._is_provider_allowed(preferred):
            return preferred
        if self.provider in {"coingecko", "cmc"} and self._is_provider_allowed(self.provider):
            return self.provider
        if self.provider == "none":
            return "none"

        # auto 模式：优先 CoinGecko，预算不够则回退 CMC
        candidates = ["coingecko", "cmc"]
        for p in candidates:
            if not self._is_provider_allowed(p):
                continue
            usage = self.budget_tracker.can_attempt(
                p,
                minute_limit=self.provider_limits[p]["minute_limit"],
                monthly_soft_limit=self.provider_limits[p]["monthly_soft_limit"],
            )
            if usage["allowed"]:
                return p
        # 都超预算时仍返回首个已配置 provider，交给调用层处理（避免 silent failure）
        for p in candidates:
            if self._is_provider_allowed(p):
                return p
        return "none"

    async def get_provider_usage(self) -> Dict[str, Any]:
        cache_key = "provider_usage"
        if cache_key in self._usage_cache:
            return self._usage_cache[cache_key]
        local = self.budget_tracker.get_all_usage(self.provider_limits)
        remote = {}
        # CoinGecko 支持 /key endpoint 查看用量（best effort）
        if self.coingecko_api_key:
            remote["coingecko"] = await self._request_coingecko_key_usage()
        result = {
            "preferred_provider": self.active_provider,
            "configured_providers": self.configured_providers,
            "local": local,
            "remote": remote,
            "timestamp": int(time.time()),
        }
        self._usage_cache[cache_key] = result
        return result

    async def _request_coingecko_key_usage(self) -> Dict[str, Any]:
        if not self.coingecko_api_key:
            return {"available": False, "reason": "missing_key"}
        try:
            data = await self._request_json(
                f"{self.coingecko_api_endpoint}/key",
                headers={"x-cg-demo-api-key": self.coingecko_api_key},
                params=None,
                provider="coingecko",
                count_success=False,
            )
            if isinstance(data, dict) and data:
                return {"available": True, "data": data}
            return {"available": False, "reason": "empty_response"}
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    # ---------- request helpers ----------
    async def _request_json(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
        provider: Optional[str] = None,
        count_success: bool = True,
    ) -> Any:
        session = await self._get_session()
        merged_headers = {"Accept": "application/json"}
        if headers:
            merged_headers.update(headers)

        if provider and provider in self.provider_limits:
            gate = self.budget_tracker.can_attempt(
                provider,
                minute_limit=self.provider_limits[provider]["minute_limit"],
                monthly_soft_limit=self.provider_limits[provider]["monthly_soft_limit"],
            )
            if not gate["allowed"]:
                logger.warning("%s usage gate blocked request: %s", provider, gate)
                return {}
            self.budget_tracker.record_attempt(provider)

        try:
            async with session.get(url, headers=merged_headers, params=params, timeout=15) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Market API error %s: %s", resp.status, body[:300])
                    if provider:
                        self.budget_tracker.record_result(provider, False, error=f"HTTP {resp.status}: {body[:180]}")
                    return {}
                data = await resp.json()
                if provider and count_success:
                    self.budget_tracker.record_result(provider, True)
                return data
        except asyncio.TimeoutError:
            logger.warning("Market API timeout: %s", url)
            if provider:
                self.budget_tracker.record_result(provider, False, error="timeout")
            return {}
        except Exception as exc:
            logger.warning("Market API error: %s", exc)
            if provider:
                self.budget_tracker.record_result(provider, False, error=str(exc))
            return {}

    async def _request_cmc(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        if not self.api_key:
            return {}
        return await self._request_json(
            f"{self.api_endpoint}{endpoint}",
            headers={"X-CMC_PRO_API_KEY": self.api_key},
            params=params,
            provider="cmc",
        )

    async def _request_coingecko(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        if not self.coingecko_api_key:
            return {}
        headers = {"x-cg-demo-api-key": self.coingecko_api_key}
        return await self._request_json(
            f"{self.coingecko_api_endpoint}{endpoint}",
            headers=headers,
            params=params,
            provider="coingecko",
        )

    # ---------- public data methods ----------
    async def get_latest_listings(self, limit: int = 200) -> Dict[str, CMCCoinData]:
        provider = self._pick_provider()
        cache_key = f"listings:{provider}:{limit}"
        if cache_key in self._market_cache:
            return self._market_cache[cache_key]

        if provider == "coingecko":
            data = await self._request_coingecko(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": limit,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h,7d",
                },
            )
            results: Dict[str, CMCCoinData] = {}
            if isinstance(data, list):
                for item in data:
                    symbol = str(item.get("symbol", "")).upper()
                    results[symbol] = CMCCoinData(
                        symbol=symbol,
                        name=item.get("name", symbol),
                        cmc_rank=int(item.get("market_cap_rank") or 0),
                        price=float(item.get("current_price") or 0),
                        market_cap=float(item.get("market_cap") or 0),
                        volume_24h=float(item.get("total_volume") or 0),
                        percent_change_1h=float(item.get("price_change_percentage_1h_in_currency") or 0),
                        percent_change_24h=float(item.get("price_change_percentage_24h") or 0),
                        percent_change_7d=float(item.get("price_change_percentage_7d_in_currency") or 0),
                        circulating_supply=float(item.get("circulating_supply") or 0),
                        total_supply=float(item.get("total_supply") or 0),
                        max_supply=float(item.get("max_supply")) if item.get("max_supply") is not None else None,
                    )
                self._market_cache[cache_key] = results
                return results
            if self.api_key and self.provider == "auto":
                logger.info("CoinGecko listings unavailable, fallback to CMC")
                return await self._get_latest_listings_by_provider("cmc", limit)

        if provider == "cmc":
            return await self._get_latest_listings_by_provider("cmc", limit)

        return {}

    async def _get_latest_listings_by_provider(self, provider: str, limit: int) -> Dict[str, CMCCoinData]:
        cache_key = f"listings:{provider}:{limit}"
        if cache_key in self._market_cache:
            return self._market_cache[cache_key]
        if provider != "cmc":
            return {}
        data = await self._request_cmc(
            "/v1/cryptocurrency/listings/latest",
            {"limit": limit, "convert": "USD", "sort": "market_cap", "sort_dir": "desc"},
        )
        rows = data.get("data", []) if isinstance(data, dict) else []
        results: Dict[str, CMCCoinData] = {}
        for item in rows:
            symbol = str(item.get("symbol", "")).upper()
            quote = item.get("quote", {}).get("USD", {})
            results[symbol] = CMCCoinData(
                symbol=symbol,
                name=item.get("name", symbol),
                cmc_rank=int(item.get("cmc_rank") or 0),
                price=float(quote.get("price") or 0),
                market_cap=float(quote.get("market_cap") or 0),
                volume_24h=float(quote.get("volume_24h") or 0),
                percent_change_1h=float(quote.get("percent_change_1h") or 0),
                percent_change_24h=float(quote.get("percent_change_24h") or 0),
                percent_change_7d=float(quote.get("percent_change_7d") or 0),
                circulating_supply=float(item.get("circulating_supply") or 0),
                total_supply=float(item.get("total_supply") or 0),
                max_supply=float(item.get("max_supply")) if item.get("max_supply") is not None else None,
            )
        self._market_cache[cache_key] = results
        return results

    async def get_gainers_losers(self, limit: int = 20, time_period: str = "24h") -> Tuple[List[CMCTrendingData], List[CMCTrendingData]]:
        cache_key = f"gainers_losers:{self._pick_provider()}:{limit}:{time_period}"
        if cache_key in self._trending_cache:
            return self._trending_cache[cache_key]

        listings = await self.get_latest_listings(250)
        gainers: List[CMCTrendingData] = []
        losers: List[CMCTrendingData] = []
        for coin in listings.values():
            entry = CMCTrendingData(
                symbol=coin.symbol,
                name=coin.name,
                cmc_rank=coin.cmc_rank,
                price=coin.price,
                percent_change_24h=coin.percent_change_24h,
                volume_change_24h=0.0,
                trending_score=abs(coin.percent_change_24h),
            )
            if coin.percent_change_24h >= 0:
                gainers.append(entry)
            else:
                losers.append(entry)
        gainers.sort(key=lambda x: x.percent_change_24h, reverse=True)
        losers.sort(key=lambda x: x.percent_change_24h)
        result = (gainers[:limit], losers[:limit])
        self._trending_cache[cache_key] = result
        return result

    async def get_trending(self, limit: int = 20) -> List[CMCTrendingData]:
        provider = self._pick_provider()
        cache_key = f"trending:{provider}:{limit}"
        if cache_key in self._trending_cache:
            return self._trending_cache[cache_key]

        if provider == "coingecko":
            data = await self._request_coingecko("/search/trending")
            coins = data.get("coins", []) if isinstance(data, dict) else []
            results: List[CMCTrendingData] = []
            for row in coins[:limit]:
                item = row.get("item", {})
                symbol = str(item.get("symbol", "")).upper()
                results.append(
                    CMCTrendingData(
                        symbol=symbol,
                        name=item.get("name", symbol),
                        cmc_rank=int(item.get("market_cap_rank") or 0),
                        price=float(item.get("data", {}).get("price") or 0),
                        percent_change_24h=float(item.get("data", {}).get("price_change_percentage_24h", {}).get("usd") or 0),
                        volume_change_24h=0.0,
                        trending_score=float(item.get("score") or 0),
                    )
                )
            self._trending_cache[cache_key] = results
            return results

        # CMC free 无专门 trending 端点时，退化为 activity ratio 近似榜单
        listings = await self.get_latest_listings(200)
        results = []
        for coin in listings.values():
            if coin.market_cap <= 0:
                continue
            activity_ratio = coin.volume_24h / coin.market_cap if coin.market_cap else 0
            results.append(
                CMCTrendingData(
                    symbol=coin.symbol,
                    name=coin.name,
                    cmc_rank=coin.cmc_rank,
                    price=coin.price,
                    percent_change_24h=coin.percent_change_24h,
                    volume_change_24h=0.0,
                    trending_score=activity_ratio * 100,
                )
            )
        results.sort(key=lambda x: x.trending_score, reverse=True)
        results = results[:limit]
        self._trending_cache[cache_key] = results
        return results

    async def get_coin_info(self, symbol: str) -> Optional[CMCCoinData]:
        return (await self.get_latest_listings(250)).get(symbol.upper())

    async def get_high_volume_coins(self, min_volume: float = 100_000_000, limit: int = 50) -> List[CMCCoinData]:
        listings = await self.get_latest_listings(300)
        rows = [x for x in listings.values() if x.volume_24h >= min_volume]
        rows.sort(key=lambda x: x.volume_24h, reverse=True)
        return rows[:limit]

    async def get_market_overview(self) -> Dict[str, Any]:
        provider = self._pick_provider()
        cache_key = f"market_overview:{provider}"
        if cache_key in self._market_cache:
            return self._market_cache[cache_key]

        if provider == "coingecko":
            data = await self._request_coingecko("/global")
            payload = data.get("data", {}) if isinstance(data, dict) else {}
            overview = {
                "total_market_cap": float((payload.get("total_market_cap") or {}).get("usd") or 0),
                "total_volume_24h": float((payload.get("total_volume") or {}).get("usd") or 0),
                "btc_dominance": float((payload.get("market_cap_percentage") or {}).get("btc") or 0),
                "eth_dominance": float((payload.get("market_cap_percentage") or {}).get("eth") or 0),
                "active_cryptocurrencies": int(payload.get("active_cryptocurrencies") or 0),
                "total_market_cap_yesterday_percentage_change": float(payload.get("market_cap_change_percentage_24h_usd") or 0),
                "total_volume_24h_yesterday_percentage_change": 0.0,
                "last_updated": int(time.time()),
                "provider": "coingecko",
            }
            self._market_cache[cache_key] = overview
            return overview

        if provider == "cmc":
            data = await self._request_cmc("/v1/global-metrics/quotes/latest", {"convert": "USD"})
            payload = data.get("data", {}) if isinstance(data, dict) else {}
            quote = payload.get("quote", {}).get("USD", {})
            overview = {
                "total_market_cap": float(quote.get("total_market_cap") or 0),
                "total_volume_24h": float(quote.get("total_volume_24h") or 0),
                "btc_dominance": float(payload.get("btc_dominance") or 0),
                "eth_dominance": float(payload.get("eth_dominance") or 0),
                "active_cryptocurrencies": int(payload.get("active_cryptocurrencies") or 0),
                "total_market_cap_yesterday_percentage_change": float(quote.get("total_market_cap_yesterday_percentage_change") or 0),
                "total_volume_24h_yesterday_percentage_change": float(quote.get("total_volume_24h_yesterday_percentage_change") or 0),
                "last_updated": payload.get("last_updated", int(time.time())),
                "provider": "cmc",
            }
            self._market_cache[cache_key] = overview
            return overview

        return {}

    async def get_fear_greed_index(self) -> Optional[FearGreedData]:
        cache_key = "fear_greed"
        if cache_key in self._fear_greed_cache:
            return self._fear_greed_cache[cache_key]
        try:
            session = await self._get_session()
            async with session.get(self.FEAR_GREED_API, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                rows = data.get("data", []) if isinstance(data, dict) else []
                if not rows:
                    return None
                row = rows[0]
                result = FearGreedData(
                    value=int(row.get("value") or 50),
                    value_classification=row.get("value_classification", "Neutral"),
                    timestamp=int(row.get("timestamp") or time.time()),
                    time_until_update=int(row.get("time_until_update")) if row.get("time_until_update") else None,
                )
                self._fear_greed_cache[cache_key] = result
                return result
        except Exception as exc:
            logger.warning("获取恐惧贪婪指数失败: %s", exc)
            return None

    async def get_market_sentiment(self) -> MarketSentiment:
        sentiment = MarketSentiment()
        fg = await self.get_fear_greed_index()
        if fg:
            sentiment.fear_greed_index = fg.value
            sentiment.fear_greed_label = fg.value_classification

        overview = await self.get_market_overview()
        if overview:
            sentiment.btc_dominance = float(overview.get("btc_dominance") or 0)
            sentiment.eth_dominance = float(overview.get("eth_dominance") or 0)
            sentiment.total_market_cap = float(overview.get("total_market_cap") or 0)
            sentiment.total_market_cap_change_24h = float(overview.get("total_market_cap_yesterday_percentage_change") or 0)
            sentiment.total_volume_24h = float(overview.get("total_volume_24h") or 0)
            if sentiment.btc_dominance > 0:
                sentiment.altcoin_season_index = max(0, min(100, int(100 - sentiment.btc_dominance * 1.25)))

        if sentiment.fear_greed_index >= 70:
            sentiment.market_trend = "bullish"
        elif sentiment.fear_greed_index <= 30:
            sentiment.market_trend = "bearish"
        elif sentiment.total_market_cap_change_24h > 2:
            sentiment.market_trend = "bullish"
        elif sentiment.total_market_cap_change_24h < -2:
            sentiment.market_trend = "bearish"
        else:
            sentiment.market_trend = "neutral"
        sentiment.timestamp = time.time()
        return sentiment

    async def safe_get_market_sentiment(self) -> Dict[str, Any]:
        try:
            sentiment = await self.get_market_sentiment()
            return {
                "available": True,
                "provider": self._pick_provider(),
                "fear_greed_index": sentiment.fear_greed_index,
                "fear_greed_label": sentiment.fear_greed_label,
                "btc_dominance": sentiment.btc_dominance,
                "eth_dominance": sentiment.eth_dominance,
                "total_market_cap": sentiment.total_market_cap,
                "total_market_cap_change_24h": sentiment.total_market_cap_change_24h,
                "total_volume_24h": sentiment.total_volume_24h,
                "altcoin_season_index": sentiment.altcoin_season_index,
                "market_trend": sentiment.market_trend,
                "timestamp": int(sentiment.timestamp),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc), "timestamp": int(time.time())}

    async def get_fear_greed_history(self, limit: int = 7) -> List[Dict]:
        cache_key = f"fear_greed_history:{limit}"
        if cache_key in self._fear_greed_cache:
            return self._fear_greed_cache[cache_key]
        try:
            session = await self._get_session()
            async with session.get(f"{self.FEAR_GREED_API}?limit={min(limit, 30)}", timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                rows = data.get("data", []) if isinstance(data, dict) else []
                result = [
                    {
                        "value": int(row.get("value") or 50),
                        "classification": row.get("value_classification", "Neutral"),
                        "timestamp": int(row.get("timestamp") or 0),
                        "date": time.strftime("%Y-%m-%d", time.localtime(int(row.get("timestamp") or 0))),
                    }
                    for row in rows
                ]
                self._fear_greed_cache[cache_key] = result
                return result
        except Exception as exc:
            logger.warning("获取恐惧贪婪历史失败: %s", exc)
            return []
