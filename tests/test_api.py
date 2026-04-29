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

# Mock 依赖，防止 factory 在模块加载时启动真实服务
with patch('app.factory.UnifiedMarketCollector'), \
     patch('app.factory.CMCCollector'), \
     patch('app.factory.CoinAnalyzer'), \
     patch('app.factory.CacheWarmer'), \
     patch('app.factory.init_cache'), \
     patch('core.cache.get_cache') as mock_get_cache:
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_get_cache.return_value = mock_cache
    from app import create_app
    app = create_app()

from app.auth import verify_auth
from app.converters import analysis_to_coin_info
from app.dependencies import get_analyzer, get_cmc_collector, get_collector
from app.schemas import CoinInfo, AI500Response, OIRankingResponse
from analysis.coin_analyzer import CoinAnalysis, Direction
from core.config import settings


class TestAuthVerification:
    """测试认证验证"""

    def test_valid_auth(self):
        """测试有效认证"""
        assert verify_auth(settings.auth_key) is True

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
        mock_collector = MagicMock()
        mock_collector.get_provider_status.return_value = {"binance": True}
        with patch('app.dependencies._collector', mock_collector):
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["auth"]["env_keys"] == ["NOFXOS_API_KEY", "NOFX_LOCAL_AUTH_KEY"]
        assert data["cache_warmup"]["second_offset"] == 30
        assert data["cache_warmup"]["minutes"] == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]

    def test_health_check_is_degraded_when_collector_is_missing(self, client):
        with patch('app.dependencies._collector', None):
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["collector_initialized"] is False


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


class TestAnalysisEndpoints:
    """测试分析类端点"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_high_volatility_passes_min_volatility_to_analyzer(self, client):
        class StubAnalyzer:
            async def get_high_volatility_coins(self, min_volatility, limit):
                assert min_volatility == 12.0
                assert limit == 5
                return []

        app.dependency_overrides[get_analyzer] = lambda: StubAnalyzer()
        app.dependency_overrides[get_cmc_collector] = lambda: MagicMock(_pick_provider=lambda: "coingecko")

        try:
            response = client.get(
                f"/api/analysis/high-volatility?auth={settings.auth_key}&min_volatility=12&limit=5"
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["min_volatility"] == 12.0


class TestMarketDataEndpoints:
    """测试行情类端点"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_netflow_ranking_rejects_unsupported_type(self, client):
        mock_collector = MagicMock()
        mock_collector.get_netflow_ranking = AsyncMock(return_value=[])
        app.dependency_overrides[get_collector] = lambda: mock_collector

        try:
            response = client.get(
                f"/api/netflow/top-ranking?auth={settings.auth_key}&type=institution"
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json()["detail"] == "仅支持 type=proxy，institution/personal 暂未实现"

    def test_netflow_ranking_accepts_auth_header(self, client):
        mock_collector = MagicMock()
        mock_collector.get_netflow_ranking = AsyncMock(return_value=[])
        app.dependency_overrides[get_collector] = lambda: mock_collector

        try:
            response = client.get(
                "/api/netflow/top-ranking",
                headers={"X-API-Key": settings.auth_key},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200

    def test_price_ranking_cache_miss_returns_warming_up_without_recompute(self, client):
        mock_collector = MagicMock()
        mock_collector.get_price_ranking = AsyncMock(return_value=[{"symbol": "BTCUSDT"}])
        mock_cache = MagicMock()
        mock_cache.get_with_state.return_value = (None, "miss")

        app.dependency_overrides[get_collector] = lambda: mock_collector
        try:
            with patch("app.routers.market_data.get_cache", return_value=mock_cache):
                response = client.get(
                    "/api/price/ranking?duration=1h&limit=20",
                    headers={"X-API-Key": settings.auth_key},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["detail"] == "price_ranking_warming_up"
        mock_collector.get_price_ranking.assert_not_called()

    def test_price_ranking_returns_stale_cache_without_recompute(self, client):
        mock_collector = MagicMock()
        mock_collector.get_price_ranking = AsyncMock(return_value=[{"symbol": "ETHUSDT"}])
        cached = {
            "success": True,
            "data": {
                "rows": [{"symbol": "BTCUSDT"}],
                "count": 1,
                "duration": "1h",
                "timestamp": 1712000000,
            },
        }
        mock_cache = MagicMock()
        mock_cache.get_with_state.return_value = (cached, "stale")

        app.dependency_overrides[get_collector] = lambda: mock_collector
        try:
            with patch("app.routers.market_data.get_cache", return_value=mock_cache):
                response = client.get(
                    "/api/price/ranking?duration=1h&limit=20",
                    headers={"X-API-Key": settings.auth_key},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["data"]["rows"] == [{"symbol": "BTCUSDT"}]
        mock_collector.get_price_ranking.assert_not_called()


class TestResponseModels:
    """测试响应模型"""

    def test_coin_info_model(self):
        """测试 CoinInfo 模型"""
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


class TestAI500StatsEndpoint:
    """测试 AI500 stats 路由不会被 /api/ai500/{symbol} 截获"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_ai500_stats_route_matches_before_symbol_route(self, client):
        analysis = CoinAnalysis(
            symbol="BTCUSDT",
            direction=Direction.LONG,
            score=80.0,
            confidence=70.0,
        )
        analyzer = MagicMock()
        analyzer.analyze_all = AsyncMock(return_value={"BTCUSDT": analysis})
        analyzer.set_cmc_data = MagicMock()

        cmc_collector = MagicMock()
        cmc_collector.get_trending = AsyncMock(return_value=[])
        cmc_collector.get_gainers_losers = AsyncMock(return_value=([], []))
        cmc_collector.get_latest_listings = AsyncMock(return_value={})

        app.dependency_overrides[get_analyzer] = lambda: analyzer
        app.dependency_overrides[get_cmc_collector] = lambda: cmc_collector

        try:
            response = client.get(
                "/api/ai500/stats",
                headers={"X-API-Key": settings.auth_key},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["universe_count"] == 1
        assert data["active_count"] == 1


class TestOIRankingResponse:
    """测试 OI 排行响应模型"""

    def test_oi_ranking_response(self):
        """测试 OI 排行响应"""
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
        # 应该返回 422 (参数缺失)、401 (未授权)、或 503 (依赖未就绪)
        assert response.status_code in [401, 422, 503]

    def test_invalid_auth(self, client):
        """测试无效认证"""
        response = client.get("/api/analysis/short?auth=invalid")
        assert response.status_code == 401


class TestSystemStatusEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_system_status_includes_auth_and_cache_warmup_metadata(self, client):
        mock_collector = MagicMock()
        mock_collector.get_system_status = AsyncMock(return_value={"exchange": "ok"})

        with patch('app.dependencies._collector', mock_collector):
            response = client.get("/api/system/status", params={"auth": settings.auth_key})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["exchange"] == "ok"
        assert data["data"]["auth"]["env_keys"] == ["NOFXOS_API_KEY", "NOFX_LOCAL_AUTH_KEY"]
        assert data["data"]["cache_warmup"]["second_offset"] == 30

    def test_system_status_uses_short_cache_to_avoid_repeated_collection(self, client):
        from core.cache import init_cache, get_cache as real_get_cache

        mock_collector = MagicMock()
        mock_collector.get_system_status = AsyncMock(return_value={"exchange": "ok"})
        init_cache()

        with patch('app.dependencies._collector', mock_collector), \
             patch('app.routers.system.get_cache', real_get_cache):
            first = client.get("/api/system/status", params={"auth": settings.auth_key})
            second = client.get("/api/system/status", params={"auth": settings.auth_key})

        assert first.status_code == 200
        assert second.status_code == 200
        assert mock_collector.get_system_status.await_count == 1


class TestCacheModels:
    """测试缓存相关模型"""

    def test_cache_key_generation(self):
        """测试缓存键生成"""
        from core.cache import APICache

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
        response = client.get('/api/system/strategy-universe', params={'auth': settings.auth_key})
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'symbols' in data['data']

    def test_pair_template_endpoint(self, client):
        response = client.get('/api/strategy/pair-neutral/template', params={'auth': settings.auth_key})
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'template' in data['data']
        assert 'backtest_fields' in data['data']
