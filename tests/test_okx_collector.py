#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock

import pytest

from collectors.okx_collector import OKXCollector


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
