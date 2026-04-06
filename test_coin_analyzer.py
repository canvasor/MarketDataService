#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币种分析器单元测试

测试覆盖：
1. CoinAnalysis 数据类
2. 方向判断逻辑
3. 评分计算
4. 入场时机计算
5. CMC 数据增强
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from coin_analyzer import CoinAnalyzer, CoinAnalysis, Direction
from binance_collector import BinanceCollector, TickerData, OIData, FundingData


class TestCoinAnalysis:
    """测试 CoinAnalysis 数据类"""

    def test_default_values(self):
        """测试默认值"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=80.0,
            confidence=75.0
        )
        assert analysis.symbol == "BTCUSDT"
        assert analysis.direction == Direction.LONG
        assert analysis.score == 80.0
        assert analysis.confidence == 75.0
        assert analysis.price == 0.0
        assert analysis.entry_timing == "neutral"
        assert analysis.timing_score == 50.0
        assert analysis.tags == []
        assert analysis.reasons == []

    def test_full_initialization(self):
        """测试完整初始化"""
        analysis = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.SHORT,
            score=65.0,
            confidence=60.0,
            price=3500.0,
            price_change_1h=-2.5,
            price_change_24h=-5.0,
            volatility_24h=8.0,
            oi_value=50000000.0,
            oi_change_1h=5.0,
            funding_rate=0.0005,
            entry_timing="chasing",
            timing_score=30.0,
            atr_pct=4.5,
            tags=["high_volatility"],
            reasons=["价格下跌"]
        )
        assert analysis.price == 3500.0
        assert analysis.price_change_1h == -2.5
        assert analysis.volatility_24h == 8.0
        assert analysis.entry_timing == "chasing"
        assert analysis.atr_pct == 4.5
        assert "high_volatility" in analysis.tags


class TestDirection:
    """测试交易方向枚举"""

    def test_direction_values(self):
        """测试方向枚举值"""
        assert Direction.LONG.value == "long"
        assert Direction.SHORT.value == "short"
        assert Direction.NEUTRAL.value == "neutral"

    def test_direction_string(self):
        """测试方向字符串转换"""
        assert str(Direction.LONG) == "Direction.LONG"


class TestCoinAnalyzer:
    """测试 CoinAnalyzer 类"""

    @pytest.fixture
    def mock_collector(self):
        """创建模拟的 BinanceCollector"""
        collector = MagicMock(spec=BinanceCollector)
        collector.get_all_tickers = AsyncMock(return_value={})
        collector.get_all_oi = AsyncMock(return_value={})
        collector.get_all_funding_rates = AsyncMock(return_value={})
        collector.calculate_price_changes = AsyncMock(return_value=(0.0, 0.0))
        collector.calculate_multi_period_vwap = AsyncMock(return_value={
            "1h": {"vwap": 0.0, "price_vs_vwap": 0.0},
            "4h": {"vwap": 0.0, "price_vs_vwap": 0.0}
        })
        collector.calculate_entry_timing = AsyncMock(return_value={
            "timing": "neutral",
            "timing_score": 50,
            "pullback_pct": 0.0,
            "required_pullback": 2.0,
            "atr_pct": 3.0,
            "support_distance": 2.0,
            "resistance_distance": 3.0,
            "swing_high": 100.0,
            "swing_low": 95.0,
            "reasons": []
        })
        return collector

    @pytest.fixture
    def analyzer(self, mock_collector):
        """创建 CoinAnalyzer 实例"""
        return CoinAnalyzer(mock_collector)

    def test_normalize_symbol(self, analyzer):
        """测试币种符号标准化"""
        assert analyzer._normalize_symbol("BTC") == "BTCUSDT"
        assert analyzer._normalize_symbol("btc") == "BTCUSDT"
        assert analyzer._normalize_symbol("BTCUSDT") == "BTCUSDT"
        assert analyzer._normalize_symbol("  eth  ") == "ETHUSDT"

    def test_set_cmc_data(self, analyzer):
        """测试设置 CMC 数据"""
        trending = [{"symbol": "BTC", "trending_score": 95}]
        gainers = [{"symbol": "ETH", "percent_change_24h": 10.5}]
        losers = [{"symbol": "SOL", "percent_change_24h": -8.0}]

        analyzer.set_cmc_data(trending, gainers, losers)

        assert "BTCUSDT" in analyzer._cmc_trending
        assert "ETHUSDT" in analyzer._cmc_gainers
        assert "SOLUSDT" in analyzer._cmc_losers

    def test_config_values(self, analyzer):
        """测试配置阈值"""
        assert analyzer.config["short_price_drop_1h"] == -1.5
        assert analyzer.config["long_price_rise_1h"] == 1.5
        assert analyzer.config["min_volume_24h"] == 3_000_000
        assert analyzer.config["cmc_trending_bonus"] == 10


class TestDirectionCalculation:
    """测试方向计算逻辑"""

    @pytest.fixture
    def analyzer(self):
        """创建带模拟 collector 的 analyzer"""
        collector = MagicMock(spec=BinanceCollector)
        return CoinAnalyzer(collector)

    def test_long_direction_price_rise(self, analyzer):
        """测试做多方向判断 - 价格上涨"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            price_change_1h=2.5,  # 超过阈值 1.5
            oi_change_1h=3.0  # 超过阈值 2.0
        )
        analyzer._calculate_direction(analysis)
        assert analysis.direction == Direction.LONG

    def test_short_direction_price_drop(self, analyzer):
        """测试做空方向判断 - 价格下跌"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            price_change_1h=-2.0,  # 超过阈值 -1.5
            oi_change_1h=3.0  # OI 增加
        )
        analyzer._calculate_direction(analysis)
        assert analysis.direction == Direction.SHORT

    def test_short_direction_high_funding(self, analyzer):
        """测试做空方向判断 - 高资金费率"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            price_change_1h=-1.6,
            funding_rate=0.0005  # 高于阈值 0.0003
        )
        analyzer._calculate_direction(analysis)
        assert analysis.direction == Direction.SHORT

    def test_long_direction_negative_funding(self, analyzer):
        """测试做多方向判断 - 负资金费率"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            price_change_1h=1.6,
            funding_rate=-0.0003  # 低于阈值 -0.0002
        )
        analyzer._calculate_direction(analysis)
        assert analysis.direction == Direction.LONG

    def test_neutral_direction_no_signals(self, analyzer):
        """测试中性方向 - 无明显信号"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            price_change_1h=0.5,  # 低于阈值
            oi_change_1h=0.5,
            funding_rate=0.0001
        )
        analyzer._calculate_direction(analysis)
        assert analysis.direction == Direction.NEUTRAL


class TestScoreCalculation:
    """测试评分计算逻辑"""

    @pytest.fixture
    def analyzer(self):
        """创建 analyzer"""
        collector = MagicMock(spec=BinanceCollector)
        return CoinAnalyzer(collector)

    def test_base_score(self, analyzer):
        """测试基础分数"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=0.0,
            confidence=0.0
        )
        analyzer._calculate_score(analysis)
        assert analysis.score == 50.0  # 基础分

    def test_long_score_boost(self, analyzer):
        """测试做多评分加成"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=0.0,
            confidence=0.0,
            price_change_1h=3.0,
            oi_change_1h=5.0,
            entry_timing="optimal"
        )
        analyzer._calculate_score(analysis)
        assert analysis.score > 50.0  # 应该高于基础分
        assert analysis.confidence > 50.0

    def test_short_score_boost(self, analyzer):
        """测试做空评分加成"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            score=0.0,
            confidence=0.0,
            price_change_1h=-3.0,
            oi_change_1h=5.0,
            funding_rate=0.0006
        )
        analyzer._calculate_score(analysis)
        assert analysis.score > 50.0

    def test_chasing_penalty(self, analyzer):
        """测试追高惩罚"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=0.0,
            confidence=0.0,
            price_change_1h=2.0,
            entry_timing="chasing"
        )
        analyzer._calculate_score(analysis)
        # 追高会扣分
        assert "追高风险" in str(analysis.reasons) or analysis.score < 80

    def test_optimal_timing_bonus(self, analyzer):
        """测试最佳入场时机加分"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=0.0,
            confidence=0.0,
            price_change_1h=2.0,
            entry_timing="optimal",
            pullback_pct=3.0
        )
        analyzer._calculate_score(analysis)
        assert "最佳入场时机" in str(analysis.reasons)

    def test_cmc_trending_bonus(self, analyzer):
        """测试 CMC 热门加分"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=0.0,
            confidence=0.0,
            cmc_trending=True
        )
        analyzer._calculate_score(analysis)
        # CMC 热门会加分
        assert analysis.score >= 50.0 + analyzer.config["cmc_trending_bonus"]

    def test_score_limits(self, analyzer):
        """测试评分边界限制"""
        # 极高分数情况
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=0.0,
            confidence=0.0,
            price_change_1h=20.0,
            oi_change_1h=30.0,
            funding_rate=-0.01,
            cmc_trending=True,
            entry_timing="optimal"
        )
        analysis.cmc_rank = 10
        analysis.tags = ["cmc_gainer"]
        analyzer._calculate_score(analysis)
        assert analysis.score <= 100.0
        assert analysis.confidence <= 100.0

        # 极低分数情况
        analysis2 = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=0.0,
            confidence=0.0,
            price_change_1h=15.0,
            entry_timing="chasing",
            required_pullback=2.0
        )
        analyzer._calculate_score(analysis2)
        assert analysis2.score >= 0.0
        assert analysis2.confidence >= 0.0


class TestTagGeneration:
    """测试标签生成"""

    @pytest.fixture
    def analyzer(self):
        """创建 analyzer"""
        collector = MagicMock(spec=BinanceCollector)
        return CoinAnalyzer(collector)

    def test_timing_tags(self, analyzer):
        """测试入场时机标签"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0,
            entry_timing="optimal"
        )
        analyzer._add_tags(analysis)
        assert "TIMING:OPTIMAL" in analysis.tags

        analysis2 = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.SHORT,
            score=50.0,
            confidence=50.0,
            entry_timing="chasing"
        )
        analyzer._add_tags(analysis2)
        assert "TIMING:CHASING" in analysis2.tags

    def test_volatility_tags(self, analyzer):
        """测试波动性标签"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            volatility_24h=12.0
        )
        analyzer._add_tags(analysis)
        assert "extreme_volatility" in analysis.tags

        analysis2 = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            volatility_24h=7.0
        )
        analyzer._add_tags(analysis2)
        assert "high_volatility" in analysis2.tags

    def test_atr_tags(self, analyzer):
        """测试 ATR 标签"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0,
            atr_pct=6.0
        )
        analyzer._add_tags(analysis)
        assert "ATR:6.0%" in analysis.tags
        assert "high_atr" in analysis.tags

    def test_trend_tags(self, analyzer):
        """测试趋势标签"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0,
            price_change_24h=15.0
        )
        analyzer._add_tags(analysis)
        assert "strong_uptrend" in analysis.tags

        analysis2 = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.SHORT,
            score=50.0,
            confidence=50.0,
            price_change_24h=-12.0
        )
        analyzer._add_tags(analysis2)
        assert "strong_downtrend" in analysis2.tags

    def test_oi_tags(self, analyzer):
        """测试 OI 标签"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0,
            oi_change_1h=15.0
        )
        analyzer._add_tags(analysis)
        assert "oi_surge" in analysis.tags

        analysis2 = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.SHORT,
            score=50.0,
            confidence=50.0,
            oi_change_1h=-12.0
        )
        analyzer._add_tags(analysis2)
        assert "oi_drop" in analysis2.tags


class TestFlashCrashRisk:
    """测试闪崩风险检测"""

    @pytest.fixture
    def analyzer(self):
        """创建 analyzer"""
        collector = MagicMock(spec=BinanceCollector)
        return CoinAnalyzer(collector)

    def test_no_flash_crash_risk(self, analyzer):
        """测试无闪崩风险"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            volatility_24h=3.0,
            price_change_24h=-1.0,
            oi_change_1h=2.0,
            funding_rate=0.0001
        )
        assert not analyzer._check_flash_crash_risk(analysis)

    def test_flash_crash_risk_high_volatility(self, analyzer):
        """测试高波动闪崩风险"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            score=50.0,
            confidence=50.0,
            volatility_24h=10.0,  # 高波动
            price_change_24h=-8.0,  # 大幅下跌
            oi_change_1h=20.0,  # OI 急增
            funding_rate=0.002  # 极端费率
        )
        assert analyzer._check_flash_crash_risk(analysis)

    def test_flash_crash_risk_oi_price_divergence(self, analyzer):
        """测试 OI 增加 + 价格下跌的闪崩风险"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            score=50.0,
            confidence=50.0,
            volatility_24h=9.0,
            price_change_24h=-6.0,
            oi_change_1h=15.0,  # OI 增加
            price_change_1h=-4.0,  # 价格下跌
            funding_rate=0.0001
        )
        assert analyzer._check_flash_crash_risk(analysis)


class TestCMCEnhancement:
    """测试 CMC 数据增强"""

    @pytest.fixture
    def analyzer(self):
        """创建带 CMC 数据的 analyzer"""
        collector = MagicMock(spec=BinanceCollector)
        analyzer = CoinAnalyzer(collector)
        analyzer.set_cmc_data(
            trending=[{"symbol": "BTC", "trending_score": 95, "rank": 1}],
            gainers=[{"symbol": "ETH", "percent_change_24h": 10.5, "rank": 2}],
            losers=[{"symbol": "SOL", "percent_change_24h": -8.0, "rank": 5}]
        )
        return analyzer

    def test_cmc_trending_enhancement(self, analyzer):
        """测试 CMC 热门增强"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0
        )
        analyzer._enhance_with_cmc(analysis)
        assert analysis.cmc_trending
        assert analysis.cmc_trending_score == 95
        assert analysis.cmc_rank == 1
        assert "cmc_trending" in analysis.tags

    def test_cmc_gainer_enhancement(self, analyzer):
        """测试 CMC 涨幅榜增强"""
        analysis = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0
        )
        analyzer._enhance_with_cmc(analysis)
        assert "cmc_gainer" in analysis.tags
        assert analysis.cmc_rank == 2

    def test_cmc_loser_enhancement(self, analyzer):
        """测试 CMC 跌幅榜增强"""
        analysis = CoinAnalysis(
            symbol="SOLUSDT",
            direction=Direction.SHORT,
            score=50.0,
            confidence=50.0
        )
        analyzer._enhance_with_cmc(analysis)
        assert "cmc_loser" in analysis.tags


class TestAsyncMethods:
    """测试异步方法"""

    @pytest.fixture
    def mock_collector(self):
        """创建完整模拟的 collector"""
        collector = MagicMock(spec=BinanceCollector)

        # 模拟 ticker 数据
        collector.get_all_tickers = AsyncMock(return_value={
            "BTCUSDT": TickerData(
                symbol="BTCUSDT",
                price=50000.0,
                price_change_24h=2.0,
                volume_24h=1000000000.0,
                volatility_24h=5.0
            ),
            "ETHUSDT": TickerData(
                symbol="ETHUSDT",
                price=3000.0,
                price_change_24h=-3.0,
                volume_24h=500000000.0,
                volatility_24h=6.0
            )
        })

        # 模拟 OI 数据
        collector.get_all_oi = AsyncMock(return_value={
            "BTCUSDT": OIData(
                symbol="BTCUSDT",
                oi_value=5000000000.0,
                oi_coins=100000.0,
                oi_change_1h=2.0
            ),
            "ETHUSDT": OIData(
                symbol="ETHUSDT",
                oi_value=1000000000.0,
                oi_coins=333333.0,
                oi_change_1h=5.0
            )
        })

        # 模拟资金费率
        collector.get_all_funding_rates = AsyncMock(return_value={
            "BTCUSDT": FundingData(
                symbol="BTCUSDT",
                funding_rate=0.0001,
                next_funding_time=0
            ),
            "ETHUSDT": FundingData(
                symbol="ETHUSDT",
                funding_rate=-0.0002,
                next_funding_time=0
            )
        })

        collector.calculate_price_changes = AsyncMock(return_value=(1.5, 3.0))
        collector.calculate_multi_period_vwap = AsyncMock(return_value={
            "1h": {"vwap": 50000.0, "price_vs_vwap": 0.0},
            "4h": {"vwap": 49000.0, "price_vs_vwap": 2.0}
        })
        collector.calculate_entry_timing = AsyncMock(return_value={
            "timing": "optimal",
            "timing_score": 75,
            "pullback_pct": 2.0,
            "required_pullback": 2.5,
            "atr_pct": 3.0,
            "support_distance": 1.5,
            "resistance_distance": 3.0,
            "swing_high": 51000.0,
            "swing_low": 48000.0,
            "reasons": ["回调到位"]
        })

        return collector

    @pytest.mark.asyncio
    async def test_analyze_all(self, mock_collector):
        """测试分析所有币种"""
        analyzer = CoinAnalyzer(mock_collector)
        results = await analyzer.analyze_all()

        assert len(results) == 2
        assert "BTCUSDT" in results
        assert "ETHUSDT" in results

    @pytest.mark.asyncio
    async def test_get_long_candidates(self, mock_collector):
        """测试获取做多候选"""
        analyzer = CoinAnalyzer(mock_collector)
        candidates = await analyzer.get_long_candidates(limit=10)

        # 应该返回做多方向的候选
        for c in candidates:
            assert c.direction == Direction.LONG

    @pytest.mark.asyncio
    async def test_get_short_candidates(self, mock_collector):
        """测试获取做空候选"""
        analyzer = CoinAnalyzer(mock_collector)
        candidates = await analyzer.get_short_candidates(limit=10)

        for c in candidates:
            assert c.direction == Direction.SHORT

    @pytest.mark.asyncio
    async def test_get_balanced_candidates(self, mock_collector):
        """测试获取平衡候选"""
        analyzer = CoinAnalyzer(mock_collector)
        candidates = await analyzer.get_balanced_candidates(limit=8)

        # 应该返回多空平衡的候选
        assert len(candidates) <= 8


class TestMarketCapWeight:
    """测试市值权重功能"""

    def test_calculate_market_cap_weight_tier1(self):
        """测试 Tier1 权重（BTC/ETH, rank 1-2）"""
        assert CoinAnalyzer.calculate_market_cap_weight(1) == 1.0
        assert CoinAnalyzer.calculate_market_cap_weight(2) == 1.0

    def test_calculate_market_cap_weight_tier2(self):
        """测试 Tier2 权重（rank 3-10）"""
        assert CoinAnalyzer.calculate_market_cap_weight(3) == 0.8
        assert CoinAnalyzer.calculate_market_cap_weight(10) == 0.8

    def test_calculate_market_cap_weight_tier3(self):
        """测试 Tier3 权重（rank 11-30）"""
        assert CoinAnalyzer.calculate_market_cap_weight(11) == 0.6
        assert CoinAnalyzer.calculate_market_cap_weight(30) == 0.6

    def test_calculate_market_cap_weight_tier4(self):
        """测试 Tier4 权重（rank 31-100）"""
        assert CoinAnalyzer.calculate_market_cap_weight(31) == 0.4
        assert CoinAnalyzer.calculate_market_cap_weight(100) == 0.4

    def test_calculate_market_cap_weight_tier5(self):
        """测试 Tier5 权重（rank 101-200）"""
        assert CoinAnalyzer.calculate_market_cap_weight(101) == 0.2
        assert CoinAnalyzer.calculate_market_cap_weight(200) == 0.2

    def test_calculate_market_cap_weight_default(self):
        """测试默认权重（rank > 200）"""
        assert CoinAnalyzer.calculate_market_cap_weight(201) == 0.1
        assert CoinAnalyzer.calculate_market_cap_weight(500) == 0.1

    def test_calculate_market_cap_weight_unknown(self):
        """测试未知排名权重（rank <= 0）"""
        assert CoinAnalyzer.calculate_market_cap_weight(0) == 0.5
        assert CoinAnalyzer.calculate_market_cap_weight(-1) == 0.5

    def test_apply_market_cap_weight(self):
        """测试权重应用公式: final = base * (1 + weight * 0.3)"""
        # k = 0.3
        # base=100, weight=1.0 -> 100 * 1.3 = 130
        assert CoinAnalyzer.apply_market_cap_weight(100, 1.0) == pytest.approx(130.0)
        # base=100, weight=0.5 -> 100 * 1.15 = 115
        assert CoinAnalyzer.apply_market_cap_weight(100, 0.5) == pytest.approx(115.0)
        # base=80, weight=0.2 -> 80 * 1.06 = 84.8
        assert CoinAnalyzer.apply_market_cap_weight(80, 0.2) == pytest.approx(84.8)

    def test_coin_analysis_market_cap_fields(self):
        """测试 CoinAnalysis 市值字段默认值"""
        analysis = CoinAnalysis(
            symbol="TESTUSDT",
            direction=Direction.LONG,
            score=50.0,
            confidence=50.0
        )
        assert analysis.market_cap == 0.0
        assert analysis.market_cap_rank == 0
        assert analysis.market_cap_weight == 0.5

    def test_cmc_listings_enhancement(self):
        """测试 CMC listings 数据增强市值字段"""
        collector = MagicMock(spec=BinanceCollector)
        analyzer = CoinAnalyzer(collector)

        # 设置 CMC listings 数据
        analyzer.set_cmc_data(
            listings={
                "BTCUSDT": {"cmc_rank": 1, "market_cap": 1800000000000},
                "ETHUSDT": {"cmc_rank": 2, "market_cap": 400000000000},
                "SOLUSDT": {"cmc_rank": 5, "market_cap": 80000000000},
            }
        )

        # 创建分析对象并增强
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=80.0,
            confidence=75.0
        )
        analyzer._enhance_with_cmc(analysis)

        # 验证市值字段已填充
        assert analysis.market_cap == 1800000000000
        assert analysis.market_cap_rank == 1
        assert analysis.market_cap_weight == 1.0  # rank 1 -> weight 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
