#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance 数据采集模块

使用 Binance Futures API 获取:
- 合约行情数据
- 持仓量(OI)数据
- 资金费率
- 24h 交易量
"""

import asyncio
import logging
import re
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import aiohttp
from cachetools import TTLCache

logger = logging.getLogger(__name__)


def contains_non_ascii(s: str) -> bool:
    """
    检测字符串是否包含非 ASCII 字符（如中文、日文、韩文等）

    用于过滤掉带有中文名称的币种，这些币种可能导致 LLM 分析失败
    例如：币安人生 (BLIFEUSDT)
    """
    return bool(re.search(r'[^\x00-\x7F]', s))


@dataclass
class TickerData:
    """行情数据"""
    symbol: str
    price: float
    price_change_1h: float = 0.0
    price_change_4h: float = 0.0
    price_change_24h: float = 0.0
    volume_24h: float = 0.0  # USDT
    high_24h: float = 0.0
    low_24h: float = 0.0
    volatility_24h: float = 0.0  # (high-low)/price * 100
    last_update: float = field(default_factory=time.time)


@dataclass
class OIData:
    """持仓量数据"""
    symbol: str
    oi_value: float  # USDT
    oi_coins: float  # 币数量
    oi_change_1h: float = 0.0  # %
    oi_change_4h: float = 0.0
    oi_change_24h: float = 0.0
    oi_delta_value_1h: float = 0.0  # USDT
    last_update: float = field(default_factory=time.time)


@dataclass
class FundingData:
    """资金费率数据"""
    symbol: str
    funding_rate: float
    next_funding_time: int
    last_update: float = field(default_factory=time.time)


class BinanceCollector:
    """Binance 数据采集器"""

    BASE_URL = "https://fapi.binance.com"
    REQUEST_CONCURRENCY = 15
    REQUEST_MIN_INTERVAL = 0.05
    RATE_LIMIT_RETRY_LIMIT = 2
    RATE_LIMIT_COOLDOWN_SECONDS = 900.0
    RATE_LIMIT_RETRY_SECONDS = 2.0
    OI_BATCH_SIZE = 50
    OI_HISTORY_BATCH_SIZE = 15

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session: Optional[aiohttp.ClientSession] = None

        # 缓存
        self._ticker_cache: TTLCache = TTLCache(maxsize=500, ttl=5)
        self._oi_cache: TTLCache = TTLCache(maxsize=500, ttl=600)
        self._funding_cache: TTLCache = TTLCache(maxsize=500, ttl=600)
        self._kline_cache: TTLCache = TTLCache(maxsize=1000, ttl=600)

        # 所有 USDT 永续合约符号
        self._usdt_symbols: List[str] = []
        self._symbols_update_time: float = 0
        self._request_semaphore = asyncio.Semaphore(self.REQUEST_CONCURRENCY)
        self._request_pace_lock = asyncio.Lock()
        self._next_request_time = 0.0
        self._rate_limit_blocked_until = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取 HTTP 会话"""
        if self.session is None or self.session.closed:
            headers = {}
            if self.api_key:
                headers["X-MBX-APIKEY"] = self.api_key
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()

    @staticmethod
    def _parse_retry_after(value: Optional[str], default: float) -> float:
        if not value:
            return default
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return default

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """发送请求"""
        session = await self._get_session()
        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(self.RATE_LIMIT_RETRY_LIMIT + 1):
            now = time.monotonic()
            if self._rate_limit_blocked_until > now:
                logger.warning(
                    "Binance API cooldown active for %.1fs, skipping request: %s",
                    self._rate_limit_blocked_until - now,
                    endpoint,
                )
                return {}

            try:
                async with self._request_semaphore:
                    async with self._request_pace_lock:
                        now = time.monotonic()
                        if self._rate_limit_blocked_until > now:
                            logger.warning(
                                "Binance API cooldown active for %.1fs, skipping request: %s",
                                self._rate_limit_blocked_until - now,
                                endpoint,
                            )
                            return {}
                        wait_seconds = max(0.0, self._next_request_time - now)
                        if wait_seconds > 0:
                            await asyncio.sleep(wait_seconds)
                        self._next_request_time = time.monotonic() + self.REQUEST_MIN_INTERVAL

                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            return await resp.json()

                        text = await resp.text()
                        if resp.status == 429:
                            retry_after = self._parse_retry_after(resp.headers.get("Retry-After"), self.RATE_LIMIT_RETRY_SECONDS)
                            logger.warning(
                                "Binance API rate limited on %s, retrying in %.1fs (attempt %d/%d)",
                                endpoint,
                                retry_after,
                                attempt + 1,
                                self.RATE_LIMIT_RETRY_LIMIT + 1,
                            )
                            if attempt < self.RATE_LIMIT_RETRY_LIMIT:
                                await asyncio.sleep(retry_after)
                                continue
                            return {}

                        if resp.status == 418:
                            cooldown = self._parse_retry_after(resp.headers.get("Retry-After"), self.RATE_LIMIT_COOLDOWN_SECONDS)
                            self._rate_limit_blocked_until = max(self._rate_limit_blocked_until, time.monotonic() + cooldown)
                            logger.error("Binance API IP banned/cooldown %.1fs: %s", cooldown, endpoint)
                            return {}

                        # -4108: Symbol is on delivering/settling/closed - 预期行为，降级为 debug
                        if "-4108" in text:
                            logger.debug(f"Binance API: symbol not available (settling/delivering): {params}")
                        elif "-1121" in text:
                            logger.debug(f"Binance API: invalid symbol: {params}")
                        else:
                            logger.error(f"Binance API error {resp.status}: {text} (endpoint={endpoint}, params={params})")
                        return {}
            except asyncio.TimeoutError:
                logger.error(f"Binance API timeout: {endpoint}")
                return {}
            except Exception as e:
                logger.error(f"Binance API error: {e}")
                return {}

        return {}

    async def _refresh_binance_symbols(self, force_refresh: bool = False) -> List[str]:
        """从 Binance exchangeInfo 刷新并缓存 USDT 永续合约列表（仅 Binance 自身的）"""
        now = time.time()
        if not force_refresh and self._usdt_symbols and (now - self._symbols_update_time < 3600):
            return self._usdt_symbols

        data = await self._request("/fapi/v1/exchangeInfo")
        if not data:
            return self._usdt_symbols or []

        symbols = []
        for s in data.get("symbols", []):
            if (s.get("contractType") == "PERPETUAL" and
                s.get("quoteAsset") == "USDT" and
                s.get("status") == "TRADING"):
                symbols.append(s["symbol"])

        self._usdt_symbols = symbols
        self._symbols_update_time = now
        logger.info(f"Loaded {len(symbols)} USDT perpetual symbols from Binance")
        return symbols

    async def get_usdt_symbols(self, force_refresh: bool = False) -> List[str]:
        """获取所有 USDT 永续合约符号（子类可重写以合并多交易所）"""
        return await self._refresh_binance_symbols(force_refresh=force_refresh)

    async def get_all_tickers(self) -> Dict[str, TickerData]:
        """获取所有合约 24h 行情"""
        cache_key = "all_tickers"
        if cache_key in self._ticker_cache:
            return self._ticker_cache[cache_key]

        # 先获取有效的交易符号列表，过滤掉结算中/已下架的合约
        valid_symbols = set(await self._refresh_binance_symbols())

        data = await self._request("/fapi/v1/ticker/24hr")
        if not data:
            return {}

        tickers = {}
        for item in data:
            symbol = item.get("symbol", "")
            # 只处理有效的 USDT 永续合约
            if symbol not in valid_symbols:
                continue

            try:
                price = float(item.get("lastPrice", 0))
                high = float(item.get("highPrice", 0))
                low = float(item.get("lowPrice", 0))
                volume = float(item.get("quoteVolume", 0))
                price_change_pct = float(item.get("priceChangePercent", 0))

                volatility = ((high - low) / price * 100) if price > 0 else 0

                tickers[symbol] = TickerData(
                    symbol=symbol,
                    price=price,
                    price_change_24h=price_change_pct,
                    volume_24h=volume,
                    high_24h=high,
                    low_24h=low,
                    volatility_24h=volatility
                )
            except (ValueError, TypeError) as e:
                logger.debug(f"Parse ticker error for {symbol}: {e}")
                continue

        self._ticker_cache[cache_key] = tickers
        logger.info(f"Fetched {len(tickers)} tickers from Binance")
        return tickers

    async def get_symbol_klines(self, symbol: str, interval: str = "1h", limit: int = 4) -> List[Dict]:
        """获取 K 线数据"""
        cache_key = f"kline_{symbol}_{interval}_{limit}"
        if cache_key in self._kline_cache:
            return self._kline_cache[cache_key]

        data = await self._request("/fapi/v1/klines", {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        })

        if not data:
            return []

        klines = []
        for k in data:
            klines.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
                "quote_volume": float(k[7])
            })

        self._kline_cache[cache_key] = klines
        return klines

    async def calculate_price_changes(self, symbol: str, current_price: float) -> Tuple[float, float]:
        """计算 1h 和 4h 价格变化"""
        try:
            # 获取 4h K线（包含1h和4h变化）
            klines_1h = await self.get_symbol_klines(symbol, "1h", 2)
            klines_4h = await self.get_symbol_klines(symbol, "4h", 2)

            price_change_1h = 0.0
            price_change_4h = 0.0

            if len(klines_1h) >= 2:
                prev_close = klines_1h[-2]["close"]
                if prev_close > 0:
                    price_change_1h = ((current_price - prev_close) / prev_close) * 100

            if len(klines_4h) >= 2:
                prev_close = klines_4h[-2]["close"]
                if prev_close > 0:
                    price_change_4h = ((current_price - prev_close) / prev_close) * 100

            return price_change_1h, price_change_4h
        except Exception as e:
            logger.debug(f"Calculate price changes error for {symbol}: {e}")
            return 0.0, 0.0

    async def calculate_all_price_changes(self, symbol: str, current_price: float) -> Dict[str, float]:
        """计算所有时间周期的价格变化

        Returns:
            包含各时间周期价格变化百分比的字典
        """
        result = {
            "1m": 0.0, "5m": 0.0, "15m": 0.0, "30m": 0.0,
            "1h": 0.0, "4h": 0.0, "8h": 0.0, "12h": 0.0,
            "24h": 0.0, "2d": 0.0, "3d": 0.0
        }

        try:
            # 并发获取多个时间周期的 K 线
            tasks = [
                self.get_symbol_klines(symbol, "1m", 2),
                self.get_symbol_klines(symbol, "5m", 2),
                self.get_symbol_klines(symbol, "15m", 2),
                self.get_symbol_klines(symbol, "30m", 2),
                self.get_symbol_klines(symbol, "1h", 2),
                self.get_symbol_klines(symbol, "4h", 2),
                self.get_symbol_klines(symbol, "8h", 2),
                self.get_symbol_klines(symbol, "12h", 2),
                self.get_symbol_klines(symbol, "1d", 4),  # 获取4根日线用于计算 24h/2d/3d
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "8h", "12h", "1d"]

            for i, (interval, klines) in enumerate(zip(intervals, results)):
                if isinstance(klines, Exception) or not klines:
                    continue

                if interval == "1d":
                    # 日线数据用于计算 24h/2d/3d
                    if len(klines) >= 2:
                        prev_close = klines[-2]["close"]
                        if prev_close > 0:
                            result["24h"] = ((current_price - prev_close) / prev_close) * 100
                    if len(klines) >= 3:
                        prev_close = klines[-3]["close"]
                        if prev_close > 0:
                            result["2d"] = ((current_price - prev_close) / prev_close) * 100
                    if len(klines) >= 4:
                        prev_close = klines[-4]["close"]
                        if prev_close > 0:
                            result["3d"] = ((current_price - prev_close) / prev_close) * 100
                else:
                    if len(klines) >= 2:
                        prev_close = klines[-2]["close"]
                        if prev_close > 0:
                            result[interval] = ((current_price - prev_close) / prev_close) * 100

        except Exception as e:
            logger.debug(f"Calculate all price changes error for {symbol}: {e}")

        return result

    async def get_all_oi(self, force_refresh: bool = False) -> Dict[str, OIData]:
        """获取所有合约持仓量（不含历史变化数据，用于快速扫描）"""
        cache_key = "all_oi"
        if not force_refresh and cache_key in self._oi_cache:
            return self._oi_cache[cache_key]

        # 实际上需要逐个获取
        # 只用 Binance 自己的 symbol 列表，避免把其他交易所的 symbol 发给 Binance API
        symbols = await self._refresh_binance_symbols()
        tickers = await self.get_all_tickers()

        oi_data = {}

        # 并发获取 OI 数据（分批处理避免限流）
        batch_size = self.OI_BATCH_SIZE
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self._get_symbol_oi(s, tickers.get(s), with_history=False) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for symbol, result in zip(batch, results):
                if isinstance(result, OIData):
                    oi_data[symbol] = result

            # 避免限流
            if i + batch_size < len(symbols):
                await asyncio.sleep(0.1)

        self._oi_cache[cache_key] = oi_data
        logger.info(f"Fetched {len(oi_data)} OI data from Binance")
        return oi_data

    async def get_oi_ranking_with_history(self, rank_type: str = "top", limit: int = 20) -> List[OIData]:
        """获取 OI 排行榜（带历史变化数据）

        Args:
            rank_type: "top" 增加最多, "low" 减少最多
            limit: 返回数量

        Returns:
            带历史变化数据的 OI 列表
        """
        cache_key = f"oi_ranking_{rank_type}_{limit}"
        if cache_key in self._oi_cache:
            return self._oi_cache[cache_key]

        # 先获取所有 OI 的基础数据（快速）
        all_oi = await self.get_all_oi()
        tickers = await self.get_all_tickers()

        # 按 OI 价值排序，取前 100 名作为候选
        sorted_oi = sorted(
            [(s, oi) for s, oi in all_oi.items() if oi.oi_value > 1_000_000],
            key=lambda x: x[1].oi_value,
            reverse=True
        )[:100]

        # 为候选币种获取历史数据
        oi_with_history = []
        batch_size = self.OI_HISTORY_BATCH_SIZE
        symbols_to_fetch = [s for s, _ in sorted_oi]

        for i in range(0, len(symbols_to_fetch), batch_size):
            batch = symbols_to_fetch[i:i+batch_size]
            tasks = [self._get_symbol_oi(s, tickers.get(s), with_history=True) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, OIData):
                    oi_with_history.append(result)

            # 避免限流
            if i + batch_size < len(symbols_to_fetch):
                await asyncio.sleep(0.1)

        # 根据类型排序
        if rank_type == "top":
            # OI 增加值最大
            oi_with_history.sort(key=lambda x: x.oi_delta_value_1h, reverse=True)
        else:
            # OI 减少值最大（负值最小）
            oi_with_history.sort(key=lambda x: x.oi_delta_value_1h)

        # 按 symbol 去重，保留排位靠前的
        seen = set()
        deduplicated = []
        for item in oi_with_history:
            if item.symbol not in seen:
                seen.add(item.symbol)
                deduplicated.append(item)

        result = deduplicated[:limit]
        self._oi_cache[cache_key] = result
        return result

    async def warmup_oi_rankings(self, limit: int = 20) -> Dict[str, List[OIData]]:
        """一次性预热 top 和 low OI 排行，共享历史数据获取，避免重复请求。

        Returns:
            {"top": [...], "low": [...]}
        """
        cache_key_top = f"oi_ranking_top_{limit}"
        cache_key_low = f"oi_ranking_low_{limit}"

        # 如果都已缓存直接返回
        if cache_key_top in self._oi_cache and cache_key_low in self._oi_cache:
            return {"top": self._oi_cache[cache_key_top], "low": self._oi_cache[cache_key_low]}

        all_oi = await self.get_all_oi()
        tickers = await self.get_all_tickers()

        sorted_oi = sorted(
            [(s, oi) for s, oi in all_oi.items() if oi.oi_value > 1_000_000],
            key=lambda x: x[1].oi_value,
            reverse=True
        )[:100]

        # 批量获取历史数据（只请求一次）
        oi_with_history = []
        batch_size = self.OI_HISTORY_BATCH_SIZE
        symbols_to_fetch = [s for s, _ in sorted_oi]

        for i in range(0, len(symbols_to_fetch), batch_size):
            batch = symbols_to_fetch[i:i+batch_size]
            tasks = [self._get_symbol_oi(s, tickers.get(s), with_history=True) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, OIData):
                    oi_with_history.append(r)
            if i + batch_size < len(symbols_to_fetch):
                await asyncio.sleep(0.1)

        # 按 symbol 去重，分别排序并缓存
        def _dedup(items: list) -> list:
            seen = set()
            result = []
            for item in items:
                if item.symbol not in seen:
                    seen.add(item.symbol)
                    result.append(item)
            return result

        top_sorted = sorted(oi_with_history, key=lambda x: x.oi_delta_value_1h, reverse=True)
        low_sorted = sorted(oi_with_history, key=lambda x: x.oi_delta_value_1h)

        top_result = _dedup(top_sorted)[:limit]
        low_result = _dedup(low_sorted)[:limit]

        self._oi_cache[cache_key_top] = top_result
        self._oi_cache[cache_key_low] = low_result

        return {"top": top_result, "low": low_result}

    async def _get_symbol_oi(self, symbol: str, ticker: Optional[TickerData] = None, with_history: bool = False) -> Optional[OIData]:
        """获取单个符号的 OI 数据

        Args:
            symbol: 交易对符号
            ticker: ticker 数据（可选，用于获取价格）
            with_history: 是否获取历史变化数据
        """
        # 校验 symbol 是否为 Binance 合约有效币种，避免对 OKX 独有 symbol 发起无效请求
        if self._usdt_symbols and symbol not in self._usdt_symbols:
            return None
        try:
            data = await self._request("/fapi/v1/openInterest", {"symbol": symbol})
            if not data:
                return None

            oi_coins = float(data.get("openInterest", 0))
            price = ticker.price if ticker else 0

            if price == 0:
                # 尝试从数据获取价格
                ticker_data = await self._request("/fapi/v1/ticker/price", {"symbol": symbol})
                if ticker_data:
                    price = float(ticker_data.get("price", 0))

            oi_value = oi_coins * price

            oi_change_1h = 0.0
            oi_change_4h = 0.0
            oi_delta_value_1h = 0.0

            # 获取历史数据计算变化
            if with_history:
                history = await self._request("/futures/data/openInterestHist", {
                    "symbol": symbol,
                    "period": "5m",
                    "limit": 50  # 获取最近50个5分钟数据
                })

                if history and len(history) > 0:
                    current_oi = float(history[-1].get("sumOpenInterest", oi_coins))
                    current_oi_value = float(history[-1].get("sumOpenInterestValue", oi_value))

                    # 1小时前 (12个5分钟)
                    if len(history) >= 12:
                        oi_1h_ago = float(history[-12].get("sumOpenInterest", current_oi))
                        oi_value_1h_ago = float(history[-12].get("sumOpenInterestValue", current_oi_value))
                        if oi_1h_ago > 0:
                            oi_change_1h = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100
                        oi_delta_value_1h = current_oi_value - oi_value_1h_ago

                    # 4小时前 (48个5分钟)
                    if len(history) >= 48:
                        oi_4h_ago = float(history[-48].get("sumOpenInterest", current_oi))
                        if oi_4h_ago > 0:
                            oi_change_4h = ((current_oi - oi_4h_ago) / oi_4h_ago) * 100

            return OIData(
                symbol=symbol,
                oi_value=oi_value,
                oi_coins=oi_coins,
                oi_change_1h=oi_change_1h,
                oi_change_4h=oi_change_4h,
                oi_delta_value_1h=oi_delta_value_1h
            )
        except Exception as e:
            logger.debug(f"Get OI error for {symbol}: {e}")
            return None

    async def get_oi_with_history(self, symbol: str, period: str = "1h") -> Optional[OIData]:
        """获取带历史变化的 OI 数据"""
        try:
            # 获取当前 OI
            current_data = await self._request("/fapi/v1/openInterest", {"symbol": symbol})
            if not current_data:
                return None

            oi_coins = float(current_data.get("openInterest", 0))

            # 获取价格
            ticker_data = await self._request("/fapi/v1/ticker/price", {"symbol": symbol})
            price = float(ticker_data.get("price", 0)) if ticker_data else 0

            oi_value = oi_coins * price

            # 获取历史 OI（使用 OI 统计接口）
            history = await self._request("/futures/data/openInterestHist", {
                "symbol": symbol,
                "period": "5m",
                "limit": 50  # 获取最近50个5分钟数据
            })

            oi_change_1h = 0.0
            oi_change_4h = 0.0
            oi_delta_value_1h = 0.0

            if history and len(history) > 0:
                current_oi = float(history[-1].get("sumOpenInterest", oi_coins))
                current_oi_value = float(history[-1].get("sumOpenInterestValue", oi_value))

                # 1小时前 (12个5分钟)
                if len(history) >= 12:
                    oi_1h_ago = float(history[-12].get("sumOpenInterest", current_oi))
                    oi_value_1h_ago = float(history[-12].get("sumOpenInterestValue", current_oi_value))
                    if oi_1h_ago > 0:
                        oi_change_1h = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100
                    oi_delta_value_1h = current_oi_value - oi_value_1h_ago

                # 4小时前 (48个5分钟)
                if len(history) >= 48:
                    oi_4h_ago = float(history[-48].get("sumOpenInterest", current_oi))
                    if oi_4h_ago > 0:
                        oi_change_4h = ((current_oi - oi_4h_ago) / oi_4h_ago) * 100

            return OIData(
                symbol=symbol,
                oi_value=oi_value,
                oi_coins=oi_coins,
                oi_change_1h=oi_change_1h,
                oi_change_4h=oi_change_4h,
                oi_delta_value_1h=oi_delta_value_1h
            )
        except Exception as e:
            logger.error(f"Get OI with history error for {symbol}: {e}")
            return None

    async def get_all_funding_rates(self) -> Dict[str, FundingData]:
        """获取所有合约资金费率"""
        cache_key = "all_funding"
        if cache_key in self._funding_cache:
            return self._funding_cache[cache_key]

        data = await self._request("/fapi/v1/premiumIndex")
        if not data:
            return {}

        funding_data = {}
        for item in data:
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            try:
                funding_data[symbol] = FundingData(
                    symbol=symbol,
                    funding_rate=float(item.get("lastFundingRate", 0)),
                    next_funding_time=int(item.get("nextFundingTime", 0))
                )
            except (ValueError, TypeError):
                continue

        self._funding_cache[cache_key] = funding_data
        logger.info(f"Fetched {len(funding_data)} funding rates from Binance")
        return funding_data

    async def get_top_gainers_losers(self, limit: int = 20) -> Tuple[List[TickerData], List[TickerData]]:
        """获取涨幅/跌幅榜"""
        tickers = await self.get_all_tickers()

        sorted_tickers = sorted(
            tickers.values(),
            key=lambda x: x.price_change_24h,
            reverse=True
        )

        # 过滤低交易量
        filtered = [t for t in sorted_tickers if t.volume_24h >= 1_000_000]

        gainers = filtered[:limit]
        losers = filtered[-limit:][::-1]  # 倒序取跌幅最大的

        return gainers, losers

    async def get_high_volatility_coins(self, min_volatility: float = 5.0, limit: int = 20) -> List[TickerData]:
        """获取高波动币种"""
        tickers = await self.get_all_tickers()

        high_vol = [
            t for t in tickers.values()
            if t.volatility_24h >= min_volatility and t.volume_24h >= 5_000_000
        ]

        # 按波动率排序
        high_vol.sort(key=lambda x: x.volatility_24h, reverse=True)

        return high_vol[:limit]

    async def calculate_vwap(self, symbol: str, interval: str = "1h", periods: int = 24) -> Dict[str, float]:
        """
        计算 VWAP (成交量加权平均价格)

        VWAP = Σ(典型价格 × 成交量) / Σ(成交量)
        典型价格 = (高 + 低 + 收) / 3

        Args:
            symbol: 交易对符号
            interval: K线周期 ("1m", "5m", "15m", "1h", "4h")
            periods: 计算周期数量

        Returns:
            包含 vwap 值和相关信号的字典
        """
        try:
            klines = await self.get_symbol_klines(symbol, interval, periods)

            if not klines or len(klines) < 2:
                return {"vwap": 0.0, "price_vs_vwap": 0.0}

            cumulative_tp_volume = 0.0
            cumulative_volume = 0.0

            for k in klines:
                typical_price = (k["high"] + k["low"] + k["close"]) / 3
                volume = k["quote_volume"]  # 使用 USDT 计价的成交量
                cumulative_tp_volume += typical_price * volume
                cumulative_volume += volume

            vwap = cumulative_tp_volume / cumulative_volume if cumulative_volume > 0 else 0.0

            # 当前价格
            current_price = klines[-1]["close"]

            # 价格相对于 VWAP 的偏离度 (%)
            price_vs_vwap = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0.0

            return {
                "vwap": vwap,
                "current_price": current_price,
                "price_vs_vwap": price_vs_vwap,  # 正值=价格在VWAP上方，负值=在下方
            }

        except Exception as e:
            logger.debug(f"Calculate VWAP error for {symbol}: {e}")
            return {"vwap": 0.0, "price_vs_vwap": 0.0}

    async def calculate_multi_period_vwap(self, symbol: str) -> Dict[str, Dict[str, float]]:
        """
        计算多周期 VWAP

        Returns:
            包含 1h 和 4h VWAP 数据的字典
        """
        try:
            # 并发获取多周期 VWAP
            vwap_1h_task = self.calculate_vwap(symbol, "15m", 4)   # 4个15分钟 = 1小时
            vwap_4h_task = self.calculate_vwap(symbol, "15m", 16)  # 16个15分钟 = 4小时

            vwap_1h, vwap_4h = await asyncio.gather(vwap_1h_task, vwap_4h_task)

            return {
                "1h": vwap_1h,
                "4h": vwap_4h
            }
        except Exception as e:
            logger.debug(f"Calculate multi-period VWAP error for {symbol}: {e}")
            return {
                "1h": {"vwap": 0.0, "price_vs_vwap": 0.0},
                "4h": {"vwap": 0.0, "price_vs_vwap": 0.0}
            }

    async def calculate_entry_timing(self, symbol: str, direction: str = "long") -> Dict:
        """
        计算入场时机指标（核心反追高逻辑）

        通过分析最近价格走势，判断当前是否适合入场：
        - 刚突破/暴涨：不适合追高，等待回调
        - 回调到支撑位：适合入场
        - 过度延伸：风险较高

        Args:
            symbol: 交易对符号
            direction: 交易方向 "long" 或 "short"

        Returns:
            {
                "timing": "optimal" | "wait_pullback" | "chasing" | "extended",
                "timing_score": 0-100 (越高越适合入场),
                "pullback_pct": 实际回调幅度,
                "required_pullback": 建议回调幅度,
                "atr_pct": ATR占价格百分比（波动性指标）,
                "support_distance": 距支撑位距离,
                "resistance_distance": 距阻力位距离,
                "swing_high": 近期高点,
                "swing_low": 近期低点,
                "reasons": []
            }
        """
        result = {
            "timing": "neutral",
            "timing_score": 50,
            "pullback_pct": 0.0,
            "required_pullback": 2.0,
            "atr_pct": 0.0,
            "support_distance": 0.0,
            "resistance_distance": 0.0,
            "swing_high": 0.0,
            "swing_low": 0.0,
            "reasons": []
        }

        try:
            # 获取多周期K线数据
            klines_15m = await self.get_symbol_klines(symbol, "15m", 24)  # 6小时
            klines_1h = await self.get_symbol_klines(symbol, "1h", 24)    # 24小时
            klines_4h = await self.get_symbol_klines(symbol, "4h", 12)    # 48小时

            if not klines_15m or len(klines_15m) < 8:
                result["reasons"].append("数据不足")
                return result

            current_price = klines_15m[-1]["close"]

            # 1. 计算 ATR（波动性）
            atr = self._calculate_atr(klines_1h[-14:] if len(klines_1h) >= 14 else klines_1h)
            atr_pct = (atr / current_price * 100) if current_price > 0 else 0
            result["atr_pct"] = round(atr_pct, 3)

            # 2. 计算动态回调要求（基于波动性）
            # 高波动币种需要更大回调，低波动币种回调要求低
            if atr_pct > 5:
                required_pullback = min(atr_pct * 0.8, 8.0)  # 高波动：需要更多回调
            elif atr_pct > 3:
                required_pullback = atr_pct * 0.6
            else:
                required_pullback = max(atr_pct * 0.5, 1.0)  # 最少1%
            result["required_pullback"] = round(required_pullback, 2)

            # 3. 找出近期高低点（支撑/阻力）
            highs_1h = [k["high"] for k in klines_1h[-12:]]  # 12小时内高点
            lows_1h = [k["low"] for k in klines_1h[-12:]]
            swing_high = max(highs_1h) if highs_1h else current_price
            swing_low = min(lows_1h) if lows_1h else current_price

            result["swing_high"] = swing_high
            result["swing_low"] = swing_low

            # 4. 计算距离支撑/阻力的百分比
            if swing_high > swing_low:
                result["resistance_distance"] = round((swing_high - current_price) / current_price * 100, 2)
                result["support_distance"] = round((current_price - swing_low) / current_price * 100, 2)

            # 5. 分析价格走势：是刚突破还是回调
            # 计算最近2小时和6小时的价格变化
            price_2h_ago = klines_15m[-8]["close"] if len(klines_15m) >= 8 else current_price
            price_6h_ago = klines_15m[0]["close"]

            change_2h = (current_price - price_2h_ago) / price_2h_ago * 100 if price_2h_ago > 0 else 0
            change_6h = (current_price - price_6h_ago) / price_6h_ago * 100 if price_6h_ago > 0 else 0

            # 6. 判断入场时机
            timing_score = 50
            reasons = []

            if direction == "long":
                # === 做多入场时机分析 ===

                # 计算从高点回调的幅度
                pullback_from_high = (swing_high - current_price) / swing_high * 100 if swing_high > 0 else 0
                result["pullback_pct"] = round(pullback_from_high, 2)

                # 情况1: 刚暴涨，追高风险
                if change_2h > required_pullback * 0.8:
                    timing_score -= 30
                    reasons.append(f"2h涨幅{change_2h:.1f}%过大，追高风险")
                    result["timing"] = "chasing"

                # 情况2: 价格过度延伸（离阻力太近）
                elif result["resistance_distance"] < required_pullback * 0.3:
                    timing_score -= 20
                    reasons.append(f"距阻力位仅{result['resistance_distance']:.1f}%，空间有限")
                    result["timing"] = "extended"

                # 情况3: 回调到位，最佳入场
                elif pullback_from_high >= required_pullback * 0.7:
                    timing_score += 30
                    reasons.append(f"从高点回调{pullback_from_high:.1f}%已到位")
                    # 额外检查：是否接近支撑
                    if result["support_distance"] < required_pullback * 0.5:
                        timing_score += 15
                        reasons.append(f"接近支撑位")
                    result["timing"] = "optimal"

                # 情况4: 正在回调中，等待
                elif change_2h < 0 and pullback_from_high > 0:
                    timing_score += 10
                    reasons.append(f"正在回调中({pullback_from_high:.1f}%)，继续等待")
                    result["timing"] = "wait_pullback"

                # 情况5: 横盘整理
                elif abs(change_2h) < required_pullback * 0.3:
                    timing_score += 5
                    reasons.append("横盘整理中")
                    result["timing"] = "neutral"

            else:
                # === 做空入场时机分析 ===

                # 计算从低点反弹的幅度
                bounce_from_low = (current_price - swing_low) / swing_low * 100 if swing_low > 0 else 0
                result["pullback_pct"] = round(bounce_from_low, 2)  # 对于做空，记录反弹幅度

                # 情况1: 刚暴跌，追空风险
                if change_2h < -required_pullback * 0.8:
                    timing_score -= 30
                    reasons.append(f"2h跌幅{abs(change_2h):.1f}%过大，追空风险")
                    result["timing"] = "chasing"

                # 情况2: 价格过度延伸（离支撑太近）
                elif result["support_distance"] < required_pullback * 0.3:
                    timing_score -= 20
                    reasons.append(f"距支撑位仅{result['support_distance']:.1f}%，反弹风险")
                    result["timing"] = "extended"

                # 情况3: 反弹到位，最佳做空点
                elif bounce_from_low >= required_pullback * 0.7:
                    timing_score += 30
                    reasons.append(f"从低点反弹{bounce_from_low:.1f}%已到位")
                    # 额外检查：是否接近阻力
                    if result["resistance_distance"] < required_pullback * 0.5:
                        timing_score += 15
                        reasons.append(f"接近阻力位")
                    result["timing"] = "optimal"

                # 情况4: 正在反弹中，等待
                elif change_2h > 0 and bounce_from_low > 0:
                    timing_score += 10
                    reasons.append(f"正在反弹中({bounce_from_low:.1f}%)，等待到位")
                    result["timing"] = "wait_pullback"

            # 7. 额外调整：趋势强度
            if len(klines_4h) >= 6:
                trend_strength = self._calculate_trend_strength(klines_4h[-6:], direction)
                if trend_strength > 0.7:
                    timing_score += 10
                    reasons.append("趋势强劲")
                elif trend_strength < 0.3:
                    timing_score -= 10
                    reasons.append("趋势较弱")

            result["timing_score"] = max(0, min(100, timing_score))
            result["reasons"] = reasons

        except Exception as e:
            logger.debug(f"Calculate entry timing error for {symbol}: {e}")
            result["reasons"].append(f"计算错误: {str(e)}")

        return result

    def _calculate_atr(self, klines: List[Dict]) -> float:
        """计算 ATR (Average True Range)"""
        if not klines or len(klines) < 2:
            return 0.0

        tr_values = []
        for i in range(1, len(klines)):
            high = klines[i]["high"]
            low = klines[i]["low"]
            prev_close = klines[i-1]["close"]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)

        return sum(tr_values) / len(tr_values) if tr_values else 0.0

    def _calculate_trend_strength(self, klines: List[Dict], direction: str) -> float:
        """
        计算趋势强度 (0-1)

        Args:
            klines: K线数据
            direction: "long" 或 "short"

        Returns:
            0-1 的趋势强度值，越高表示趋势越明确
        """
        if not klines or len(klines) < 3:
            return 0.5

        # 计算收盘价变化方向一致性
        bullish_bars = 0
        bearish_bars = 0

        for i in range(1, len(klines)):
            if klines[i]["close"] > klines[i-1]["close"]:
                bullish_bars += 1
            elif klines[i]["close"] < klines[i-1]["close"]:
                bearish_bars += 1

        total_bars = len(klines) - 1

        if direction == "long":
            return bullish_bars / total_bars if total_bars > 0 else 0.5
        else:
            return bearish_bars / total_bars if total_bars > 0 else 0.5
