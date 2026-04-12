#!/usr/bin/env python3
"""系统状态与健康检查路由。"""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from analysis.coin_analyzer import CoinAnalyzer
from app.auth import build_auth_metadata, require_auth
from app.dependencies import (
    get_cache_warmer,
    get_cmc_collector,
    get_collector_optional,
)
from collectors.cmc_collector import CMCCollector
from collectors.market_data_collector import UnifiedMarketCollector
from core.cache import APICache, get_cache
from core.cache_warmer import CacheWarmer, get_warmup_schedule
from core.config import settings
from tools.nofx_mapping import build_mapping_summary
from tools.strategy_tools import (
    NOFX_ADAPTATION_CHECKLIST,
    build_universe_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


# ==================== 辅助函数 ====================


def build_cache_warmup_metadata() -> Dict[str, Any]:
    return {
        "enabled": settings.cache_warmup_enabled,
        "ttl": settings.cache_warmup_ttl,
        **get_warmup_schedule(),
    }


def build_health_checks(
    provider_status: Dict[str, Any],
    collector: Optional[UnifiedMarketCollector],
) -> Dict[str, Any]:
    degraded_providers: List[str] = []
    for provider, info in provider_status.items():
        if not isinstance(info, dict):
            continue
        if (
            info.get("enabled", True)
            and int(info.get("errors") or 0) > 0
            and int(info.get("last_success") or 0) == 0
        ):
            degraded_providers.append(provider)

    return {
        "collector_initialized": collector is not None,
        "provider_count": len(provider_status),
        "degraded_providers": degraded_providers,
    }


async def build_system_status_payload(
    collector: Optional[UnifiedMarketCollector],
) -> Dict[str, Any]:
    cache = get_cache()
    cached = cache.get(APICache.KEY_SYSTEM_STATUS)
    if isinstance(cached, dict):
        return cached

    status = await collector.get_system_status() if collector else {}
    if not isinstance(status, dict):
        status = {"collector_status": status}
    status["auth"] = build_auth_metadata(required=True)
    status["cache_warmup"] = build_cache_warmup_metadata()
    status["status_cache_ttl"] = settings.cache_ttl_ranking
    cache.set(APICache.KEY_SYSTEM_STATUS, status, ttl=settings.cache_ttl_ranking)
    return status


# ==================== 路由端点 ====================


@router.get("/")
async def root():
    """根路径"""
    return {
        "name": "NOFX Local Data Server",
        "version": "2.1.0",
        "status": "running",
        "compatibility_mode": settings.compatibility_mode,
        "providers": {
            "binance": True,
            "okx": settings.okx_enabled,
            "coingecko": settings.coingecko_api_key is not None,
            "cmc": settings.cmc_api_key is not None,
        },
        "endpoints": {
            "core": {
                "description": "NoFx 核心兼容接口（AI500 / OI / Coin / Funding / Price / Heatmap）",
                "endpoints": [
                    "/api/ai500/list",
                    "/api/ai500/{symbol}",
                    "/api/ai500/stats",
                    "/api/oi/top-ranking",
                    "/api/oi/low-ranking",
                    "/api/oi-cap/ranking",
                    "/api/price/ranking",
                    "/api/funding-rate/top",
                    "/api/funding-rate/low",
                    "/api/funding-rate/{symbol}",
                    "/api/heatmap/future/{symbol}",
                    "/api/heatmap/spot/{symbol}",
                    "/api/heatmap/list",
                    "/api/coin/{symbol}",
                ],
            },
            "extended": {
                "description": "增强分析与监控接口",
                "endpoints": [
                    "/api/analysis/short",
                    "/api/analysis/long",
                    "/api/analysis/early-signals",
                    "/api/analysis/flash-crash",
                    "/api/analysis/high-volatility",
                    "/api/analysis/market-overview",
                    "/api/netflow/top-ranking",
                    "/api/netflow/low-ranking",
                    "/api/system/status",
                    "/api/system/capabilities",
                    "/api/system/provider-usage",
                    "/api/system/nofx-compatibility",
                    "/api/system/strategy-universe",
                    "/api/system/nofx-adaptation-checklist",
                    "/api/cache/status",
                ],
            },
            "macro": {
                "description": "宏观与市值数据（优先 CoinGecko Demo，其次 CMC）",
                "endpoints": [
                    "/api/sentiment/fear-greed",
                    "/api/sentiment/market",
                    "/api/cmc/listings",
                    "/api/cmc/trending",
                    "/api/cmc/gainers-losers",
                    "/api/cmc/market-overview",
                ],
            },
            "strategy": {
                "description": "配对中性 / 固定币池策略辅助接口",
                "endpoints": [
                    "/api/strategy/pair-neutral/template",
                    "/api/strategy/pair-neutral/context",
                ],
            },
        },
    }


@router.get("/health")
async def health_check(
    collector: Optional[UnifiedMarketCollector] = Depends(get_collector_optional),
):
    """健康检查"""
    provider_status = (
        collector.get_provider_status()
        if collector and hasattr(collector, "get_provider_status")
        else {}
    )
    checks = build_health_checks(provider_status, collector)
    return {
        "status": (
            "healthy"
            if checks["collector_initialized"] and not checks["degraded_providers"]
            else "degraded"
        ),
        "timestamp": int(time.time()),
        "providers": provider_status,
        "coingecko_api": settings.coingecko_api_key is not None,
        "cmc_api": settings.cmc_api_key is not None,
        "auth": build_auth_metadata(required=False),
        "cache_warmup": build_cache_warmup_metadata(),
        "checks": checks,
    }


@router.get("/api/system/status")
async def get_system_status(
    auth: str = Depends(require_auth),
    collector: Optional[UnifiedMarketCollector] = Depends(get_collector_optional),
):
    status = await build_system_status_payload(collector)
    return {"success": True, "data": status}


@router.get("/api/system/capabilities")
async def get_system_capabilities(
    auth: str = Depends(require_auth),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    return {
        "success": True,
        "data": {
            "core_supported": [
                "ai500", "oi_ranking", "coin", "price_ranking",
                "funding_rate", "oi_cap_ranking", "heatmap", "sentiment",
            ],
            "proxy_supported": [
                "netflow_top_ranking", "netflow_low_ranking", "coin.netflow",
            ],
            "not_fully_supported": [
                "institution_vs_personal_true_split",
                "upbit_specific_endpoints",
                "query_rank",
                "ai300_proprietary_signal",
            ],
            "providers": {
                "market_cap_provider": cmc_collector.active_provider,
                "configured_macro_providers": cmc_collector.configured_providers,
                "okx_enabled": settings.okx_enabled,
            },
            "compatibility_summary": build_mapping_summary()["summary"],
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/system/provider-usage")
async def get_provider_usage(
    auth: str = Depends(require_auth),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    return {"success": True, "data": await cmc_collector.get_provider_usage()}


@router.get("/api/system/nofx-compatibility")
async def get_nofx_compatibility(auth: str = Depends(require_auth)):
    data = build_mapping_summary()
    data["timestamp"] = int(time.time())
    return {"success": True, "data": data}


@router.get("/api/system/strategy-universe")
async def get_strategy_universe(auth: str = Depends(require_auth)):
    data = build_universe_summary()
    data["timestamp"] = int(time.time())
    return {"success": True, "data": data}


@router.get("/api/system/nofx-adaptation-checklist")
async def get_nofx_adaptation_checklist(auth: str = Depends(require_auth)):
    return {
        "success": True,
        "data": {
            "items": NOFX_ADAPTATION_CHECKLIST,
            "timestamp": int(time.time()),
        },
    }
