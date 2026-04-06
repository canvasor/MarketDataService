#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoinMarketCap 数据采集模块（辅助数据源）

作为 Binance 的补充数据源，提供:
- 全市场概览（总市值、BTC主导率）
- 恐惧贪婪指数
- 全网涨跌幅排行（包括非 Binance 币种）
- 市场情绪指标

注意:
- 本模块所有方法都有异常保护，不会影响主流程
- CMC 币种列表可能包含 Binance 没有的币种
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import aiohttp
from cachetools import TTLCache

logger = logging.getLogger(__name__)


@dataclass
class CMCCoinData:
    """CMC 币种数据"""
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
    """CMC 热门/趋势数据"""
    symbol: str
    name: str
    cmc_rank: int
    price: float
    percent_change_24h: float
    volume_change_24h: float  # 交易量变化
    trending_score: float = 0.0  # 热度评分
    last_update: float = field(default_factory=time.time)


@dataclass
class FearGreedData:
    """恐惧贪婪指数数据"""
    value: int  # 0-100
    value_classification: str  # Extreme Fear, Fear, Neutral, Greed, Extreme Greed
    timestamp: int
    time_until_update: Optional[int] = None


@dataclass
class MarketSentiment:
    """市场情绪综合数据"""
    fear_greed_index: int = 50  # 0-100
    fear_greed_label: str = "Neutral"
    btc_dominance: float = 0.0
    eth_dominance: float = 0.0
    total_market_cap: float = 0.0
    total_market_cap_change_24h: float = 0.0
    total_volume_24h: float = 0.0
    altcoin_season_index: int = 50  # 0-100, >75 为山寨季
    market_trend: str = "neutral"  # bullish, bearish, neutral
    timestamp: float = field(default_factory=time.time)


class CMCCollector:
    """CoinMarketCap 数据采集器（辅助数据源）"""

    # 恐惧贪婪指数 API（免费，无需 key）
    FEAR_GREED_API = "https://api.alternative.me/fng/"

    def __init__(self, api_endpoint: Optional[str] = None, api_key: Optional[str] = None):
        self.api_endpoint = api_endpoint or "https://pro-api.coinmarketcap.com"
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None

        # 缓存
        self._market_cache: TTLCache = TTLCache(maxsize=500, ttl=300)  # 5分钟
        self._trending_cache: TTLCache = TTLCache(maxsize=100, ttl=180)  # 3分钟
        self._fear_greed_cache: TTLCache = TTLCache(maxsize=10, ttl=600)  # 10分钟

    @property
    def is_available(self) -> bool:
        """检查 CMC API 是否可用"""
        return self.api_key is not None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取 HTTP 会话"""
        if self.session is None or self.session.closed:
            headers = {
                "Accept": "application/json",
            }
            if self.api_key:
                headers["X-CMC_PRO_API_KEY"] = self.api_key
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """发送请求"""
        if not self.api_key:
            logger.warning("CMC API key not configured")
            return {}

        session = await self._get_session()
        url = f"{self.api_endpoint}{endpoint}"

        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"CMC API error {resp.status}: {text}")
                    return {}
                result = await resp.json()
                if result.get("status", {}).get("error_code") != 0:
                    logger.error(f"CMC API error: {result.get('status', {}).get('error_message')}")
                    return {}
                return result
        except asyncio.TimeoutError:
            logger.error(f"CMC API timeout: {endpoint}")
            return {}
        except Exception as e:
            logger.error(f"CMC API error: {e}")
            return {}

    async def get_latest_listings(self, limit: int = 200) -> Dict[str, CMCCoinData]:
        """获取最新市值排名（前200名）"""
        cache_key = f"listings_{limit}"
        if cache_key in self._market_cache:
            return self._market_cache[cache_key]

        data = await self._request("/v1/cryptocurrency/listings/latest", {
            "limit": limit,
            "convert": "USD",
            "sort": "market_cap",
            "sort_dir": "desc"
        })

        if not data or "data" not in data:
            return {}

        coins = {}
        for item in data.get("data", []):
            symbol = item.get("symbol", "")
            quote = item.get("quote", {}).get("USD", {})

            try:
                coins[symbol] = CMCCoinData(
                    symbol=symbol,
                    name=item.get("name", ""),
                    cmc_rank=item.get("cmc_rank", 0),
                    price=quote.get("price", 0),
                    market_cap=quote.get("market_cap", 0),
                    volume_24h=quote.get("volume_24h", 0),
                    percent_change_1h=quote.get("percent_change_1h", 0),
                    percent_change_24h=quote.get("percent_change_24h", 0),
                    percent_change_7d=quote.get("percent_change_7d", 0),
                    circulating_supply=item.get("circulating_supply", 0),
                    total_supply=item.get("total_supply", 0),
                    max_supply=item.get("max_supply")
                )
            except Exception as e:
                logger.debug(f"Parse CMC coin error for {symbol}: {e}")
                continue

        self._market_cache[cache_key] = coins
        logger.info(f"Fetched {len(coins)} coins from CMC listings")
        return coins

    async def get_gainers_losers(self, limit: int = 20, time_period: str = "24h") -> tuple:
        """
        获取涨跌幅排行

        使用 listings 数据按涨跌幅排序（免费 API 兼容）

        Args:
            limit: 返回数量
            time_period: 时间周期 (1h, 24h, 7d)，目前只支持 24h

        Returns:
            (gainers, losers) 两个列表
        """
        cache_key = f"gainers_losers_{limit}_{time_period}"
        if cache_key in self._trending_cache:
            return self._trending_cache[cache_key]

        # 使用 listings 数据按涨跌幅排序（免费 API 兼容）
        coins = await self.get_latest_listings(200)

        if not coins:
            return ([], [])

        gainers = []
        losers = []

        for symbol, coin in coins.items():
            trending_data = CMCTrendingData(
                symbol=symbol,
                name=coin.name,
                cmc_rank=coin.cmc_rank,
                price=coin.price,
                percent_change_24h=coin.percent_change_24h,
                volume_change_24h=0  # listings 不提供此字段
            )

            if coin.percent_change_24h > 0:
                gainers.append(trending_data)
            else:
                losers.append(trending_data)

        # 按涨跌幅排序
        gainers.sort(key=lambda x: x.percent_change_24h, reverse=True)
        losers.sort(key=lambda x: x.percent_change_24h)

        result = (gainers[:limit], losers[:limit])
        self._trending_cache[cache_key] = result
        return result

    async def get_trending(self, limit: int = 20) -> List[CMCTrendingData]:
        """
        获取热门/趋势币种

        使用交易量/市值比率作为热度指标（免费 API 兼容）
        """
        cache_key = f"trending_{limit}"
        if cache_key in self._trending_cache:
            return self._trending_cache[cache_key]

        # 直接使用基于交易量的热度计算（免费 API 兼容）
        trending = await self._get_volume_trending(limit)
        self._trending_cache[cache_key] = trending
        return trending

    async def _get_volume_trending(self, limit: int = 20) -> List[CMCTrendingData]:
        """使用交易量变化作为热度指标"""
        coins = await self.get_latest_listings(200)

        # 计算交易量/市值比率作为活跃度指标
        trending = []
        for symbol, coin in coins.items():
            if coin.market_cap > 0:
                activity_ratio = coin.volume_24h / coin.market_cap
                trending.append(CMCTrendingData(
                    symbol=symbol,
                    name=coin.name,
                    cmc_rank=coin.cmc_rank,
                    price=coin.price,
                    percent_change_24h=coin.percent_change_24h,
                    volume_change_24h=0,  # 无法获取
                    trending_score=activity_ratio * 100
                ))

        # 按活跃度排序
        trending.sort(key=lambda x: x.trending_score, reverse=True)
        return trending[:limit]

    async def get_coin_info(self, symbol: str) -> Optional[CMCCoinData]:
        """获取单个币种详细信息"""
        # 先从缓存查找
        coins = await self.get_latest_listings(200)
        return coins.get(symbol.upper())

    async def get_high_volume_coins(self, min_volume: float = 100_000_000, limit: int = 50) -> List[CMCCoinData]:
        """获取高交易量币种"""
        coins = await self.get_latest_listings(200)

        high_vol = [
            c for c in coins.values()
            if c.volume_24h >= min_volume
        ]

        high_vol.sort(key=lambda x: x.volume_24h, reverse=True)
        return high_vol[:limit]

    async def get_market_overview(self) -> Dict:
        """获取市场概览"""
        cache_key = "market_overview"
        if cache_key in self._market_cache:
            return self._market_cache[cache_key]

        data = await self._request("/v1/global-metrics/quotes/latest", {
            "convert": "USD"
        })

        if not data or "data" not in data:
            return {}

        quote = data["data"].get("quote", {}).get("USD", {})

        overview = {
            "total_market_cap": quote.get("total_market_cap", 0),
            "total_volume_24h": quote.get("total_volume_24h", 0),
            "btc_dominance": data["data"].get("btc_dominance", 0),
            "eth_dominance": data["data"].get("eth_dominance", 0),
            "active_cryptocurrencies": data["data"].get("active_cryptocurrencies", 0),
            "total_market_cap_yesterday_percentage_change": quote.get("total_market_cap_yesterday_percentage_change", 0),
            "total_volume_24h_yesterday_percentage_change": quote.get("total_volume_24h_yesterday_percentage_change", 0),
            "last_updated": data["data"].get("last_updated", "")
        }

        self._market_cache[cache_key] = overview
        return overview

    async def get_fear_greed_index(self) -> Optional[FearGreedData]:
        """
        获取恐惧贪婪指数（使用 alternative.me 免费 API，无需 CMC key）

        返回:
            - value: 0-100 (0=极度恐惧, 100=极度贪婪)
            - value_classification: Extreme Fear/Fear/Neutral/Greed/Extreme Greed
        """
        cache_key = "fear_greed"
        if cache_key in self._fear_greed_cache:
            return self._fear_greed_cache[cache_key]

        try:
            session = await self._get_session()
            async with session.get(self.FEAR_GREED_API, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"Fear & Greed API error: {resp.status}")
                    return None

                data = await resp.json()
                if not data or "data" not in data or not data["data"]:
                    return None

                item = data["data"][0]
                result = FearGreedData(
                    value=int(item.get("value", 50)),
                    value_classification=item.get("value_classification", "Neutral"),
                    timestamp=int(item.get("timestamp", time.time())),
                    time_until_update=int(item.get("time_until_update", 0)) if item.get("time_until_update") else None
                )

                self._fear_greed_cache[cache_key] = result
                logger.info(f"Fear & Greed Index: {result.value} ({result.value_classification})")
                return result

        except Exception as e:
            logger.warning(f"获取恐惧贪婪指数失败: {e}")
            return None

    async def get_market_sentiment(self) -> MarketSentiment:
        """
        获取综合市场情绪数据

        整合多个数据源:
        - 恐惧贪婪指数（免费 API）
        - CMC 全市场数据（需要 key）
        - 计算山寨季指数

        注意: 此方法保证返回数据，即使部分数据源失败
        """
        sentiment = MarketSentiment()

        # 1. 获取恐惧贪婪指数（免费，不需要 CMC key）
        try:
            fear_greed = await self.get_fear_greed_index()
            if fear_greed:
                sentiment.fear_greed_index = fear_greed.value
                sentiment.fear_greed_label = fear_greed.value_classification
        except Exception as e:
            logger.debug(f"获取恐惧贪婪指数失败: {e}")

        # 2. 获取 CMC 市场数据（需要 key）
        if self.is_available:
            try:
                overview = await self.get_market_overview()
                if overview:
                    sentiment.btc_dominance = overview.get("btc_dominance", 0)
                    sentiment.eth_dominance = overview.get("eth_dominance", 0)
                    sentiment.total_market_cap = overview.get("total_market_cap", 0)
                    sentiment.total_market_cap_change_24h = overview.get("total_market_cap_yesterday_percentage_change", 0)
                    sentiment.total_volume_24h = overview.get("total_volume_24h", 0)

                    # 计算山寨季指数（BTC 主导率越低，山寨季越强）
                    if sentiment.btc_dominance > 0:
                        # BTC 主导率 60% -> 山寨季指数 25
                        # BTC 主导率 40% -> 山寨季指数 75
                        sentiment.altcoin_season_index = max(0, min(100, int(100 - sentiment.btc_dominance * 1.25)))
            except Exception as e:
                logger.debug(f"获取 CMC 市场数据失败: {e}")

        # 3. 判断市场趋势
        if sentiment.fear_greed_index >= 70:
            sentiment.market_trend = "bullish"
        elif sentiment.fear_greed_index <= 30:
            sentiment.market_trend = "bearish"
        else:
            # 中性区间，参考市值变化
            if sentiment.total_market_cap_change_24h > 2:
                sentiment.market_trend = "bullish"
            elif sentiment.total_market_cap_change_24h < -2:
                sentiment.market_trend = "bearish"
            else:
                sentiment.market_trend = "neutral"

        sentiment.timestamp = time.time()
        return sentiment

    async def safe_get_market_sentiment(self) -> Dict[str, Any]:
        """
        安全获取市场情绪数据（保证返回字典，不抛异常）

        用于主接口调用，确保 CMC 异常不影响主流程
        """
        try:
            sentiment = await self.get_market_sentiment()
            return {
                "available": True,
                "fear_greed_index": sentiment.fear_greed_index,
                "fear_greed_label": sentiment.fear_greed_label,
                "btc_dominance": sentiment.btc_dominance,
                "eth_dominance": sentiment.eth_dominance,
                "total_market_cap": sentiment.total_market_cap,
                "total_market_cap_change_24h": sentiment.total_market_cap_change_24h,
                "total_volume_24h": sentiment.total_volume_24h,
                "altcoin_season_index": sentiment.altcoin_season_index,
                "market_trend": sentiment.market_trend,
                "timestamp": int(sentiment.timestamp)
            }
        except Exception as e:
            logger.warning(f"获取市场情绪失败: {e}")
            return {
                "available": False,
                "error": str(e),
                "timestamp": int(time.time())
            }

    async def get_fear_greed_history(self, limit: int = 7) -> List[Dict]:
        """
        获取恐惧贪婪指数历史数据

        Args:
            limit: 返回天数（最多30天）

        Returns:
            历史数据列表
        """
        cache_key = f"fear_greed_history_{limit}"
        if cache_key in self._fear_greed_cache:
            return self._fear_greed_cache[cache_key]

        try:
            session = await self._get_session()
            url = f"{self.FEAR_GREED_API}?limit={min(limit, 30)}"
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                if not data or "data" not in data:
                    return []

                history = []
                for item in data["data"]:
                    history.append({
                        "value": int(item.get("value", 50)),
                        "classification": item.get("value_classification", "Neutral"),
                        "timestamp": int(item.get("timestamp", 0)),
                        "date": time.strftime("%Y-%m-%d", time.localtime(int(item.get("timestamp", 0))))
                    })

                self._fear_greed_cache[cache_key] = history
                return history

        except Exception as e:
            logger.warning(f"获取恐惧贪婪历史失败: {e}")
            return []
