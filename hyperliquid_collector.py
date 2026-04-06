#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hyperliquid 公共市场数据采集器。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import aiohttp
from cachetools import TTLCache

logger = logging.getLogger(__name__)


@dataclass
class HyperliquidAssetContext:
    symbol: str
    coin: str
    price: float
    funding_rate: float
    open_interest: float
    oi_value_usd: float
    prev_day_price: float = 0.0
    day_notional_volume: float = 0.0
    day_base_volume: float = 0.0
    premium: float = 0.0
    last_update: float = field(default_factory=time.time)


@dataclass
class HyperliquidHeatmap:
    symbol: str
    bid_volume: float
    ask_volume: float
    delta: float
    delta_history: List[float]
    large_bids: List[dict]
    large_asks: List[dict]
    last_update: float = field(default_factory=time.time)


class HyperliquidCollector:
    BASE_URL = "https://api.hyperliquid.xyz"

    INTERVAL_TO_MS = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
        "8h": 28_800_000,
        "12h": 43_200_000,
        "1d": 86_400_000,
        "3d": 259_200_000,
        "1w": 604_800_000,
        "1M": 2_592_000_000,
    }

    def __init__(self, dex: str = ""):
        self.dex = dex
        self.session: Optional[aiohttp.ClientSession] = None
        self._meta_cache: TTLCache = TTLCache(maxsize=5, ttl=300)
        self._ctx_cache: TTLCache = TTLCache(maxsize=5, ttl=10)
        self._kline_cache: TTLCache = TTLCache(maxsize=2000, ttl=30)
        self._book_cache: TTLCache = TTLCache(maxsize=500, ttl=10)
        self._heatmap_delta_history: Dict[str, List[float]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"Content-Type": "application/json"})
        return self.session

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _post(self, payload: dict) -> object:
        session = await self._get_session()
        try:
            async with session.post(f"{self.BASE_URL}/info", json=payload, timeout=15) as resp:
                if resp.status != 200:
                    logger.warning("Hyperliquid API error %s: %s", resp.status, await resp.text())
                    return {}
                return await resp.json()
        except asyncio.TimeoutError:
            logger.warning("Hyperliquid API timeout: %s", payload.get("type"))
            return {}
        except Exception as exc:
            logger.warning("Hyperliquid API error: %s", exc)
            return {}

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        symbol = symbol.upper().strip()
        if symbol.endswith("USDT"):
            return symbol
        if symbol.endswith("-USDT"):
            return symbol.replace("-USDT", "USDT")
        return f"{symbol}USDT"

    @staticmethod
    def to_hl_coin(symbol: str) -> str:
        symbol = symbol.upper().strip()
        if symbol.endswith("USDT"):
            return symbol[:-4]
        if symbol.endswith("-USDT"):
            return symbol[:-5]
        return symbol

    async def get_meta(self) -> dict:
        cache_key = f"meta:{self.dex}"
        if cache_key in self._meta_cache:
            return self._meta_cache[cache_key]
        payload = {"type": "meta"}
        if self.dex:
            payload["dex"] = self.dex
        data = await self._post(payload)
        if isinstance(data, dict):
            self._meta_cache[cache_key] = data
            return data
        return {}

    async def get_meta_and_asset_contexts(self) -> Tuple[dict, List[dict]]:
        cache_key = f"meta_ctx:{self.dex}"
        if cache_key in self._ctx_cache:
            return self._ctx_cache[cache_key]

        payload = {"type": "metaAndAssetCtxs"}
        if self.dex:
            payload["dex"] = self.dex
        data = await self._post(payload)
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[0], dict) and isinstance(data[1], list):
            result = (data[0], data[1])
            self._ctx_cache[cache_key] = result
            return result
        return {}, []

    async def get_universe_symbols(self) -> List[str]:
        meta = await self.get_meta()
        symbols: List[str] = []
        for item in meta.get("universe", []):
            name = item.get("name")
            if not name:
                continue
            if item.get("isDelisted"):
                continue
            symbols.append(self.normalize_symbol(name))
        return symbols

    async def get_all_asset_contexts(self) -> Dict[str, HyperliquidAssetContext]:
        meta, contexts = await self.get_meta_and_asset_contexts()
        universe = meta.get("universe", []) if isinstance(meta, dict) else []
        results: Dict[str, HyperliquidAssetContext] = {}

        for item, ctx in zip(universe, contexts):
            coin = item.get("name")
            if not coin or item.get("isDelisted"):
                continue
            symbol = self.normalize_symbol(coin)
            price = float(ctx.get("midPx") or ctx.get("markPx") or ctx.get("oraclePx") or 0)
            open_interest = float(ctx.get("openInterest") or 0)
            oi_value = open_interest * price
            results[symbol] = HyperliquidAssetContext(
                symbol=symbol,
                coin=coin,
                price=price,
                funding_rate=float(ctx.get("funding") or 0),
                open_interest=open_interest,
                oi_value_usd=oi_value,
                prev_day_price=float(ctx.get("prevDayPx") or 0),
                day_notional_volume=float(ctx.get("dayNtlVlm") or 0),
                day_base_volume=float(ctx.get("dayBaseVlm") or 0),
                premium=float(ctx.get("premium") or 0),
            )
        return results

    async def get_coin_context(self, symbol: str) -> Optional[HyperliquidAssetContext]:
        return (await self.get_all_asset_contexts()).get(self.normalize_symbol(symbol))

    async def get_symbol_klines(self, symbol: str, interval: str = "1h", limit: int = 24) -> List[dict]:
        hl_coin = self.to_hl_coin(symbol)
        cache_key = f"k:{hl_coin}:{interval}:{limit}:{self.dex}"
        if cache_key in self._kline_cache:
            return self._kline_cache[cache_key]

        interval_ms = self.INTERVAL_TO_MS.get(interval, self.INTERVAL_TO_MS["1h"])
        end_time = int(time.time() * 1000)
        start_time = end_time - interval_ms * max(limit, 2)

        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": hl_coin,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
            },
        }
        if self.dex:
            payload["dex"] = self.dex

        data = await self._post(payload)
        if not isinstance(data, list):
            return []

        klines: List[dict] = []
        for item in data[-limit:]:
            try:
                klines.append(
                    {
                        "open_time": int(item.get("t", 0)),
                        "open": float(item.get("o", 0)),
                        "high": float(item.get("h", 0)),
                        "low": float(item.get("l", 0)),
                        "close": float(item.get("c", 0)),
                        "volume": float(item.get("v", 0)),
                        "close_time": int(item.get("T", 0)),
                        "quote_volume": float(item.get("v", 0)) * float(item.get("c", 0)),
                        "trade_count": int(item.get("n", 0)),
                        "taker_buy_quote_volume": 0.0,
                    }
                )
            except (TypeError, ValueError):
                continue

        self._kline_cache[cache_key] = klines
        return klines

    async def get_l2_book(self, symbol: str) -> dict:
        hl_coin = self.to_hl_coin(symbol)
        cache_key = f"book:{hl_coin}:{self.dex}"
        if cache_key in self._book_cache:
            return self._book_cache[cache_key]
        payload = {"type": "l2Book", "coin": hl_coin}
        if self.dex:
            payload["dex"] = self.dex
        data = await self._post(payload)
        if isinstance(data, dict):
            self._book_cache[cache_key] = data
            return data
        return {}

    async def get_orderbook_heatmap(self, symbol: str) -> Optional[HyperliquidHeatmap]:
        symbol = self.normalize_symbol(symbol)
        data = await self.get_l2_book(symbol)
        if not data:
            return None

        levels = data.get("levels") or []
        if len(levels) < 2:
            return None

        def _parse_levels(raw_levels: List[dict]) -> Tuple[float, List[dict]]:
            total = 0.0
            parsed: List[dict] = []
            for item in raw_levels:
                px = float(item.get("px") or 0)
                sz = float(item.get("sz") or 0)
                volume = px * sz
                total += volume
                parsed.append({"price": px, "quantity": sz, "volume": volume})
            parsed.sort(key=lambda x: x["volume"], reverse=True)
            return total, parsed[:5]

        bid_volume, large_bids = _parse_levels(levels[0])
        ask_volume, large_asks = _parse_levels(levels[1])
        delta = bid_volume - ask_volume

        history = self._heatmap_delta_history.setdefault(symbol, [])
        history.append(delta)
        if len(history) > 10:
            del history[:-10]

        return HyperliquidHeatmap(
            symbol=symbol,
            bid_volume=bid_volume,
            ask_volume=ask_volume,
            delta=delta,
            delta_history=list(history),
            large_bids=large_bids,
            large_asks=large_asks,
        )
