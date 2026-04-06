#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX 市场数据采集器（以公共行情接口为主，认证信息仅为后续私有扩展预留）。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import aiohttp
from cachetools import TTLCache

logger = logging.getLogger(__name__)


@dataclass
class OKXSwapTicker:
    symbol: str
    inst_id: str
    price: float
    price_change_24h: float = 0.0
    volume_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    open_24h: float = 0.0
    last_update: float = field(default_factory=time.time)


@dataclass
class OKXFundingInfo:
    symbol: str
    inst_id: str
    funding_rate: float
    next_funding_time: int
    last_update: float = field(default_factory=time.time)


@dataclass
class OKXOIInfo:
    symbol: str
    inst_id: str
    oi_contracts: float
    oi_value_usd: float
    oi_delta_percent: float = 0.0
    oi_delta_value: float = 0.0
    last_update: float = field(default_factory=time.time)


class OKXCollector:
    BASE_URL = "https://www.okx.com"

    INTERVAL_MAP = {
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "2h": "2H",
        "4h": "4H",
        "6h": "6H",
        "12h": "12H",
        "1d": "1D",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        enabled: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.enabled = enabled
        self.session: Optional[aiohttp.ClientSession] = None

        self._instrument_cache: TTLCache = TTLCache(maxsize=4, ttl=1800)
        self._tickers_cache: TTLCache = TTLCache(maxsize=8, ttl=10)
        self._funding_cache: TTLCache = TTLCache(maxsize=2000, ttl=60)
        self._oi_cache: TTLCache = TTLCache(maxsize=2000, ttl=60)
        self._kline_cache: TTLCache = TTLCache(maxsize=1000, ttl=30)
        self._book_cache: TTLCache = TTLCache(maxsize=500, ttl=10)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"Content-Type": "application/json"})
        return self.session

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    def _sign_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        if not (self.api_key and self.api_secret and self.api_passphrase):
            return {}
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        prehash = f"{ts}{method.upper()}{request_path}{body}"
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.api_passphrase,
        }

    async def _request(self, path: str, params: Optional[dict] = None, private: bool = False) -> dict:
        if not self.enabled:
            return {}
        session = await self._get_session()
        query = ""
        if params:
            from urllib.parse import urlencode
            query = "?" + urlencode({k: v for k, v in params.items() if v is not None})
        request_path = f"{path}{query}"
        headers = self._sign_headers("GET", request_path) if private else {}
        url = f"{self.BASE_URL}{request_path}"
        try:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    logger.debug("OKX API error %s on %s: %s", resp.status, request_path, await resp.text())
                    return {}
                data = await resp.json()
                if isinstance(data, dict) and data.get("code") in ("0", 0, None):
                    return data
                return data if isinstance(data, dict) else {}
        except asyncio.TimeoutError:
            logger.warning("OKX API timeout: %s", request_path)
            return {}
        except Exception as exc:
            logger.warning("OKX API error: %s", exc)
            return {}

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        symbol = symbol.upper().strip().replace("-", "")
        if symbol.endswith("USDT"):
            return symbol
        return f"{symbol}USDT"

    @staticmethod
    def to_swap_inst_id(symbol: str) -> str:
        symbol = OKXCollector.normalize_symbol(symbol)
        base = symbol[:-4]
        return f"{base}-USDT-SWAP"

    @staticmethod
    def to_spot_inst_id(symbol: str) -> str:
        symbol = OKXCollector.normalize_symbol(symbol)
        base = symbol[:-4]
        return f"{base}-USDT"

    async def get_swap_instruments(self) -> Dict[str, dict]:
        cache_key = "swap_instruments"
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]
        payload = await self._request("/api/v5/public/instruments", {"instType": "SWAP"})
        results: Dict[str, dict] = {}
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            try:
                if item.get("state") and item.get("state") != "live":
                    continue
                settle_ccy = (item.get("settleCcy") or "").upper()
                quote_ccy = (item.get("quoteCcy") or "").upper()
                if settle_ccy != "USDT" and quote_ccy != "USDT":
                    continue
                inst_id = item.get("instId")
                if not inst_id or not inst_id.endswith("-SWAP"):
                    continue
                base = (item.get("ctValCcy") or item.get("baseCcy") or "").upper()
                if not base:
                    continue
                symbol = f"{base}USDT"
                results[symbol] = item
            except Exception:
                continue
        self._instrument_cache[cache_key] = results
        return results

    async def get_swap_symbols(self) -> List[str]:
        return sorted((await self.get_swap_instruments()).keys())

    async def get_all_swap_tickers(self) -> Dict[str, OKXSwapTicker]:
        cache_key = "swap_tickers"
        if cache_key in self._tickers_cache:
            return self._tickers_cache[cache_key]
        payload = await self._request("/api/v5/market/tickers", {"instType": "SWAP"})
        instruments = await self.get_swap_instruments()
        results: Dict[str, OKXSwapTicker] = {}
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            inst_id = item.get("instId")
            try:
                base = inst_id.split("-")[0].upper()
                symbol = f"{base}USDT"
                if symbol not in instruments:
                    continue
                last = float(item.get("last") or 0)
                open_24h = float(item.get("open24h") or 0)
                high_24h = float(item.get("high24h") or 0)
                low_24h = float(item.get("low24h") or 0)
                vol_ccy_24h = float(item.get("volCcy24h") or 0)
                price_change_24h = ((last - open_24h) / open_24h * 100) if open_24h > 0 else 0.0
                results[symbol] = OKXSwapTicker(
                    symbol=symbol,
                    inst_id=inst_id,
                    price=last,
                    price_change_24h=price_change_24h,
                    volume_24h=vol_ccy_24h,
                    high_24h=high_24h,
                    low_24h=low_24h,
                    open_24h=open_24h,
                )
            except Exception:
                continue
        self._tickers_cache[cache_key] = results
        return results

    async def get_symbol_klines(self, symbol: str, interval: str = "1h", limit: int = 24, trade: str = "swap") -> List[dict]:
        symbol = self.normalize_symbol(symbol)
        bar = self.INTERVAL_MAP.get(interval, "1H")
        inst_id = self.to_swap_inst_id(symbol) if trade == "swap" else self.to_spot_inst_id(symbol)
        cache_key = f"k:{trade}:{inst_id}:{bar}:{limit}"
        if cache_key in self._kline_cache:
            return self._kline_cache[cache_key]
        path = "/api/v5/market/candles"
        payload = await self._request(path, {"instId": inst_id, "bar": bar, "limit": max(limit, 2)})
        rows: List[dict] = []
        data = payload.get("data", []) if isinstance(payload, dict) else []
        for row in reversed(data[-limit:]):
            try:
                # ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm
                rows.append(
                    {
                        "open_time": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                        "quote_volume": float(row[7]) if len(row) > 7 else float(row[6]) if len(row) > 6 else 0.0,
                        "close_time": int(row[0]),
                        "trade_count": 0,
                        "taker_buy_quote_volume": 0.0,
                    }
                )
            except Exception:
                continue
        self._kline_cache[cache_key] = rows
        return rows

    async def get_orderbook(self, symbol: str, trade: str = "swap", depth: int = 100) -> dict:
        symbol = self.normalize_symbol(symbol)
        inst_id = self.to_swap_inst_id(symbol) if trade == "swap" else self.to_spot_inst_id(symbol)
        cache_key = f"book:{trade}:{inst_id}:{depth}"
        if cache_key in self._book_cache:
            return self._book_cache[cache_key]
        payload = await self._request("/api/v5/market/books", {"instId": inst_id, "sz": depth})
        data = payload.get("data", []) if isinstance(payload, dict) else []
        result = data[0] if data else {}
        if isinstance(result, dict):
            self._book_cache[cache_key] = result
            return result
        return {}

    async def get_funding_rate(self, symbol: str) -> Optional[OKXFundingInfo]:
        symbol = self.normalize_symbol(symbol)
        cache_key = f"funding:{symbol}"
        if cache_key in self._funding_cache:
            return self._funding_cache[cache_key]
        inst_id = self.to_swap_inst_id(symbol)
        payload = await self._request("/api/v5/public/funding-rate", {"instId": inst_id})
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not data:
            return None
        item = data[0]
        try:
            info = OKXFundingInfo(
                symbol=symbol,
                inst_id=inst_id,
                funding_rate=float(item.get("fundingRate") or 0),
                next_funding_time=int(item.get("nextFundingTime") or 0),
            )
            self._funding_cache[cache_key] = info
            return info
        except Exception:
            return None

    async def get_open_interest(self, symbol: str) -> Optional[OKXOIInfo]:
        symbol = self.normalize_symbol(symbol)
        cache_key = f"oi:{symbol}"
        if cache_key in self._oi_cache:
            return self._oi_cache[cache_key]
        inst_id = self.to_swap_inst_id(symbol)
        payload = await self._request("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst_id})
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not data:
            return None
        item = data[0]
        try:
            oi_contracts = float(item.get("oi") or 0)
            oi_ccy = float(item.get("oiCcy") or 0)
            ticker = (await self.get_all_swap_tickers()).get(symbol)
            price = ticker.price if ticker else 0.0
            oi_value = oi_ccy * price if oi_ccy > 0 and price > 0 else oi_contracts * price
            info = OKXOIInfo(
                symbol=symbol,
                inst_id=inst_id,
                oi_contracts=oi_contracts,
                oi_value_usd=oi_value,
            )
            self._oi_cache[cache_key] = info
            return info
        except Exception:
            return None

    async def get_all_funding_rates(self, symbols: Optional[List[str]] = None) -> Dict[str, OKXFundingInfo]:
        symbols = symbols or await self.get_swap_symbols()
        tasks = [self.get_funding_rate(sym) for sym in symbols]
        rows = await asyncio.gather(*tasks, return_exceptions=True)
        results: Dict[str, OKXFundingInfo] = {}
        for row in rows:
            if isinstance(row, OKXFundingInfo):
                results[row.symbol] = row
        return results

    async def get_all_open_interest(self, symbols: Optional[List[str]] = None) -> Dict[str, OKXOIInfo]:
        symbols = symbols or await self.get_swap_symbols()
        tasks = [self.get_open_interest(sym) for sym in symbols]
        rows = await asyncio.gather(*tasks, return_exceptions=True)
        results: Dict[str, OKXOIInfo] = {}
        for row in rows:
            if isinstance(row, OKXOIInfo):
                results[row.symbol] = row
        return results
