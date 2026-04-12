#!/usr/bin/env python3
"""分析策略路由（多空候选 / 闪崩风险 / 高波动 / 早期信号 / 市场概览）。"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from analysis.coin_analyzer import CoinAnalyzer, Direction
from app.auth import require_auth
from app.converters import analysis_to_coin_info, load_cmc_data_for_analyzer
from app.dependencies import get_analyzer, get_cmc_collector
from collectors.cmc_collector import CMCCollector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.get("/api/analysis/short")
async def get_short_candidates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取做空候选币种

    筛选逻辑:
    1. 价格下跌 + OI 增加 = 空头主导
    2. 高资金费率 = 过度做多
    3. 高波动下跌趋势
    """
    try:
        coins = await analyzer.get_short_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "direction": "short",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取做空候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/analysis/long")
async def get_long_candidates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取做多候选币种

    筛选逻辑:
    1. 价格上涨 + OI 增加 = 多头主导
    2. 负资金费率 = 过度做空
    3. 回调后企稳反弹
    """
    try:
        coins = await analyzer.get_long_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "direction": "long",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取做多候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/analysis/flash-crash")
async def get_flash_crash_candidates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
):
    """
    获取闪崩风险币种（适合做空埋伏）

    筛选逻辑:
    1. 高波动 + 下跌趋势
    2. OI 急剧增加（空头在砸盘）
    3. 极端资金费率
    """
    try:
        coins = await analyzer.get_flash_crash_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "type": "flash_crash_risk",
                "timestamp": int(time.time()),
                "description": "这些币种有闪崩风险，适合在反弹时做空埋伏",
            },
        }
    except Exception as e:
        logger.error(f"获取闪崩风险币种失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/analysis/high-volatility")
async def get_high_volatility_coins(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    min_volatility: float = Query(5.0, description="最小波动率(%)"),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取高波动币种

    这些币种波动大，适合:
    - 高频交易
    - 做空埋伏
    - 趋势跟踪
    """
    try:
        coins = await analyzer.get_high_volatility_coins(min_volatility=min_volatility, limit=limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "type": "high_volatility",
                "min_volatility": min_volatility,
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取高波动币种失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/analysis/early-signals")
async def get_early_signal_candidates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
):
    """
    获取早期信号候选币种（基于 VWAP 分析）

    用于提前发现潜在交易机会，在动量确认之前布局：

    VWAP 信号类型:
    - early_long: 价格低于 VWAP 但 OI 增加（资金悄悄进场）
    - early_short: 价格高于 VWAP 且资金费率偏高（可能回调）
    - breakout_long: 价格刚向上突破 VWAP
    - breakout_short: 价格刚向下跌破 VWAP

    适用场景:
    - 提前布局，避免追高追跌
    - 在动量信号确认之前入场
    - 获得更好的入场价格
    """
    try:
        coins = await analyzer.get_early_signal_candidates(limit)

        # 按信号类型分组统计
        signal_counts = {}
        for c in coins:
            signal = c.vwap_signal or "unknown"
            signal_counts[signal] = signal_counts.get(signal, 0) + 1

        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "type": "early_signals",
                "signal_distribution": signal_counts,
                "timestamp": int(time.time()),
                "description": "基于 VWAP 的早期信号，用于提前布局避免追高",
            },
        }
    except Exception as e:
        logger.error(f"获取早期信号候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/analysis/market-overview")
async def get_market_overview(
    auth: str = Depends(require_auth),
    analyzer: CoinAnalyzer = Depends(get_analyzer),
    cmc_collector: CMCCollector = Depends(get_cmc_collector),
):
    """
    获取市场概览（整合 Binance 和全网数据）

    返回:
    - Binance 合约市场的多空分布
    - 全网恐惧贪婪指数（无需 CMC key）
    - CMC 全市场数据（需要 CMC key，可选）
    """
    try:
        # 1. Binance 合约市场分析
        all_analysis = await analyzer.analyze_all()

        total = len(all_analysis)
        long_count = sum(1 for a in all_analysis.values() if a.direction == Direction.LONG)
        short_count = sum(1 for a in all_analysis.values() if a.direction == Direction.SHORT)
        neutral_count = total - long_count - short_count

        # Binance 市场情绪
        if short_count > long_count * 1.5:
            binance_sentiment = "bearish"
            binance_sentiment_desc = "空头主导，做空机会较多"
        elif long_count > short_count * 1.5:
            binance_sentiment = "bullish"
            binance_sentiment_desc = "多头主导，做多机会较多"
        else:
            binance_sentiment = "neutral"
            binance_sentiment_desc = "多空均衡，观望为主"

        high_vol_count = sum(1 for a in all_analysis.values() if a.volatility_24h > 5)
        flash_crash_count = sum(1 for a in all_analysis.values() if "flash_crash_risk" in a.tags)

        # 2. 全网市场情绪（CMC + 恐惧贪婪指数）
        global_sentiment = await cmc_collector.safe_get_market_sentiment()

        return {
            "success": True,
            "data": {
                # Binance 合约市场数据
                "binance": {
                    "total_coins": total,
                    "long_candidates": long_count,
                    "short_candidates": short_count,
                    "neutral": neutral_count,
                    "high_volatility": high_vol_count,
                    "flash_crash_risk": flash_crash_count,
                    "market_sentiment": binance_sentiment,
                    "sentiment_description": binance_sentiment_desc,
                },
                # 全网市场情绪
                "global": global_sentiment,
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            },
        }
    except Exception as e:
        logger.error(f"获取市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
