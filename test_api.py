#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 接口单元测试

测试覆盖：
1. 健康检查接口
2. AI500 列表接口
3. OI 排行接口
4. 单币种数据接口
5. 市场情绪接口
6. 缓存接口
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Mock dependencies before importing main
with patch('main.BinanceCollector'), \
     patch('main.CMCCollector'), \
     patch('main.CoinAnalyzer'), \
     patch('main.CacheWarmer'), \
     patch('main.init_cache'), \
     patch('main.get_cache'):

    import main
    from main import app, verify_auth, analysis_to_coin_info
    from coin_analyzer import CoinAnalysis, Direction


class TestAuthVerification:
    """测试认证验证"""

    def test_valid_auth(self):
        """测试有效认证"""
        assert verify_auth("cm_568c67eae410d912c54c") is True

    def test_invalid_auth(self):
        """测试无效认证"""
        assert verify_auth("invalid_key") is False
        assert verify_auth("") is False
        assert verify_auth("cm_wrong_key") is False


class TestAnalysisToCoinfInfo:
    """测试分析结果转换"""

    def test_basic_conversion(self):
        """测试基础转换"""
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=85.0,
            confidence=75.0,
            price=50000.0,
            price_change_1h=2.0,
            price_change_24h=5.0,
            volatility_24h=4.0,
            oi_value=5000000000.0,
            oi_change_1h=3.0,
            funding_rate=0.0001,
            volume_24h=1000000000.0,
            entry_timing="optimal",
            timing_score=80.0,
            pullback_pct=2.5,
            required_pullback=3.0,
            atr_pct=3.5,
            tags=["high_volume"],
            reasons=["强势上涨"]
        )

        coin_info = analysis_to_coin_info(analysis)

        assert coin_info.pair == "BTCUSDT"
        assert coin_info.score == 85.0
        assert coin_info.direction == "long"
        assert coin_info.confidence == 75.0
        assert coin_info.price == 50000.0
        assert coin_info.entry_timing == "optimal"
        assert "DIRECTION:LONG" in coin_info.tags

    def test_timing_tag_insertion(self):
        """测试时机标签插入"""
        analysis = CoinAnalysis(
            symbol="ETHUSDT",
            direction=Direction.SHORT,
            score=70.0,
            confidence=65.0,
            entry_timing="chasing",
            tags=["TIMING:CHASING", "high_volatility"]
        )

        coin_info = analysis_to_coin_info(analysis)

        # DIRECTION 标签应该在 TIMING 标签后面
        tags = coin_info.tags
        timing_idx = next((i for i, t in enumerate(tags) if t.startswith("TIMING:")), -1)
        direction_idx = next((i for i, t in enumerate(tags) if t.startswith("DIRECTION:")), -1)

        assert timing_idx >= 0
        assert direction_idx > timing_idx

    def test_vwap_signal_tag(self):
        """测试 VWAP 信号标签"""
        analysis = CoinAnalysis(
            symbol="SOLUSDT",
            direction=Direction.LONG,
            score=75.0,
            confidence=70.0,
            vwap_signal="early_long",
            tags=["TIMING:OPTIMAL"]
        )

        coin_info = analysis_to_coin_info(analysis)

        assert "VWAP:early_long" in coin_info.tags


class TestHealthEndpoint:
    """测试健康检查端点"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        return TestClient(app)

    def test_health_check(self, client):
        """测试健康检查"""
        main.collector = MagicMock()
        main.collector.get_provider_status.return_value = {"binance": True}
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["auth"]["env_keys"] == ["NOFXOS_API_KEY", "NOFX_LOCAL_AUTH_KEY"]
        assert data["cache_warmup"]["second_offset"] == 30
        assert data["cache_warmup"]["minutes"] == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]


class TestRootEndpoint:
    """测试根路径端点"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        return TestClient(app)

    def test_root(self, client):
        """测试根路径"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "NOFX Local Data Server"
        assert "endpoints" in data


class TestResponseModels:
    """测试响应模型"""

    def test_coin_info_model(self):
        """测试 CoinInfo 模型"""
        from main import CoinInfo

        coin = CoinInfo(
            pair="BTCUSDT",
            score=85.0,
            start_time=1704067200,
            start_price=45000.0,
            last_score=84.0,
            max_score=90.0,
            max_price=52000.0,
            increase_percent=15.0
        )

        assert coin.pair == "BTCUSDT"
        assert coin.direction is None  # 可选字段
        assert coin.entry_timing is None

    def test_coin_info_with_extensions(self):
        """测试带扩展字段的 CoinInfo"""
        from main import CoinInfo

        coin = CoinInfo(
            pair="ETHUSDT",
            score=70.0,
            direction="short",
            confidence=65.0,
            price=3000.0,
            entry_timing="chasing",
            timing_score=30.0,
            pullback_pct=1.5,
            required_pullback=3.0,
            atr_pct=4.5,
            tags=["TIMING:CHASING", "high_volatility"]
        )

        assert coin.direction == "short"
        assert coin.entry_timing == "chasing"
        assert coin.atr_pct == 4.5


class TestAI500Response:
    """测试 AI500 响应模型"""

    def test_ai500_response(self):
        """测试 AI500 响应"""
        from main import AI500Response

        response = AI500Response(
            success=True,
            data={
                "coins": [{"pair": "BTCUSDT", "score": 85.0}],
                "count": 1,
                "direction": "balanced",
                "long_count": 1,
                "short_count": 0
            }
        )

        assert response.success is True
        assert response.data["count"] == 1


class TestOIRankingResponse:
    """测试 OI 排行响应模型"""

    def test_oi_ranking_response(self):
        """测试 OI 排行响应"""
        from main import OIRankingResponse

        response = OIRankingResponse(
            success=True,
            code=0,
            data={
                "positions": [
                    {
                        "rank": 1,
                        "symbol": "BTCUSDT",
                        "current_oi": 92000.0,
                        "oi_delta": 500.0,
                        "oi_delta_percent": 0.55
                    }
                ],
                "count": 1,
                "rank_type": "top"
            }
        )

        assert response.success is True
        assert response.code == 0


class TestAPIAuthentication:
    """测试 API 认证"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        return TestClient(app)

    def test_missing_auth(self, client):
        """测试缺少认证"""
        # 大多数端点需要认证
        response = client.get("/api/analysis/short")
        # 应该返回 422 (参数缺失) 或 401 (未授权)
        assert response.status_code in [401, 422]

    def test_invalid_auth(self, client):
        """测试无效认证"""
        response = client.get("/api/analysis/short?auth=invalid")
        assert response.status_code == 401


class TestSystemStatusEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_system_status_includes_auth_and_cache_warmup_metadata(self, client):
        main.collector = MagicMock()
        main.collector.get_system_status = AsyncMock(return_value={"exchange": "ok"})

        response = client.get("/api/system/status", params={"auth": "cm_568c67eae410d912c54c"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["exchange"] == "ok"
        assert data["data"]["auth"]["env_keys"] == ["NOFXOS_API_KEY", "NOFX_LOCAL_AUTH_KEY"]
        assert data["data"]["cache_warmup"]["second_offset"] == 30


class TestCacheModels:
    """测试缓存相关模型"""

    def test_cache_key_generation(self):
        """测试缓存键生成"""
        from cache import APICache

        cache = APICache()
        key = cache.get_coin_key("BTCUSDT")
        assert "BTCUSDT" in key


class TestTimingTagParsing:
    """测试时机标签解析"""

    def test_timing_tags_format(self):
        """测试时机标签格式"""
        valid_tags = [
            "TIMING:OPTIMAL",
            "TIMING:WAIT_PULLBACK",
            "TIMING:CHASING",
            "TIMING:EXTENDED",
            "TIMING:NEUTRAL"
        ]

        for tag in valid_tags:
            assert tag.startswith("TIMING:")
            timing_value = tag.split(":")[1]
            assert timing_value in ["OPTIMAL", "WAIT_PULLBACK", "CHASING", "EXTENDED", "NEUTRAL"]

    def test_direction_tags_format(self):
        """测试方向标签格式"""
        valid_tags = [
            "DIRECTION:LONG",
            "DIRECTION:SHORT",
            "DIRECTION:NEUTRAL"
        ]

        for tag in valid_tags:
            assert tag.startswith("DIRECTION:")
            direction_value = tag.split(":")[1]
            assert direction_value in ["LONG", "SHORT", "NEUTRAL"]


class TestATRTagFormat:
    """测试 ATR 标签格式"""

    def test_atr_tag_format(self):
        """测试 ATR 标签格式"""
        atr_tags = ["ATR:3.5%", "ATR:5.0%", "ATR:7.2%"]

        for tag in atr_tags:
            assert tag.startswith("ATR:")
            assert tag.endswith("%")
            # 提取数值部分
            value_str = tag[4:-1]  # 移除 "ATR:" 和 "%"
            value = float(value_str)
            assert value > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestStrategyEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_strategy_universe_endpoint(self, client):
        response = client.get('/api/system/strategy-universe', params={'auth': 'cm_568c67eae410d912c54c'})
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'symbols' in data['data']

    def test_pair_template_endpoint(self, client):
        response = client.get('/api/strategy/pair-neutral/template', params={'auth': 'cm_568c67eae410d912c54c'})
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'template' in data['data']
        assert 'backtest_fields' in data['data']
