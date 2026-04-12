#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from collectors.binance_collector import OIData, TickerData
from collectors.market_data_collector import UnifiedMarketCollector


class TestUnifiedMarketCollector:
    @pytest.fixture
    def collector(self):
        c = UnifiedMarketCollector(snapshot_file="")
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
    async def test_get_exchange_oi_details_binance(self, collector, monkeypatch):
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_usdt_symbols', AsyncMock(return_value=["ETHUSDT"]))
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_oi_with_history', AsyncMock(return_value=OIData(
            symbol="ETHUSDT",
            oi_value=12_000_000.0,
            oi_coins=4000.0,
            oi_change_1h=5.0,
            oi_delta_value_1h=600_000.0,
        )))

        result = await collector.get_exchange_oi_details("ETHUSDT")
        assert "binance" in result
        assert result["binance"]["oi"] == 4000.0

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
    async def test_get_usdt_symbols_logs_okx_connection_once(self, collector, monkeypatch):
        monkeypatch.setattr('collectors.binance_collector.BinanceCollector.get_usdt_symbols', AsyncMock(return_value=["BTCUSDT"]))
        collector.okx = MagicMock()
        collector.okx.get_swap_symbols = AsyncMock(return_value=["ZECUSDT"])

        with patch("collectors.market_data_collector.logger.info") as mock_info:
            first = await collector.get_usdt_symbols()
            second = await collector.get_usdt_symbols()

        assert set(first) == {"BTCUSDT", "ZECUSDT"}
        assert set(second) == {"BTCUSDT", "ZECUSDT"}

        okx_calls = [call for call in mock_info.call_args_list if call.args[1] == "Okx" and call.args[3] == "symbols"]
        assert len(okx_calls) == 1
