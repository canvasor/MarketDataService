#!/usr/bin/env python3
"""全局服务实例管理与 FastAPI 依赖注入。"""

import logging
from typing import Optional

from fastapi import HTTPException

from collectors.market_data_collector import UnifiedMarketCollector
from collectors.cmc_collector import CMCCollector
from analysis.coin_analyzer import CoinAnalyzer
from core.cache_warmer import CacheWarmer
from core.cache import APICache

logger = logging.getLogger(__name__)

# 全局服务实例
_collector: Optional[UnifiedMarketCollector] = None
_cmc_collector: Optional[CMCCollector] = None
_analyzer: Optional[CoinAnalyzer] = None
_cache_warmer: Optional[CacheWarmer] = None
_api_cache: Optional[APICache] = None


def init_services(
    collector: UnifiedMarketCollector,
    cmc_collector: CMCCollector,
    analyzer: CoinAnalyzer,
    api_cache: APICache,
    cache_warmer: Optional[CacheWarmer] = None,
):
    """在 lifespan 中调用，初始化所有服务实例"""
    global _collector, _cmc_collector, _analyzer, _cache_warmer, _api_cache
    _collector = collector
    _cmc_collector = cmc_collector
    _analyzer = analyzer
    _api_cache = api_cache
    _cache_warmer = cache_warmer


def cleanup_services():
    """清理全局引用"""
    global _collector, _cmc_collector, _analyzer, _cache_warmer, _api_cache
    _collector = None
    _cmc_collector = None
    _analyzer = None
    _cache_warmer = None
    _api_cache = None


def get_collector() -> UnifiedMarketCollector:
    if _collector is None:
        raise HTTPException(status_code=503, detail="采集器未就绪")
    return _collector


def get_collector_optional() -> Optional[UnifiedMarketCollector]:
    """可选注入：collector 未就绪时返回 None 而非抛异常。
    用于 /health 等需要在启动期间优雅降级的端点。"""
    return _collector


def get_cmc_collector() -> CMCCollector:
    if _cmc_collector is None:
        raise HTTPException(status_code=503, detail="宏观数据采集器未就绪")
    return _cmc_collector


def get_analyzer() -> CoinAnalyzer:
    if _analyzer is None:
        raise HTTPException(status_code=503, detail="分析器未就绪")
    return _analyzer


def get_cache_warmer() -> Optional[CacheWarmer]:
    return _cache_warmer


def get_api_cache() -> Optional[APICache]:
    return _api_cache
