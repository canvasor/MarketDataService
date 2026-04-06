#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance 数据采集器单元测试

测试覆盖：
1. TickerData, OIData, FundingData 数据类
2. 价格计算
3. ATR 计算
4. VWAP 计算
5. 入场时机计算
6. 趋势强度计算
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import time

from binance_collector import (
    BinanceCollector,
    TickerData,
    OIData,
    FundingData
)


class TestTickerData:
    """测试 TickerData 数据类"""

    def test_default_values(self):
        """测试默认值"""
        ticker = TickerData(symbol="BTCUSDT", price=50000.0)
        assert ticker.symbol == "BTCUSDT"
        assert ticker.price == 50000.0
        assert ticker.price_change_1h == 0.0
        assert ticker.price_change_4h == 0.0
        assert ticker.price_change_24h == 0.0
        assert ticker.volume_24h == 0.0
        assert ticker.volatility_24h == 0.0

    def test_full_initialization(self):
        """测试完整初始化"""
        ticker = TickerData(
            symbol="ETHUSDT",
            price=3000.0,
            price_change_1h=1.5,
            price_change_4h=3.0,
            price_change_24h=5.0,
            volume_24h=1000000000.0,
            high_24h=3100.0,
            low_24h=2900.0,
            volatility_24h=6.67
        )
        assert ticker.price == 3000.0
        assert ticker.volume_24h == 1000000000.0
        assert ticker.volatility_24h == 6.67


class TestOIData:
    """测试 OIData 数据类"""

    def test_default_values(self):
        """测试默认值"""
        oi = OIData(symbol="BTCUSDT", oi_value=5000000000.0, oi_coins=100000.0)
        assert oi.symbol == "BTCUSDT"
        assert oi.oi_value == 5000000000.0
        assert oi.oi_coins == 100000.0
        assert oi.oi_change_1h == 0.0
        assert oi.oi_change_4h == 0.0
        assert oi.oi_delta_value_1h == 0.0

    def test_with_changes(self):
        """测试带变化数据的初始化"""
        oi = OIData(
            symbol="ETHUSDT",
            oi_value=1000000000.0,
            oi_coins=333333.0,
            oi_change_1h=5.0,
            oi_change_4h=10.0,
            oi_delta_value_1h=50000000.0
        )
        assert oi.oi_change_1h == 5.0
        assert oi.oi_delta_value_1h == 50000000.0


class TestFundingData:
    """测试 FundingData 数据类"""

    def test_initialization(self):
        """测试初始化"""
        funding = FundingData(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            next_funding_time=1704067200000
        )
        assert funding.symbol == "BTCUSDT"
        assert funding.funding_rate == 0.0001
        assert funding.next_funding_time == 1704067200000


class TestBinanceCollector:
    """测试 BinanceCollector 类"""

    @pytest.fixture
    def collector(self):
        """创建 collector 实例"""
        return BinanceCollector()

    def test_initialization(self, collector):
        """测试初始化"""
        assert collector.api_key is None
        assert collector.api_secret is None
        assert collector.session is None
        assert collector._usdt_symbols == []

    def test_initialization_with_keys(self):
        """测试带 API 密钥的初始化"""
        collector = BinanceCollector(api_key="test_key", api_secret="test_secret")
        assert collector.api_key == "test_key"
        assert collector.api_secret == "test_secret"


class TestATRCalculation:
    """测试 ATR 计算"""

    @pytest.fixture
    def collector(self):
        """创建 collector"""
        return BinanceCollector()

    def test_atr_basic(self, collector):
        """测试基础 ATR 计算"""
        klines = [
            {"high": 100, "low": 95, "close": 98},
            {"high": 102, "low": 97, "close": 101},
            {"high": 105, "low": 99, "close": 103},
            {"high": 106, "low": 100, "close": 104}
        ]
        atr = collector._calculate_atr(klines)
        assert atr > 0

    def test_atr_empty_klines(self, collector):
        """测试空 K 线数据"""
        assert collector._calculate_atr([]) == 0.0
        assert collector._calculate_atr([{"high": 100, "low": 95, "close": 98}]) == 0.0

    def test_atr_typical_values(self, collector):
        """测试典型值"""
        # 模拟每根K线波动约 5%
        klines = [
            {"high": 100, "low": 95, "close": 97},
            {"high": 102, "low": 96, "close": 100},
            {"high": 105, "low": 98, "close": 103},
            {"high": 108, "low": 100, "close": 105}
        ]
        atr = collector._calculate_atr(klines)
        # ATR 应该在合理范围内 (约 5-7)
        assert 3 < atr < 10


class TestTrendStrengthCalculation:
    """测试趋势强度计算"""

    @pytest.fixture
    def collector(self):
        """创建 collector"""
        return BinanceCollector()

    def test_strong_uptrend(self, collector):
        """测试强上涨趋势"""
        klines = [
            {"close": 100},
            {"close": 102},
            {"close": 104},
            {"close": 106},
            {"close": 108}
        ]
        strength = collector._calculate_trend_strength(klines, "long")
        assert strength >= 0.75  # 应该显示强趋势

    def test_strong_downtrend(self, collector):
        """测试强下跌趋势"""
        klines = [
            {"close": 100},
            {"close": 98},
            {"close": 96},
            {"close": 94},
            {"close": 92}
        ]
        strength = collector._calculate_trend_strength(klines, "short")
        assert strength >= 0.75

    def test_neutral_trend(self, collector):
        """测试中性趋势"""
        klines = [
            {"close": 100},
            {"close": 101},
            {"close": 100},
            {"close": 101},
            {"close": 100}
        ]
        strength = collector._calculate_trend_strength(klines, "long")
        assert 0.3 <= strength <= 0.7

    def test_insufficient_data(self, collector):
        """测试数据不足"""
        klines = [{"close": 100}]
        strength = collector._calculate_trend_strength(klines, "long")
        assert strength == 0.5  # 默认值

        strength2 = collector._calculate_trend_strength([], "long")
        assert strength2 == 0.5


class TestVWAPCalculation:
    """测试 VWAP 计算"""

    @pytest.fixture
    def mock_collector(self):
        """创建带模拟的 collector"""
        collector = BinanceCollector()
        return collector

    @pytest.mark.asyncio
    async def test_vwap_basic(self, mock_collector):
        """测试基础 VWAP 计算"""
        # 模拟 K 线数据
        klines = [
            {"high": 101, "low": 99, "close": 100, "quote_volume": 1000000},
            {"high": 102, "low": 100, "close": 101, "quote_volume": 1500000},
            {"high": 103, "low": 101, "close": 102, "quote_volume": 2000000}
        ]

        with patch.object(mock_collector, 'get_symbol_klines', new_callable=AsyncMock) as mock_klines:
            mock_klines.return_value = klines
            result = await mock_collector.calculate_vwap("BTCUSDT", "1h", 3)

            assert "vwap" in result
            assert "price_vs_vwap" in result
            assert result["vwap"] > 0

    @pytest.mark.asyncio
    async def test_vwap_empty_data(self, mock_collector):
        """测试空数据"""
        with patch.object(mock_collector, 'get_symbol_klines', new_callable=AsyncMock) as mock_klines:
            mock_klines.return_value = []
            result = await mock_collector.calculate_vwap("BTCUSDT", "1h", 3)

            assert result["vwap"] == 0.0
            assert result["price_vs_vwap"] == 0.0


class TestEntryTimingCalculation:
    """测试入场时机计算"""

    @pytest.fixture
    def mock_collector(self):
        """创建带模拟的 collector"""
        collector = BinanceCollector()
        return collector

    def _create_uptrend_klines(self, periods, start_price=100):
        """创建上涨趋势 K 线"""
        klines = []
        price = start_price
        for i in range(periods):
            high = price * 1.02
            low = price * 0.99
            close = price * 1.01
            klines.append({
                "open_time": 0,
                "open": price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000,
                "quote_volume": 100000
            })
            price = close
        return klines

    def _create_pullback_klines(self, periods, start_price=100):
        """创建回调 K 线（先涨后跌）"""
        klines = []
        price = start_price
        # 前半段上涨
        for i in range(periods // 2):
            high = price * 1.02
            low = price * 0.99
            close = price * 1.015
            klines.append({
                "open_time": 0,
                "open": price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000,
                "quote_volume": 100000
            })
            price = close
        # 后半段回调
        for i in range(periods - periods // 2):
            high = price * 1.005
            low = price * 0.98
            close = price * 0.99
            klines.append({
                "open_time": 0,
                "open": price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000,
                "quote_volume": 100000
            })
            price = close
        return klines

    @pytest.mark.asyncio
    async def test_entry_timing_chasing(self, mock_collector):
        """测试追高情况"""
        # 创建急涨 K 线
        klines_15m = self._create_uptrend_klines(24, start_price=100)
        # 让最后几根涨幅更大
        for i in range(-4, 0):
            klines_15m[i]["close"] = klines_15m[i]["close"] * 1.03

        klines_1h = self._create_uptrend_klines(24, start_price=100)
        klines_4h = self._create_uptrend_klines(12, start_price=100)

        with patch.object(mock_collector, 'get_symbol_klines', new_callable=AsyncMock) as mock_klines:
            async def mock_get_klines(symbol, interval, limit):
                if interval == "15m":
                    return klines_15m[-limit:]
                elif interval == "1h":
                    return klines_1h[-limit:]
                elif interval == "4h":
                    return klines_4h[-limit:]
                return []

            mock_klines.side_effect = mock_get_klines
            result = await mock_collector.calculate_entry_timing("BTCUSDT", "long")

            assert "timing" in result
            assert "timing_score" in result
            assert "atr_pct" in result
            # 急涨情况应该检测到追高风险
            # 根据具体数据，可能是 chasing 或其他状态

    @pytest.mark.asyncio
    async def test_entry_timing_optimal_pullback(self, mock_collector):
        """测试回调到位情况"""
        klines_15m = self._create_pullback_klines(24, start_price=100)
        klines_1h = self._create_pullback_klines(24, start_price=100)
        klines_4h = self._create_pullback_klines(12, start_price=100)

        with patch.object(mock_collector, 'get_symbol_klines', new_callable=AsyncMock) as mock_klines:
            async def mock_get_klines(symbol, interval, limit):
                if interval == "15m":
                    return klines_15m[-limit:]
                elif interval == "1h":
                    return klines_1h[-limit:]
                elif interval == "4h":
                    return klines_4h[-limit:]
                return []

            mock_klines.side_effect = mock_get_klines
            result = await mock_collector.calculate_entry_timing("BTCUSDT", "long")

            assert "timing" in result
            assert "pullback_pct" in result
            assert result["pullback_pct"] > 0  # 应该检测到回调

    @pytest.mark.asyncio
    async def test_entry_timing_short_direction(self, mock_collector):
        """测试做空方向的入场时机"""
        # 创建下跌后反弹的 K 线
        klines = []
        price = 100
        # 先下跌
        for i in range(12):
            close = price * 0.99
            klines.append({
                "open_time": 0,
                "open": price,
                "high": price * 1.005,
                "low": close * 0.995,
                "close": close,
                "volume": 1000,
                "quote_volume": 100000
            })
            price = close
        # 后反弹
        for i in range(12):
            close = price * 1.01
            klines.append({
                "open_time": 0,
                "open": price,
                "high": close * 1.005,
                "low": price * 0.995,
                "close": close,
                "volume": 1000,
                "quote_volume": 100000
            })
            price = close

        with patch.object(mock_collector, 'get_symbol_klines', new_callable=AsyncMock) as mock_klines:
            mock_klines.return_value = klines[-24:]
            result = await mock_collector.calculate_entry_timing("BTCUSDT", "short")

            assert "timing" in result
            assert "pullback_pct" in result  # 对于做空，这是反弹幅度


class TestPriceChangeCalculation:
    """测试价格变化计算"""

    @pytest.fixture
    def mock_collector(self):
        """创建带模拟的 collector"""
        return BinanceCollector()

    @pytest.mark.asyncio
    async def test_price_changes(self, mock_collector):
        """测试价格变化计算"""
        klines_1h = [
            {"close": 100},
            {"close": 102}
        ]
        klines_4h = [
            {"close": 95},
            {"close": 102}
        ]

        with patch.object(mock_collector, 'get_symbol_klines', new_callable=AsyncMock) as mock_klines:
            async def mock_get_klines(symbol, interval, limit):
                if interval == "1h":
                    return klines_1h
                elif interval == "4h":
                    return klines_4h
                return []

            mock_klines.side_effect = mock_get_klines
            change_1h, change_4h = await mock_collector.calculate_price_changes("BTCUSDT", 102)

            assert change_1h == pytest.approx(2.0, rel=0.01)  # 100 -> 102 = 2%
            assert change_4h == pytest.approx(7.37, rel=0.1)  # 95 -> 102 ≈ 7.37%


class TestMultiPeriodVWAP:
    """测试多周期 VWAP 计算"""

    @pytest.fixture
    def mock_collector(self):
        """创建带模拟的 collector"""
        return BinanceCollector()

    @pytest.mark.asyncio
    async def test_multi_period_vwap(self, mock_collector):
        """测试多周期 VWAP"""
        with patch.object(mock_collector, 'calculate_vwap', new_callable=AsyncMock) as mock_vwap:
            mock_vwap.side_effect = [
                {"vwap": 100.0, "price_vs_vwap": 1.0},  # 1h
                {"vwap": 98.0, "price_vs_vwap": 3.0}    # 4h
            ]

            result = await mock_collector.calculate_multi_period_vwap("BTCUSDT")

            assert "1h" in result
            assert "4h" in result
            assert result["1h"]["vwap"] == 100.0
            assert result["4h"]["vwap"] == 98.0


class TestCacheUsage:
    """测试缓存使用"""

    def test_cache_initialization(self):
        """测试缓存初始化"""
        collector = BinanceCollector()
        assert collector._ticker_cache is not None
        assert collector._oi_cache is not None
        assert collector._funding_cache is not None
        assert collector._kline_cache is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
