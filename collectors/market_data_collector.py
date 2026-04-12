#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多源市场数据聚合器：Binance 为主，OKX 为补充。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
from cachetools import TTLCache

from collectors.binance_collector import BinanceCollector, FundingData, OIData, TickerData
from collectors.okx_collector import OKXCollector

logger = logging.getLogger(__name__)


class UnifiedMarketCollector(BinanceCollector):
    """兼容 BinanceCollector 接口的多源聚合器。"""

    PRICE_RANKING_CANDIDATES = 60
    NETFLOW_CANDIDATES = 60
    HEATMAP_LIST_CANDIDATES = 30

    DURATION_TO_INTERVAL = {
        "1m": ("1m", 1),
        "5m": ("5m", 1),
        "15m": ("15m", 1),
        "30m": ("30m", 1),
        "1h": ("1h", 1),
        "4h": ("4h", 1),
        "8h": ("1h", 8),
        "12h": ("1h", 12),
        "24h": ("1h", 24),
        "1d": ("1h", 24),
        "2d": ("4h", 12),
        "3d": ("4h", 18),
        "5d": ("4h", 30),
        "7d": ("1d", 7),
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        okx_enabled: bool = True,
        okx_api_key: Optional[str] = None,
        okx_api_secret: Optional[str] = None,
        okx_api_passphrase: Optional[str] = None,
        snapshot_file: str = "data/provider_snapshots.json",
        focus_symbols: Optional[List[str]] = None,
        universe_mode: str = "fixed",
    ):
        super().__init__(api_key=api_key, api_secret=api_secret)
        self.okx_enabled = okx_enabled
        self.okx = OKXCollector(
            api_key=okx_api_key,
            api_secret=okx_api_secret,
            api_passphrase=okx_api_passphrase,
            enabled=okx_enabled,
        ) if okx_enabled else None
        self.snapshot_file = snapshot_file
        self.focus_symbols = {s.upper().strip() for s in (focus_symbols or []) if s}
        self.universe_mode = (universe_mode or "fixed").lower()
        self._spot_kline_cache: TTLCache = TTLCache(maxsize=1000, ttl=30)
        self._price_ranking_cache: TTLCache = TTLCache(maxsize=50, ttl=20)
        self._netflow_cache: TTLCache = TTLCache(maxsize=100, ttl=20)
        self._heatmap_cache: TTLCache = TTLCache(maxsize=500, ttl=15)
        self._provider_status: Dict[str, Any] = {
            "binance": {"enabled": True, "last_success": 0, "errors": 0},
            "okx": {"enabled": okx_enabled, "last_success": 0, "errors": 0},
        }
        self._provider_success_logs: Set[str] = set()
        self._snapshot_state: Dict[str, Any] = self._load_snapshot_state()

    async def close(self):
        await super().close()
        if self.okx and hasattr(self.okx, "close"):
            maybe = self.okx.close()
            if asyncio.iscoroutine(maybe):
                await maybe
        self._save_snapshot_state()

    # ---------- 基础状态 ----------
    def _load_snapshot_state(self) -> Dict[str, Any]:
        if not self.snapshot_file:
            return {}
        try:
            if os.path.exists(self.snapshot_file):
                with open(self.snapshot_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        return data
        except Exception as exc:
            logger.warning("加载快照状态失败: %s", exc)
        return {}

    def _save_snapshot_state(self) -> None:
        if not self.snapshot_file:
            return
        try:
            os.makedirs(os.path.dirname(self.snapshot_file), exist_ok=True)
            with open(self.snapshot_file, "w", encoding="utf-8") as fh:
                json.dump(self._snapshot_state, fh, ensure_ascii=False)
        except Exception as exc:
            logger.warning("保存快照状态失败: %s", exc)

    def _mark_provider_success(self, provider: str) -> None:
        self._provider_status.setdefault(provider, {"enabled": True, "last_success": 0, "errors": 0})
        self._provider_status[provider]["last_success"] = int(time.time())

    def _mark_provider_error(self, provider: str) -> None:
        self._provider_status.setdefault(provider, {"enabled": True, "last_success": 0, "errors": 0})
        self._provider_status[provider]["errors"] += 1

    def _log_provider_success_once(self, provider: str, resource: str, count: int) -> None:
        log_key = f"{provider}:{resource}"
        if log_key in self._provider_success_logs:
            return
        self._provider_success_logs.add(log_key)
        logger.info("%s market API connected, loaded %d %s", provider.capitalize(), count, resource)

    def get_provider_status(self) -> Dict[str, Any]:
        return self._provider_status

    def _should_include_symbol(self, symbol: str) -> bool:
        symbol = symbol.upper().strip()
        if self.universe_mode == "all":
            return True
        if self.universe_mode == "fixed":
            return not self.focus_symbols or symbol in self.focus_symbols
        # hybrid
        return True

    def _apply_universe_filter(self, symbols: List[str]) -> List[str]:
        if self.universe_mode != "fixed" or not self.focus_symbols:
            return sorted(set(symbols))
        return [s for s in sorted(set(symbols)) if s in self.focus_symbols]

    def _oi_history_key(self, provider: str) -> str:
        return f"{provider}_oi"

    # ---------- 多源 symbol / ticker ----------
    async def get_usdt_symbols(self, force_refresh: bool = False) -> List[str]:
        binance_symbols = await super().get_usdt_symbols(force_refresh=force_refresh)
        merged = set(binance_symbols)

        if self.okx:
            try:
                okx_symbols = await self.okx.get_swap_symbols()
                merged.update(okx_symbols)
                self._mark_provider_success("okx")
                self._log_provider_success_once("okx", "symbols", len(okx_symbols))
            except Exception as exc:
                logger.warning("获取 OKX symbols 失败: %s", exc)
                self._mark_provider_error("okx")

        return self._apply_universe_filter(list(merged))

    async def get_all_tickers(self) -> Dict[str, TickerData]:
        tickers = await super().get_all_tickers()
        if tickers:
            self._mark_provider_success("binance")

        if self.okx:
            try:
                okx_tickers = await self.okx.get_all_swap_tickers()
                self._mark_provider_success("okx")
            except Exception as exc:
                logger.warning("获取 OKX tickers 失败: %s", exc)
                self._mark_provider_error("okx")
                okx_tickers = {}

            for symbol, item in okx_tickers.items():
                if symbol in tickers or not self._should_include_symbol(symbol):
                    continue
                volatility = ((item.high_24h - item.low_24h) / item.price * 100) if item.price > 0 else abs(item.price_change_24h)
                tickers[symbol] = TickerData(
                    symbol=symbol,
                    price=item.price,
                    price_change_24h=item.price_change_24h,
                    volume_24h=item.volume_24h,
                    high_24h=item.high_24h,
                    low_24h=item.low_24h,
                    volatility_24h=volatility,
                )

        if self.universe_mode == "fixed" and self.focus_symbols:
            tickers = {k: v for k, v in tickers.items() if k in self.focus_symbols}
        return tickers

    async def get_symbol_klines(self, symbol: str, interval: str = "1h", limit: int = 4) -> List[Dict]:
        binance_symbols = set(await super().get_usdt_symbols())
        symbol = symbol.upper().strip()
        if symbol in binance_symbols:
            klines = await super().get_symbol_klines(symbol, interval=interval, limit=limit)
            if klines:
                return klines

        if self.okx:
            klines = await self.okx.get_symbol_klines(symbol, interval=interval, limit=limit, trade="swap")
            if klines:
                self._mark_provider_success("okx")
                return klines
        return []

    def _append_oi_snapshot(self, provider: str, symbol: str, oi: float, price: float) -> List[dict]:
        key = self._oi_history_key(provider)
        provider_state = self._snapshot_state.setdefault(key, {})
        history = provider_state.setdefault(symbol, [])
        now = int(time.time())
        history.append({"ts": now, "oi": oi, "price": price})
        cutoff = now - 8 * 24 * 3600
        provider_state[symbol] = [item for item in history if item.get("ts", 0) >= cutoff]
        return provider_state[symbol]

    async def get_all_oi(self, force_refresh: bool = False) -> Dict[str, OIData]:
        results = await super().get_all_oi(force_refresh=force_refresh)
        if results:
            self._mark_provider_success("binance")
        if self.universe_mode == "fixed" and self.focus_symbols:
            results = {k: v for k, v in results.items() if k in self.focus_symbols}

        if self.okx:
            try:
                symbols = self._apply_universe_filter(await self.okx.get_swap_symbols())
                okx_ois = await self.okx.get_all_open_interest(symbols=symbols)
                okx_tickers = await self.okx.get_all_swap_tickers()
                self._mark_provider_success("okx")
            except Exception as exc:
                logger.warning("获取 OKX OI 失败: %s", exc)
                self._mark_provider_error("okx")
                okx_ois = {}
                okx_tickers = {}

            for symbol, item in okx_ois.items():
                if not self._should_include_symbol(symbol):
                    continue
                price = okx_tickers.get(symbol).price if symbol in okx_tickers else 0.0
                history = self._append_oi_snapshot("okx", symbol, item.oi_contracts, price)
                one_hour = self._find_snapshot_delta(history, item.oi_contracts, price, 3600)
                if symbol not in results:
                    results[symbol] = OIData(
                        symbol=symbol,
                        oi_value=item.oi_value_usd,
                        oi_coins=item.oi_contracts,
                        oi_change_1h=one_hour["pct"],
                        oi_change_4h=0.0,
                        oi_change_24h=0.0,
                        oi_delta_value_1h=one_hour["delta_value"],
                    )
        return results

    def _find_snapshot_delta(self, history: List[dict], current_oi: float, current_price: float, window_seconds: int) -> Dict[str, float]:
        now = int(time.time())
        eligible = [item for item in history if item.get("ts", 0) <= now - window_seconds]
        if not eligible:
            return {"pct": 0.0, "delta_value": 0.0}
        ref = eligible[-1]
        ref_oi = float(ref.get("oi") or 0)
        if ref_oi <= 0:
            return {"pct": 0.0, "delta_value": 0.0}
        delta = current_oi - ref_oi
        pct = delta / ref_oi * 100
        delta_value = delta * current_price
        return {"pct": pct, "delta_value": delta_value}

    async def get_oi_with_history(self, symbol: str, period: str = "1h") -> Optional[OIData]:
        symbol = symbol.upper().strip()
        binance_symbols = set(await super().get_usdt_symbols())
        if symbol in binance_symbols:
            data = await super().get_oi_with_history(symbol, period=period)
            if data:
                return data
        return (await self.get_all_oi()).get(symbol)

    async def get_all_funding_rates(self) -> Dict[str, FundingData]:
        rates = await super().get_all_funding_rates()
        if rates:
            self._mark_provider_success("binance")
        if self.universe_mode == "fixed" and self.focus_symbols:
            rates = {k: v for k, v in rates.items() if k in self.focus_symbols}

        if self.okx:
            try:
                symbols = self._apply_universe_filter(await self.okx.get_swap_symbols())
                okx_rates = await self.okx.get_all_funding_rates(symbols=symbols)
                self._mark_provider_success("okx")
            except Exception as exc:
                logger.warning("获取 OKX funding 失败: %s", exc)
                self._mark_provider_error("okx")
                okx_rates = {}

            for symbol, info in okx_rates.items():
                if symbol not in rates and self._should_include_symbol(symbol):
                    rates[symbol] = FundingData(
                        symbol=symbol,
                        funding_rate=info.funding_rate,
                        next_funding_time=info.next_funding_time,
                    )
        return rates

    async def get_exchange_oi_details(self, symbol: str) -> Dict[str, dict]:
        symbol = symbol.upper().strip()
        result: Dict[str, dict] = {}
        binance_oi = await super().get_oi_with_history(symbol, period="1h") if symbol in set(await super().get_usdt_symbols()) else None
        if binance_oi:
            result["binance"] = {
                "oi": binance_oi.oi_coins,
                "oi_value": binance_oi.oi_value,
                "oi_delta_percent": binance_oi.oi_change_1h,
                "oi_delta_value": binance_oi.oi_delta_value_1h,
                "net_long": 0,
                "net_short": 0,
            }
        if self.okx:
            okx_oi = await self.okx.get_open_interest(symbol)
            if okx_oi:
                okx_history = self._snapshot_state.setdefault(self._oi_history_key("okx"), {}).get(symbol, [])
                price = (await self.okx.get_all_swap_tickers()).get(symbol).price if symbol in (await self.okx.get_all_swap_tickers()) else 0.0
                delta = self._find_snapshot_delta(okx_history, okx_oi.oi_contracts, price, 3600)
                result["okx"] = {
                    "oi": okx_oi.oi_contracts,
                    "oi_value": okx_oi.oi_value_usd,
                    "oi_delta_percent": delta["pct"],
                    "oi_delta_value": delta["delta_value"],
                }
        return result

    # ---------- Flow / ranking ----------
    async def _get_spot_session(self) -> aiohttp.ClientSession:
        return await self._get_session()

    async def _spot_request(self, endpoint: str, params: Optional[dict] = None) -> object:
        session = await self._get_spot_session()
        url = f"https://api.binance.com{endpoint}"
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.debug("Binance spot API error %s: %s", resp.status, await resp.text())
                    return {}
                return await resp.json()
        except Exception as exc:
            logger.debug("Binance spot API exception: %s", exc)
            return {}

    async def get_spot_klines(self, symbol: str, interval: str = "1h", limit: int = 4) -> List[Dict]:
        symbol = symbol.upper().strip()
        cache_key = f"spot:{symbol}:{interval}:{limit}"
        if cache_key in self._spot_kline_cache:
            return self._spot_kline_cache[cache_key]
        data = await self._spot_request("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not data:
            return []
        klines: List[Dict] = []
        for k in data:
            klines.append(
                {
                    "open_time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": k[6],
                    "quote_volume": float(k[7]),
                    "trade_count": int(k[8]),
                    "taker_buy_base_volume": float(k[9]),
                    "taker_buy_quote_volume": float(k[10]),
                }
            )
        self._spot_kline_cache[cache_key] = klines
        return klines

    async def get_flow_proxy(self, symbol: str, duration: str = "1h", trade: str = "all") -> Dict[str, float]:
        symbol = symbol.upper().strip()
        cache_key = f"flow:{symbol}:{duration}:{trade}"
        if cache_key in self._netflow_cache:
            return self._netflow_cache[cache_key]

        interval, limit = self.DURATION_TO_INTERVAL.get(duration, ("1h", 1))
        futures_klines = await self.get_symbol_klines(symbol, interval=interval, limit=limit)
        spot_klines = await self.get_spot_klines(symbol, interval=interval, limit=limit)

        def _flow(klines: List[Dict]) -> float:
            total = 0.0
            for item in klines:
                qv = float(item.get("quote_volume") or 0)
                taker = float(item.get("taker_buy_quote_volume") or 0)
                total += (2 * taker - qv)
            return total

        future_flow = _flow(futures_klines)
        spot_flow = _flow(spot_klines)
        amount = future_flow + spot_flow
        if trade == "future":
            amount = future_flow
        elif trade == "spot":
            amount = spot_flow

        result = {
            "amount": amount,
            "future_flow": future_flow,
            "spot_flow": spot_flow,
            "mode": "proxy_taker_imbalance",
        }
        self._netflow_cache[cache_key] = result
        return result

    async def get_netflow_ranking(self, rank_type: str = "top", duration: str = "1h", limit: int = 20, trade: str = "all") -> List[dict]:
        cache_key = f"netflow:{rank_type}:{duration}:{limit}:{trade}"
        if cache_key in self._price_ranking_cache:
            return self._price_ranking_cache[cache_key]

        tickers = await self.get_all_tickers()
        candidates = sorted(tickers.values(), key=lambda x: x.volume_24h, reverse=True)[: self.NETFLOW_CANDIDATES]
        tasks = [self.get_flow_proxy(item.symbol, duration=duration, trade=trade) for item in candidates]
        flows = await asyncio.gather(*tasks, return_exceptions=True)

        rows: List[dict] = []
        for item, flow in zip(candidates, flows):
            if isinstance(flow, Exception):
                continue
            amount = float(flow.get("amount") or 0)
            rows.append(
                {
                    "symbol": item.symbol,
                    "amount": amount,
                    "price": item.price,
                    "future_flow": flow.get("future_flow", 0.0),
                    "spot_flow": flow.get("spot_flow", 0.0),
                    "mode": flow.get("mode"),
                }
            )
        rows.sort(key=lambda x: x["amount"], reverse=(rank_type == "top"))
        result = rows[:limit]
        self._price_ranking_cache[cache_key] = result
        return result

    async def get_price_ranking(self, duration: str = "1h", limit: int = 20) -> List[dict]:
        cache_key = f"price:{duration}:{limit}"
        if cache_key in self._price_ranking_cache:
            return self._price_ranking_cache[cache_key]

        tickers = await self.get_all_tickers()
        candidates = sorted(tickers.values(), key=lambda x: x.volume_24h, reverse=True)[: self.PRICE_RANKING_CANDIDATES]

        async def _build_row(ticker: TickerData) -> Optional[dict]:
            changes = await self.calculate_all_price_changes(ticker.symbol, ticker.price)
            flow = await self.get_flow_proxy(ticker.symbol, duration=duration, trade="all")
            oi = (await self.get_all_oi()).get(ticker.symbol)
            pct = changes.get(duration, 0.0)
            return {
                "symbol": ticker.symbol,
                "price": ticker.price,
                "price_delta": pct / 100,
                "future_flow": flow.get("future_flow", 0.0),
                "spot_flow": flow.get("spot_flow", 0.0),
                "oi": oi.oi_coins if oi else 0.0,
                "oi_delta": (oi.oi_coins * oi.oi_change_1h / 100) if oi else 0.0,
                "oi_delta_value": oi.oi_delta_value_1h if oi else 0.0,
                "mode": flow.get("mode"),
            }

        rows = [r for r in await asyncio.gather(*[_build_row(t) for t in candidates]) if r]
        rows.sort(key=lambda x: x["price_delta"], reverse=True)
        result = rows[:limit]
        self._price_ranking_cache[cache_key] = result
        return result

    async def get_funding_rate_ranking(self, rank_type: str = "top", limit: int = 20) -> List[dict]:
        rates = list((await self.get_all_funding_rates()).values())
        rates.sort(key=lambda x: x.funding_rate, reverse=(rank_type == "top"))
        tickers = await self.get_all_tickers()
        rows = []
        for item in rates[:limit]:
            ticker = tickers.get(item.symbol)
            rows.append(
                {
                    "symbol": item.symbol,
                    "funding_rate": item.funding_rate * 100,
                    "mark_price": ticker.price if ticker else 0.0,
                    "next_funding_time": item.next_funding_time,
                }
            )
        return rows

    async def get_oi_cap_ranking(self, market_cap_lookup: Optional[Dict[str, dict]] = None, limit: int = 20) -> List[dict]:
        market_cap_lookup = market_cap_lookup or {}
        oi_data = await self.get_all_oi()
        rows: List[dict] = []
        for symbol, oi in oi_data.items():
            base = symbol.replace("USDT", "")
            market_info = market_cap_lookup.get(base, {})
            rows.append(
                {
                    "symbol": symbol,
                    "oi": oi.oi_coins,
                    "oi_value": oi.oi_value,
                    "net_long": 0,
                    "net_short": 0,
                    "market_cap": market_info.get("market_cap", 0),
                    "cmc_rank": market_info.get("cmc_rank", 0),
                    "oi_market_cap_ratio": (oi.oi_value / market_info.get("market_cap", 1)) if market_info.get("market_cap") else None,
                }
            )
        rows.sort(key=lambda x: x["oi_value"], reverse=True)
        return rows[:limit]

    # ---------- Heatmap ----------
    async def _get_depth(self, symbol: str, trade: str = "future") -> dict:
        symbol = symbol.upper().strip()
        cache_key = f"depth:{trade}:{symbol}"
        if cache_key in self._heatmap_cache:
            return self._heatmap_cache[cache_key]

        if trade == "spot":
            data = await self._spot_request("/api/v3/depth", {"symbol": symbol, "limit": 100})
        else:
            data = await self._request("/fapi/v1/depth", {"symbol": symbol, "limit": 100})
        if isinstance(data, dict) and data:
            self._heatmap_cache[cache_key] = data
            return data
        if self.okx:
            okx_book = await self.okx.get_orderbook(symbol, trade="spot" if trade == "spot" else "swap", depth=100)
            if okx_book:
                data = {"bids": okx_book.get("bids", []), "asks": okx_book.get("asks", [])}
                self._heatmap_cache[cache_key] = data
                return data
        return {}

    def _build_heatmap_from_depth(self, symbol: str, depth: dict) -> Optional[dict]:
        if not depth:
            return None

        bids = depth.get("bids", [])
        asks = depth.get("asks", [])
        if not bids and not asks:
            return None

        def _parse(rows: List[List[str]]) -> Tuple[float, List[dict]]:
            total = 0.0
            parsed = []
            for px, qty, *_ in rows:
                price = float(px)
                quantity = float(qty)
                volume = price * quantity
                total += volume
                parsed.append({"price": price, "quantity": quantity, "volume": volume})
            parsed.sort(key=lambda x: x["volume"], reverse=True)
            return total, parsed[:5]

        bid_volume, large_bids = _parse(bids)
        ask_volume, large_asks = _parse(asks)
        delta = bid_volume - ask_volume
        history_key = f"heatmap:{symbol}"
        history = self._snapshot_state.setdefault(history_key, [])
        history.append({"ts": int(time.time()), "delta": delta})
        cutoff = int(time.time()) - 3600
        history[:] = [x for x in history if x.get("ts", 0) >= cutoff]

        return {
            "symbol": symbol,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "delta": delta,
            "delta_history": [x["delta"] for x in history[-10:]],
            "large_bids": large_bids,
            "large_asks": large_asks,
            "source": "binance" if symbol.endswith("USDT") else "unknown",
        }

    async def get_heatmap(self, symbol: str, trade: str = "future") -> Optional[dict]:
        symbol = symbol.upper().strip()
        depth = await self._get_depth(symbol, trade=trade)
        if depth:
            return self._build_heatmap_from_depth(symbol, depth)
        return None

    async def get_heatmap_list(self, trade: str = "future", limit: int = 20) -> List[dict]:
        tickers = await self.get_all_tickers()
        candidates = sorted(tickers.values(), key=lambda x: x.volume_24h, reverse=True)[: self.HEATMAP_LIST_CANDIDATES]
        heatmaps = await asyncio.gather(*[self.get_heatmap(t.symbol, trade=trade) for t in candidates], return_exceptions=True)
        rows = [x for x in heatmaps if isinstance(x, dict)]
        rows.sort(key=lambda x: abs(x.get("delta", 0.0)), reverse=True)
        return rows[:limit]

    # ---------- Monitoring ----------
    async def get_system_status(self) -> Dict[str, Any]:
        tickers = await self.get_all_tickers()
        ois = await self.get_all_oi()
        rates = await self.get_all_funding_rates()
        coverage = {
            "symbols_total": len(await self.get_usdt_symbols()),
            "tickers": len(tickers),
            "oi": len(ois),
            "funding": len(rates),
            "binance_symbols": len(await super().get_usdt_symbols()),
            "okx_symbols": len(await self.okx.get_swap_symbols()) if self.okx else 0,
            "universe_mode": self.universe_mode,
            "focus_symbols": sorted(self.focus_symbols),
        }
        return {
            "providers": self.get_provider_status(),
            "coverage": coverage,
            "snapshot_file": self.snapshot_file,
            "timestamp": int(time.time()),
        }
