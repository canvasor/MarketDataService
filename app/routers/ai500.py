#!/usr/bin/env python3
"""AI500 智能筛选路由。"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from analysis.coin_analyzer import CoinAnalyzer, Direction
from app.auth import require_auth
from app.converters import analysis_to_coin_info, fetch_coin_detail, load_cmc_data_for_analyzer
from app.dependencies import get_analyzer, get_cmc_collector, get_collector
from app.schemas import AI500Response
from app.utils import normalize_symbol
from collectors.cmc_collector import CMCCollector
from collectors.market_data_collector import UnifiedMarketCollector
from core.cache import APICache, get_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai500"])


@router.get("/api/ai500/list", response_model=AI500Response)
async def get_ai500_list(
    auth: str = Depends(require_auth),
    direction: Optional[str] = Query(None, description="筛选方向: long/short/balanced/all"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取智能筛选币种列表（兼容官方 AI500 接口）

    增强功能:
    - direction=long: 只返回做多候选
    - direction=short: 只返回做空候选
    - direction=balanced: 多空平衡（偶数各半，奇数空多一个）【推荐】
    - direction=all 或不填: 默认使用多空平衡模式
    - 自动整合 CMC 热门/涨跌幅数据，提升热门币种权重
    - 支持缓存预热，优先从缓存获取
    - 新增 VWAP 早期信号识别
    """
    try:
        # 尝试从缓存获取（limit <= 20 时可以从缓存截取）
        cache = get_cache()
        cache_key = None
        if limit <= 20:
            if direction == "short":
                cache_key = APICache.KEY_AI500_SHORT
            elif direction == "long":
                cache_key = APICache.KEY_AI500_LONG
            elif direction is None or direction == "balanced":
                cache_key = APICache.KEY_AI500_LIST

        if cache_key:
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.debug(f"ai500/{direction or 'balanced'} 命中缓存")
                # 如果请求的 limit 小于缓存的数量，截取前 limit 个
                if limit < len(cached_data.get("coins", [])):
                    result_data = cached_data.copy()
                    result_data["coins"] = cached_data["coins"][:limit]
                    result_data["count"] = limit
                    return AI500Response(success=True, data=result_data)
                return AI500Response(success=True, data=cached_data)

        # 先加载 CMC 数据增强分析
        await load_cmc_data_for_analyzer(cmc_collector, analyzer)

        if direction == "short":
            coins = await analyzer.get_short_candidates(limit)
        elif direction == "long":
            coins = await analyzer.get_long_candidates(limit)
        elif direction == "all":
            # 返回所有分析结果，不做平衡
            all_analysis = await analyzer.analyze_all()
            coins = sorted(
                all_analysis.values(),
                key=lambda x: (x.direction != Direction.NEUTRAL, x.score),
                reverse=True,
            )[:limit]
        else:
            # 默认使用多空平衡模式（balanced 或 None）
            coins = await analyzer.get_balanced_candidates(limit)

        coin_list = [analysis_to_coin_info(c).model_dump() for c in coins]

        # 统计多空分布
        long_count = sum(1 for c in coins if c.direction == Direction.LONG)
        short_count = sum(1 for c in coins if c.direction == Direction.SHORT)

        return AI500Response(
            success=True,
            data={
                "coins": coin_list,
                "count": len(coin_list),
                "direction": direction or "balanced",
                "long_count": long_count,
                "short_count": short_count,
                "timestamp": int(time.time()),
            },
        )
    except Exception as e:
        logger.error(f"获取 AI500 列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ai500/{symbol}")
async def get_ai500_symbol(
    symbol: str,
    auth: str = Depends(require_auth),
    include: str = Query("price,oi,netflow,ai500", description="逗号分隔的字段集合"),
    collector: UnifiedMarketCollector = Depends(get_collector),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """获取单币 AI500 视图（本地拼装版）。"""
    symbol = normalize_symbol(symbol)
    include_items = [x.strip() for x in include.split(",") if x.strip()]

    await load_cmc_data_for_analyzer(cmc_collector, analyzer)
    all_analysis = await analyzer.analyze_all(include_neutral=True, filter_low_oi=False)
    analysis = all_analysis.get(symbol)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")

    # 调用 fetch_coin_detail 获取币种详情
    include_set = {item.strip() for item in include.split(",") if item.strip()}
    coin_data = await fetch_coin_detail(
        symbol=symbol,
        include_items=include_set,
        collector=collector,
        analyzer=analyzer,
        cmc_collector=cmc_collector,
    )

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "ai500": {
                "score": analysis.score,
                "is_active": analysis.score >= 70 and analysis.direction != Direction.NEUTRAL,
                "direction": analysis.direction.value,
                "confidence": analysis.confidence,
                "reasons": analysis.reasons,
                "tags": analysis.tags,
                "entry_timing": analysis.entry_timing,
                "timing_score": analysis.timing_score,
            },
            "coin": coin_data,
            "analysis": analysis_to_coin_info(analysis).model_dump(),
            "include": include_items,
            "mode": "local_proxy_ai500",
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/ai500/stats")
async def get_ai500_stats(
    auth: str = Depends(require_auth),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """获取本地 AI500 候选池统计。"""
    await load_cmc_data_for_analyzer(cmc_collector, analyzer)
    all_analysis = await analyzer.analyze_all(include_neutral=True, filter_low_oi=False)
    rows = list(all_analysis.values())
    if not rows:
        return {"success": True, "data": {"count": 0, "timestamp": int(time.time())}}

    active = [x for x in rows if x.score >= 70 and x.direction != Direction.NEUTRAL]
    long_count = sum(1 for x in active if x.direction == Direction.LONG)
    short_count = sum(1 for x in active if x.direction == Direction.SHORT)
    scores = [x.score for x in rows]
    active_scores = [x.score for x in active] or [0.0]

    return {
        "success": True,
        "data": {
            "universe_count": len(rows),
            "active_count": len(active),
            "active_ratio": len(active) / len(rows) if rows else 0.0,
            "direction_distribution": {
                "long": long_count,
                "short": short_count,
                "neutral": len(rows) - long_count - short_count,
            },
            "score_stats": {
                "avg": sum(scores) / len(scores),
                "max": max(scores),
                "min": min(scores),
                "active_avg": sum(active_scores) / len(active_scores),
            },
            "mode": "local_proxy_ai500",
            "timestamp": int(time.time()),
        },
    }
