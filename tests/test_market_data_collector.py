#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from collectors.binance_collector import OIData, TickerData
from collectors.hyperliquid_collector import HyperliquidAssetContext
from collectors.market_data_collector import UnifiedMarketCollector


class TestUnifiedMarketCollector:
    @pytest.fixture
    def collector(self):
        c = UnifiedMarketCollector(hyperliquid_enabled=False, snapshot_file="")
        yield c
        import asyncio
        asyncio.run(c.close())

    def test_find_snapshot_delta(self, collector):
        history = [
            {"ts": 1000, "oi": 100.0, "price": 10.0},
            {"ts": 5000, "oi": 120.0, "price": 12.0},
        ]
        # monkeypatch-like override current time window by shifting timestamps relative to now
        now = 10_000
        history = [
            {"ts": now - 7200, "oi": 100.0, "price": 10.0},
            {"ts": now - 1800, "oi": 120.0, "price": 12.0},
        ]
        import collectors.market_data_collector as mod
        old_time = mod.time.time
        mod.time.time = lambda: now
        try:
            delta = collector._find_snapshot_delta(history, current_oi=150.0, current_price=15.0, window_seconds=3600)
            assert round(delta["pct"], 2) == 50.00
            assert round(delta["delta_value"], 2) == 750.00
        finally:
            mod.time.time = old_time

    @pytest.mark.asyncio
    async def test_get_all_tickers_merges_hyperliquid(self, collector, monkeypatch):
        binance_tickers = {
            "BTCUSDT": TickerData(symbol="BTCUSDT", price=100000.0, volume_24h=1_000_000_000)
        }
        hyper_contexts = {
            "HYPEUSDT": HyperliquidAssetContext(
                symbol="HYPEUSDT",
                coin="HYPE",
                price=20.0,
                funding_rate=0.0001,
                open_interest=10_000.0,
                oi_value_usd=200_000.0,
                prev_day_price=18.0,
                day_notional_volume=50_000_000.0,
            )
        }
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_all_tickers', AsyncMock(return_value=binance_tickers))
        collector.hyperliquid_enabled = True
        collector.hyperliquid = MagicMock()
        collector.hyperliquid.get_all_asset_contexts = AsyncMock(return_value=hyper_contexts)

        result = await collector.get_all_tickers()
        assert "BTCUSDT" in result
        assert "HYPEUSDT" in result
        assert result["HYPEUSDT"].price == 20.0
        assert result["HYPEUSDT"].price_change_24h > 0

    @pytest.mark.asyncio
    async def test_get_exchange_oi_details(self, collector, monkeypatch):
        collector.hyperliquid_enabled = True
        collector.hyperliquid = MagicMock()
        collector.hyperliquid.get_coin_context = AsyncMock(return_value=HyperliquidAssetContext(
            symbol="ETHUSDT",
            coin="ETH",
            price=3000.0,
            funding_rate=0.0002,
            open_interest=5000.0,
            oi_value_usd=15_000_000.0,
            prev_day_price=2900.0,
        ))
        collector._snapshot_state = {
            "hyperliquid_oi": {
                "ETHUSDT": [
                    {"ts": 1, "oi": 4500.0, "price": 2800.0},
                    {"ts": 9999999999, "oi": 5000.0, "price": 3000.0},
                ]
            }
        }
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_usdt_symbols', AsyncMock(return_value=["ETHUSDT"]))
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_oi_with_history', AsyncMock(return_value=OIData(
            symbol="ETHUSDT",
            oi_value=12_000_000.0,
            oi_coins=4000.0,
            oi_change_1h=5.0,
            oi_delta_value_1h=600_000.0,
        )))

        # force snapshot lookup to use binance baseline only for hyper delta calc
        import collectors.market_data_collector as mod
        old_time = mod.time.time
        mod.time.time = lambda: 7200
        try:
            result = await collector.get_exchange_oi_details("ETHUSDT")
        finally:
            mod.time.time = old_time

        assert "binance" in result
        assert "hyperliquid" in result
        assert result["binance"]["oi"] == 4000.0
        assert result["hyperliquid"]["oi_value"] == 15_000_000.0

    @pytest.mark.asyncio
    async def test_get_flow_proxy_formula(self, collector, monkeypatch):
        collector.get_symbol_klines = AsyncMock(return_value=[{
            "quote_volume": 1000.0,
            "taker_buy_quote_volume": 700.0,
        }])
        collector.get_spot_klines = AsyncMock(return_value=[{
            "quote_volume": 500.0,
            "taker_buy_quote_volume": 200.0,
        }])

        result = await collector.get_flow_proxy("BTCUSDT", duration="1h", trade="all")
        # futures: 2*700-1000 = 400 ; spot: 2*200-500 = -100 ; total = 300
        assert result["future_flow"] == 400.0
        assert result["spot_flow"] == -100.0
        assert result["amount"] == 300.0
        assert result["mode"] == "proxy_taker_imbalance"


    @pytest.mark.asyncio
    async def test_get_all_tickers_merges_okx(self, collector, monkeypatch):
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_all_tickers', AsyncMock(return_value={}))
        collector.okx = MagicMock()
        collector.okx.get_all_swap_tickers = AsyncMock(return_value={
            "ZECUSDT": MagicMock(price=30.0, price_change_24h=4.0, volume_24h=1000000.0, high_24h=31.0, low_24h=28.0)
        })
        result = await collector.get_all_tickers()
        assert "ZECUSDT" in result
        assert result["ZECUSDT"].price == 30.0

    @pytest.mark.asyncio
    async def test_get_usdt_symbols_logs_hyperliquid_and_okx_connection_once(self, collector, monkeypatch):
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_usdt_symbols', AsyncMock(return_value=["BTCUSDT"]))
        collector.hyperliquid = MagicMock()
        collector.hyperliquid.get_universe_symbols = AsyncMock(return_value=["HYPEUSDT"])
        collector.okx = MagicMock()
        collector.okx.get_swap_symbols = AsyncMock(return_value=["ZECUSDT"])

        with patch("collectors.market_data_collector.logger.info") as mock_info:
            first = await collector.get_usdt_symbols()
            second = await collector.get_usdt_symbols()

        assert set(first) == {"BTCUSDT", "HYPEUSDT", "ZECUSDT"}
        assert set(second) == {"BTCUSDT", "HYPEUSDT", "ZECUSDT"}

        hyper_calls = [call for call in mock_info.call_args_list if call.args[1] == "Hyperliquid" and call.args[3] == "symbols"]
        okx_calls = [call for call in mock_info.call_args_list if call.args[1] == "Okx" and call.args[3] == "symbols"]
        assert len(hyper_calls) == 1
        assert len(okx_calls) == 1
