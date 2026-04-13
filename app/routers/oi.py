#!/usr/bin/env python3
"""OI（持仓量）排行路由。"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_auth
from app.dependencies import get_cmc_collector, get_collector
from app.schemas import OIRankingResponse
from collectors.cmc_collector import CMCCollector
from collectors.market_data_collector import UnifiedMarketCollector
from core.cache import APICache, get_cache
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oi"])


@router.get("/api/oi/top-ranking", response_model=OIRankingResponse)
async def get_oi_top_ranking(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    duration: str = Query("1h", description="时间范围: 1m/5m/15m/30m/1h/4h/8h/12h/24h"),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    """获取 OI 持仓增加排行（兼容官方接口，支持缓存）"""
    # limit <= 20 且 duration=1h 时尝试从缓存获取
    if limit <= 20 and duration == "1h":
        cache = get_cache()
        cached_data = cache.get(APICache.KEY_OI_TOP)
        if cached_data:
            logger.debug("oi/top-ranking 命中缓存")
            # 如果请求的 limit 小于缓存数量，截取
            if limit < len(cached_data.get("positions", [])):
                result_data = cached_data.copy()
                result_data["positions"] = cached_data["positions"][:limit]
                result_data["count"] = limit
                result_data["limit"] = limit
                return OIRankingResponse(success=True, code=0, data=result_data)
            return OIRankingResponse(success=True, code=0, data=cached_data)

    try:
        # 使用带历史数据的方法获取 OI 排行
        oi_list = await collector.get_oi_ranking_with_history(rank_type="top", limit=limit)
        tickers = await collector.get_all_tickers()

        positions = []
        for i, oi in enumerate(oi_list):
            ticker = tickers.get(oi.symbol)
            price_change = ticker.price_change_24h if ticker else 0

            positions.append({
                "rank": i + 1,
                "symbol": oi.symbol,
                "current_oi": oi.oi_coins,
                "oi_delta": oi.oi_coins * (oi.oi_change_1h / 100) if oi.oi_change_1h else 0,
                "oi_delta_percent": oi.oi_change_1h,
                "oi_delta_value": oi.oi_delta_value_1h,
                "price_delta_percent": price_change,
                "net_long": 0,
                "net_short": 0,
            })

        duration_map = {
            "1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
            "1h": "1小时", "4h": "4小时", "8h": "8小时", "12h": "12小时",
            "24h": "24小时", "1d": "1天", "2d": "2天", "3d": "3天",
        }

        return OIRankingResponse(
            success=True,
            code=0,
            data={
                "positions": positions,
                "count": len(positions),
                "exchange": "binance",
                "rank_type": "top",
                "time_range": duration_map.get(duration, duration),
                "time_range_param": duration,
                "limit": limit,
            },
        )
    except Exception as e:
        logger.error(f"获取 OI Top 排行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/oi/low-ranking", response_model=OIRankingResponse)
async def get_oi_low_ranking(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    duration: str = Query("1h", description="时间范围"),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    """获取 OI 持仓减少排行（兼容官方接口）"""
    # limit <= 20 且 duration=1h 时尝试从缓存获取
    if limit <= 20 and duration == "1h":
        cache = get_cache()
        cached_data = cache.get(APICache.KEY_OI_LOW)
        if cached_data:
            logger.debug("oi/low-ranking 命中缓存")
            if limit < len(cached_data.get("positions", [])):
                result_data = cached_data.copy()
                result_data["positions"] = cached_data["positions"][:limit]
                result_data["count"] = limit
                result_data["limit"] = limit
                return OIRankingResponse(success=True, code=0, data=result_data)
            return OIRankingResponse(success=True, code=0, data=cached_data)

    try:
        # 使用带历史数据的方法获取 OI 排行
        oi_list = await collector.get_oi_ranking_with_history(rank_type="low", limit=limit)
        tickers = await collector.get_all_tickers()

        positions = []
        for i, oi in enumerate(oi_list):
            ticker = tickers.get(oi.symbol)
            price_change = ticker.price_change_24h if ticker else 0

            positions.append({
                "rank": i + 1,
                "symbol": oi.symbol,
                "current_oi": oi.oi_coins,
                "oi_delta": oi.oi_coins * (oi.oi_change_1h / 100) if oi.oi_change_1h else 0,
                "oi_delta_percent": oi.oi_change_1h,
                "oi_delta_value": oi.oi_delta_value_1h,
                "price_delta_percent": price_change,
                "net_long": 0,
                "net_short": 0,
            })

        duration_map = {
            "1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
            "1h": "1小时", "4h": "4小时", "8h": "8小时", "12h": "12小时",
            "24h": "24小时", "1d": "1天", "2d": "2天", "3d": "3天",
        }

        return OIRankingResponse(
            success=True,
            code=0,
            data={
                "positions": positions,
                "count": len(positions),
                "exchange": "binance",
                "rank_type": "low",
                "time_range": duration_map.get(duration, duration),
                "time_range_param": duration,
                "limit": limit,
            },
        )
    except Exception as e:
        logger.error(f"获取 OI Low 排行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/oi/top", response_model=OIRankingResponse)
async def get_oi_top(
    auth: str = Depends(require_auth),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    """获取 OI Top 20（固定参数，兼容官方接口，支持缓存）"""
    # 尝试从缓存获取
    cache = get_cache()
    cached_data = cache.get(APICache.KEY_OI_TOP)
    if cached_data:
        logger.debug("oi/top 命中缓存")
        return OIRankingResponse(success=True, code=0, data=cached_data)

    return await get_oi_top_ranking(auth=auth, limit=20, duration="1h", collector=collector)


@router.get("/api/oi-cap/ranking")
async def get_oi_cap_ranking(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100),
    collector: UnifiedMarketCollector = Depends(get_collector),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    cache = get_cache()
    cached = cache.get(APICache.KEY_OI_CAP)
    if cached:
        return cached
    listings = await cmc_collector.get_latest_listings(300)
    lookup = {k: {"market_cap": v.market_cap, "cmc_rank": v.cmc_rank} for k, v in listings.items()}
    rows = await collector.get_oi_cap_ranking(market_cap_lookup=lookup, limit=limit)
    result = {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "timestamp": int(time.time()),
            "market_cap_provider": cmc_collector.active_provider,
        },
    }
    cache.set(APICache.KEY_OI_CAP, result, ttl=settings.cache_ttl_ranking)
    return result
