#!/usr/bin/env python3
"""行情数据路由（coin / netflow / price / funding-rate / heatmap）。"""

import logging
import time

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from analysis.coin_analyzer import CoinAnalyzer
from app.auth import require_auth
from app.converters import fetch_coin_detail
from app.dependencies import get_analyzer, get_cmc_collector, get_collector, get_vs_collector_optional
from app.utils import normalize_symbol
from collectors.cmc_collector import CMCCollector
from collectors.market_data_collector import UnifiedMarketCollector
from collectors.valuescan_collector import ValueScanCollector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market_data"])


@router.get("/api/coin/{symbol}")
async def get_coin_data(
    symbol: str,
    auth: str = Depends(require_auth),
    include: str = Query("netflow,oi,price", description="返回数据类型"),
    collector: UnifiedMarketCollector = Depends(get_collector),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
    vs_collector: Optional[ValueScanCollector] = Depends(get_vs_collector_optional),
):
    """获取单个币种综合数据（兼容官方接口，支持多源 OI 与资金流代理）。"""
    symbol = normalize_symbol(symbol)
    include_items = {item.strip() for item in include.split(",") if item.strip()}

    try:
        data = await fetch_coin_detail(
            symbol=symbol,
            include_items=include_items,
            collector=collector,
            analyzer=analyzer,
            cmc_collector=cmc_collector,
            vs_collector=vs_collector,
        )
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取币种数据失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/netflow/top-ranking")
async def get_netflow_top_ranking(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100),
    duration: str = Query("1h", description="时间范围"),
    type: str = Query("proxy", description="proxy/institution/personal"),
    trade: str = Query("all", description="all/future/spot"),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    rows = await collector.get_netflow_ranking(rank_type="top", duration=duration, limit=limit, trade=trade)
    return {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "duration": duration,
            "trade": trade,
            "type": type,
            "mode": "proxy_taker_imbalance",
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/netflow/low-ranking")
async def get_netflow_low_ranking(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100),
    duration: str = Query("1h", description="时间范围"),
    type: str = Query("proxy", description="proxy/institution/personal"),
    trade: str = Query("all", description="all/future/spot"),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    rows = await collector.get_netflow_ranking(rank_type="low", duration=duration, limit=limit, trade=trade)
    return {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "duration": duration,
            "trade": trade,
            "type": type,
            "mode": "proxy_taker_imbalance",
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/price/ranking")
async def get_price_ranking(
    auth: str = Depends(require_auth),
    duration: str = Query("1h", description="时间范围"),
    limit: int = Query(20, ge=1, le=100),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    rows = await collector.get_price_ranking(duration=duration, limit=limit)
    return {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "duration": duration,
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/funding-rate/top")
async def get_top_funding_rates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    rows = await collector.get_funding_rate_ranking(rank_type="top", limit=limit)
    return {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "rank_type": "top",
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/funding-rate/low")
async def get_low_funding_rates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=100),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    rows = await collector.get_funding_rate_ranking(rank_type="low", limit=limit)
    return {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "rank_type": "low",
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/funding-rate/{symbol}")
async def get_symbol_funding_rate(
    symbol: str,
    auth: str = Depends(require_auth),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    symbol = normalize_symbol(symbol)
    rates = await collector.get_all_funding_rates()
    row = rates.get(symbol)
    if not row:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")
    tickers = await collector.get_all_tickers()
    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "funding_rate": row.funding_rate * 100,
            "mark_price": tickers.get(symbol).price if tickers.get(symbol) else 0.0,
            "next_funding_time": row.next_funding_time,
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/heatmap/future/{symbol}")
async def get_future_heatmap(
    symbol: str,
    auth: str = Depends(require_auth),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    symbol = normalize_symbol(symbol)
    row = await collector.get_heatmap(symbol, trade="future")
    if not row:
        raise HTTPException(status_code=404, detail=f"热力图数据不存在: {symbol}")
    return {"success": True, "data": row}


@router.get("/api/heatmap/spot/{symbol}")
async def get_spot_heatmap(
    symbol: str,
    auth: str = Depends(require_auth),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    symbol = normalize_symbol(symbol)
    row = await collector.get_heatmap(symbol, trade="spot")
    if not row:
        raise HTTPException(status_code=404, detail=f"热力图数据不存在: {symbol}")
    return {"success": True, "data": row}


@router.get("/api/heatmap/list")
async def get_heatmap_list(
    auth: str = Depends(require_auth),
    trade: str = Query("future", description="future/spot"),
    limit: int = Query(20, ge=1, le=100),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    rows = await collector.get_heatmap_list(trade=trade, limit=limit)
    return {
        "success": True,
        "data": {
            "rows": rows,
            "count": len(rows),
            "trade": trade,
            "timestamp": int(time.time()),
        },
    }
