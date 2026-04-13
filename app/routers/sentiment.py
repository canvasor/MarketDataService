#!/usr/bin/env python3
"""市场情绪路由（恐惧贪婪指数 / 综合情绪）。"""

import logging
import time

from fastapi import APIRouter, Depends, Query

from app.auth import require_auth
from app.dependencies import get_cmc_collector
from collectors.cmc_collector import CMCCollector
from core.cache import APICache, get_cache
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sentiment"])


@router.get("/api/sentiment/fear-greed")
async def get_fear_greed(
    auth: str = Depends(require_auth),
    history: int = Query(0, ge=0, le=30, description="历史天数（0=仅当前）"),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取恐惧贪婪指数（免费接口，无需 CMC key）

    返回:
    - value: 0-100 (0=极度恐惧, 100=极度贪婪)
    - classification: Extreme Fear/Fear/Neutral/Greed/Extreme Greed

    恐惧贪婪指数说明:
    - 0-24: Extreme Fear（极度恐惧）- 可能是买入机会
    - 25-44: Fear（恐惧）
    - 45-55: Neutral（中性）
    - 56-75: Greed（贪婪）
    - 76-100: Extreme Greed（极度贪婪）- 可能是卖出信号
    """
    try:
        cache = get_cache()
        cache_key = f"{APICache.KEY_SENTIMENT_FG_PREFIX}{history}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        result = {
            "success": True,
            "data": {
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }

        # 获取当前指数
        current = await cmc_collector.get_fear_greed_index()
        if current:
            result["data"]["current"] = {
                "value": current.value,
                "classification": current.value_classification,
                "timestamp": current.timestamp,
            }
        else:
            result["data"]["current"] = None
            result["data"]["error"] = "无法获取恐惧贪婪指数"

        # 获取历史数据
        if history > 0:
            history_data = await cmc_collector.get_fear_greed_history(history)
            result["data"]["history"] = history_data

        cache.set(cache_key, result, ttl=settings.cache_ttl_macro)
        return result

    except Exception as e:
        logger.error(f"获取恐惧贪婪指数失败: {e}")
        # 返回错误但不抛异常，保持接口可用
        return {
            "success": False,
            "data": {
                "error": str(e),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }


@router.get("/api/sentiment/market")
async def get_market_sentiment(
    auth: str = Depends(require_auth),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取综合市场情绪（整合多个数据源）

    无需 CMC key 也能返回:
    - 恐惧贪婪指数
    - 市场趋势判断

    有 CMC key 额外返回:
    - 全网总市值
    - BTC/ETH 主导率
    - 山寨季指数
    """
    try:
        cache = get_cache()
        cached = cache.get(APICache.KEY_SENTIMENT_MARKET)
        if cached:
            return cached
        sentiment = await cmc_collector.safe_get_market_sentiment()
        result = {
            "success": True,
            "data": sentiment,
        }
        cache.set(APICache.KEY_SENTIMENT_MARKET, result, ttl=settings.cache_ttl_macro)
        return result
    except Exception as e:
        logger.error(f"获取市场情绪失败: {e}")
        return {
            "success": False,
            "data": {
                "available": False,
                "error": str(e),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
