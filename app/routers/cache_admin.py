#!/usr/bin/env python3
"""缓存管理路由（状态查看 / 手动预热 / 清空）。"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_auth
from app.dependencies import get_cache_warmer
from core.cache import get_cache
from core.cache_warmer import CacheWarmer
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cache_admin"])


@router.get("/api/cache/status")
async def get_cache_status(
    auth: str = Depends(require_auth),
    cache_warmer: CacheWarmer = Depends(get_cache_warmer),
):
    """
    获取缓存状态

    返回:
    - 缓存命中率
    - 缓存条目数量
    - 上次预热时间
    - 预热器运行状态
    """
    cache = get_cache()
    stats = cache.get_stats()
    entries = cache.list_entries()

    return {
        "success": True,
        "data": {
            "enabled": settings.cache_warmup_enabled,
            "ttl": settings.cache_warmup_ttl,
            "stats": stats,
            "entries": entries,
            "warmer": {
                "running": cache_warmer.is_running() if cache_warmer else False,
                "last_warmup": cache_warmer.get_last_warmup_time() if cache_warmer else 0,
            },
            "timestamp": int(time.time()),
        },
    }


@router.post("/api/cache/warmup")
async def trigger_warmup(
    auth: str = Depends(require_auth),
    cache_warmer: CacheWarmer = Depends(get_cache_warmer),
):
    """手动触发缓存预热"""
    if not cache_warmer:
        raise HTTPException(status_code=503, detail="缓存预热器未启用")

    try:
        result = await cache_warmer.warmup()
        return {
            "success": True,
            "data": result,
        }
    except Exception as e:
        logger.error(f"手动预热失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/cache/clear")
async def clear_cache(auth: str = Depends(require_auth)):
    """清空缓存"""
    cache = get_cache()
    cache.clear()

    return {
        "success": True,
        "message": "缓存已清空",
    }
