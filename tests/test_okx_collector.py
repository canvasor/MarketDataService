#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock

import pytest

from collectors.okx_collector import OKXCollector, OKXSwapTicker


def test_symbol_conversion():
    assert OKXCollector.normalize_symbol("btc-usdt") == "BTCUSDT"
    assert OKXCollector.to_swap_inst_id("BTCUSDT") == "BTC-USDT-SWAP"
    assert OKXCollector.to_spot_inst_id("ETH") == "ETH-USDT"


@pytest.mark.asyncio
async def test_get_all_swap_tickers_parsing(monkeypatch):
    c = OKXCollector(enabled=True)
    monkeypatch.setattr(c, "get_swap_instruments", AsyncMock(return_value={"BTCUSDT": {}}))
    monkeypatch.setattr(c, "_request", AsyncMock(return_value={
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "last": "60000",
                "open24h": "58000",
                "high24h": "61000",
                "low24h": "57000",
                "volCcy24h": "123456789",
            }
        ],
    }))
    data = await c.get_all_swap_tickers()
    assert "BTCUSDT" in data
    assert data["BTCUSDT"].price == 60000.0
    assert data["BTCUSDT"].price_change_24h > 0
    await c.close()


@pytest.mark.asyncio
async def test_get_all_open_interest_uses_bulk_endpoint_and_filters_symbols(monkeypatch):
    c = OKXCollector(enabled=True)
    request = AsyncMock(return_value={
        "code": "0",
        "data": [
            {
                "instType": "SWAP",
                "instId": "BTC-USDT-SWAP",
                "oi": "100",
                "oiCcy": "2",
                "oiUsd": "123456",
            },
            {
                "instType": "SWAP",
                "instId": "ETH-USDT-SWAP",
                "oi": "200",
                "oiCcy": "10",
                "oiUsd": "234567",
            },
            {
                "instType": "SWAP",
                "instId": "DOGE-USDT-SWAP",
                "oi": "300",
                "oiCcy": "1000",
                "oiUsd": "345678",
            },
        ],
    })
    monkeypatch.setattr(c, "_request", request)
    monkeypatch.setattr(c, "get_all_swap_tickers", AsyncMock(return_value={
        "BTCUSDT": OKXSwapTicker(symbol="BTCUSDT", inst_id="BTC-USDT-SWAP", price=60000),
        "ETHUSDT": OKXSwapTicker(symbol="ETHUSDT", inst_id="ETH-USDT-SWAP", price=3000),
        "DOGEUSDT": OKXSwapTicker(symbol="DOGEUSDT", inst_id="DOGE-USDT-SWAP", price=0.1),
    }))

    data = await c.get_all_open_interest(symbols=["BTCUSDT", "ETHUSDT"])

    request.assert_awaited_once_with("/api/v5/public/open-interest", {"instType": "SWAP"})
    assert set(data) == {"BTCUSDT", "ETHUSDT"}
    assert data["BTCUSDT"].oi_contracts == 100.0
    assert data["BTCUSDT"].oi_value_usd == 123456.0
    await c.close()
