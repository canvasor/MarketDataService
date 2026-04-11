#!/usr/bin/env python3
"""CMC / CoinGecko 宏观数据路由。"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_auth
from app.dependencies import get_cmc_collector
from collectors.cmc_collector import CMCCollector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cmc"])


@router.get("/api/cmc/listings")
async def get_cmc_listings(
    auth: str = Depends(require_auth),
    limit: int = Query(100, ge=1, le=200, description="返回数量"),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取 CMC 市值排名列表

    返回前N名币种的市值、价格、涨跌幅等数据
    """
    if not cmc_collector.is_available:
        raise HTTPException(status_code=503, detail="CoinGecko / CMC 宏观数据源未配置")

    try:
        coins = await cmc_collector.get_latest_listings(limit)

        coin_list = []
        for symbol, coin in coins.items():
            coin_list.append({
                "symbol": symbol,
                "name": coin.name,
                "rank": coin.cmc_rank,
                "price": coin.price,
                "market_cap": coin.market_cap,
                "volume_24h": coin.volume_24h,
                "percent_change_1h": coin.percent_change_1h,
                "percent_change_24h": coin.percent_change_24h,
                "percent_change_7d": coin.percent_change_7d,
                "circulating_supply": coin.circulating_supply,
                "total_supply": coin.total_supply,
            })

        # 按市值排序
        coin_list.sort(key=lambda x: x["rank"])

        return {
            "success": True,
            "data": {
                "coins": coin_list,
                "count": len(coin_list),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取 CMC 列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/cmc/trending")
async def get_cmc_trending(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取 CMC 热门/趋势币种

    返回当前最活跃的币种（按交易量/市值比率排序）
    """
    if not cmc_collector.is_available:
        raise HTTPException(status_code=503, detail="CoinGecko / CMC 宏观数据源未配置")

    try:
        trending = await cmc_collector.get_trending(limit)

        coin_list = []
        for coin in trending:
            coin_list.append({
                "symbol": coin.symbol,
                "name": coin.name,
                "rank": coin.cmc_rank,
                "price": coin.price,
                "percent_change_24h": coin.percent_change_24h,
                "trending_score": coin.trending_score,
            })

        return {
            "success": True,
            "data": {
                "coins": coin_list,
                "count": len(coin_list),
                "type": "trending",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取 CMC 热门币种失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/cmc/gainers-losers")
async def get_cmc_gainers_losers(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    time_period: str = Query("24h", description="时间周期: 1h/24h/7d/30d"),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取 CMC 涨跌幅排行

    返回涨幅最大和跌幅最大的币种
    """
    if not cmc_collector.is_available:
        raise HTTPException(status_code=503, detail="CoinGecko / CMC 宏观数据源未配置")

    try:
        gainers, losers = await cmc_collector.get_gainers_losers(limit, time_period)

        return {
            "success": True,
            "data": {
                "gainers": [
                    {
                        "symbol": c.symbol,
                        "name": c.name,
                        "rank": c.cmc_rank,
                        "price": c.price,
                        "percent_change_24h": c.percent_change_24h,
                    }
                    for c in gainers
                ],
                "losers": [
                    {
                        "symbol": c.symbol,
                        "name": c.name,
                        "rank": c.cmc_rank,
                        "price": c.price,
                        "percent_change_24h": c.percent_change_24h,
                    }
                    for c in losers
                ],
                "time_period": time_period,
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取 CMC 涨跌幅排行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/cmc/market-overview")
async def get_cmc_market_overview(
    auth: str = Depends(require_auth),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取 CMC 全市场概览

    返回全市场总市值、BTC 主导率等宏观指标
    """
    if not cmc_collector.is_available:
        raise HTTPException(status_code=503, detail="CoinGecko / CMC 宏观数据源未配置")

    try:
        overview = await cmc_collector.get_market_overview()

        if not overview:
            raise HTTPException(status_code=503, detail="无法获取市场数据")

        return {
            "success": True,
            "data": {
                "total_market_cap": overview.get("total_market_cap", 0),
                "total_volume_24h": overview.get("total_volume_24h", 0),
                "btc_dominance": overview.get("btc_dominance", 0),
                "eth_dominance": overview.get("eth_dominance", 0),
                "active_cryptocurrencies": overview.get("active_cryptocurrencies", 0),
                "market_cap_change_24h": overview.get("total_market_cap_yesterday_percentage_change", 0),
                "volume_change_24h": overview.get("total_volume_24h_yesterday_percentage_change", 0),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 CMC 市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
