#!/usr/bin/env python3
"""数据转换与加载函数。

从 main.py 提取的核心数据转换逻辑，包括：
- analysis_to_coin_info: CoinAnalysis -> CoinInfo 转换
- load_cmc_data_for_analyzer: 加载 CMC 宏观数据到分析器
- fetch_coin_detail: 单币综合数据获取（原 get_coin_data 的核心逻辑）
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException

from analysis.coin_analyzer import CoinAnalyzer, CoinAnalysis, Direction
from collectors.cmc_collector import CMCCollector
from collectors.market_data_collector import UnifiedMarketCollector
from core.cache import APICache, get_cache
from core.config import settings
from app.schemas import CoinInfo

logger = logging.getLogger(__name__)


def analysis_to_coin_info(analysis: CoinAnalysis) -> CoinInfo:
    """将分析结果转换为 CoinInfo

    注意：为了让 Go 后端能识别方向和入场时机信息，将关键标签编码到 tags 中
    标签顺序：
    1. TIMING:xxx - 入场时机（最重要）
    2. DIRECTION:xxx - 推荐方向
    3. VWAP:xxx - VWAP 信号
    4. 其他标签
    """
    # tags 已经在 _add_tags 中处理过了，包含了 TIMING 标签
    tags_with_info = list(analysis.tags) if analysis.tags else []

    # 在 TIMING 标签后面插入 DIRECTION 标签
    direction_tag = f"DIRECTION:{analysis.direction.value.upper()}"
    # 找到 TIMING 标签的位置，在其后插入 DIRECTION
    timing_idx = 0
    for i, tag in enumerate(tags_with_info):
        if tag.startswith("TIMING:"):
            timing_idx = i + 1
            break
    tags_with_info.insert(timing_idx, direction_tag)

    # 如果有 VWAP 信号，在 DIRECTION 后面添加
    if analysis.vwap_signal:
        tags_with_info.insert(timing_idx + 1, f"VWAP:{analysis.vwap_signal}")

    return CoinInfo(
        pair=analysis.symbol,
        score=analysis.score,
        start_time=int(analysis.timestamp),
        start_price=analysis.price,
        last_score=analysis.score,
        max_score=analysis.score,
        max_price=analysis.price,
        increase_percent=analysis.price_change_24h,
        direction=analysis.direction.value,
        confidence=analysis.confidence,
        price=analysis.price,
        price_change_1h=analysis.price_change_1h,
        price_change_24h=analysis.price_change_24h,
        volatility_24h=analysis.volatility_24h,
        oi_change_1h=analysis.oi_change_1h,
        oi_value_usd=analysis.oi_value,  # oi_value 已经是 USDT 价值
        funding_rate=analysis.funding_rate,
        volume_24h=analysis.volume_24h,
        tags=tags_with_info,
        reasons=analysis.reasons,
        # VWAP 相关字段
        vwap_1h=analysis.vwap_1h,
        vwap_4h=analysis.vwap_4h,
        price_vs_vwap_1h=analysis.price_vs_vwap_1h,
        price_vs_vwap_4h=analysis.price_vs_vwap_4h,
        vwap_signal=analysis.vwap_signal if analysis.vwap_signal else None,
        # === 入场时机相关字段 ===
        entry_timing=analysis.entry_timing,
        timing_score=analysis.timing_score,
        pullback_pct=analysis.pullback_pct,
        required_pullback=analysis.required_pullback,
        atr_pct=analysis.atr_pct,
        support_distance=analysis.support_distance,
        resistance_distance=analysis.resistance_distance,
        # === 动态止损建议 ===
        suggested_stop_pct=analysis.suggested_stop_pct,
        suggested_stop_price=analysis.suggested_stop_price,
        volatility_level=analysis.volatility_level,
    )


async def load_cmc_data_for_analyzer(
    cmc_collector: CMCCollector,
    analyzer: CoinAnalyzer,
) -> None:
    """加载 CMC 数据到分析器（安全调用，失败不影响主流程）。

    参数:
        cmc_collector: CMC 宏观数据采集器
        analyzer: 币种分析器
    """
    if not cmc_collector or not analyzer:
        return

    try:
        # 并行获取 CMC 数据（新增 listings 用于市值排名）
        trending_result, gainers_losers_result, listings_result = await asyncio.gather(
            cmc_collector.get_trending(limit=50),
            cmc_collector.get_gainers_losers(limit=50),
            cmc_collector.get_latest_listings(limit=200),  # 获取前200名市值排名
            return_exceptions=True
        )

        # 安全提取数据
        trending_list = []
        gainers_list = []
        losers_list = []
        listings_dict = {}

        if isinstance(trending_result, list):
            trending_list = [
                {"symbol": t.symbol, "trending_score": t.trending_score, "rank": t.cmc_rank}
                for t in trending_result
            ]

        if isinstance(gainers_losers_result, tuple) and len(gainers_losers_result) == 2:
            gainers, losers = gainers_losers_result
            gainers_list = [
                {"symbol": g.symbol, "percent_change_24h": g.percent_change_24h, "rank": g.cmc_rank}
                for g in gainers
            ]
            losers_list = [
                {"symbol": l.symbol, "percent_change_24h": l.percent_change_24h, "rank": l.cmc_rank}
                for l in losers
            ]

        # 处理 listings 数据（用于市值权重计算）
        if isinstance(listings_result, dict):
            for symbol, coin_data in listings_result.items():
                listings_dict[symbol] = {
                    "cmc_rank": coin_data.cmc_rank,
                    "market_cap": coin_data.market_cap,
                }

        if trending_list or gainers_list or losers_list or listings_dict:
            analyzer.set_cmc_data(
                trending=trending_list,
                gainers=gainers_list,
                losers=losers_list,
                listings=listings_dict
            )
            logger.info(
                f"CMC 数据已加载: trending={len(trending_list)}, "
                f"gainers={len(gainers_list)}, losers={len(losers_list)}, "
                f"listings={len(listings_dict)}"
            )
    except Exception as e:
        logger.warning(f"加载 CMC 数据失败（不影响主流程）: {e}")


async def fetch_coin_detail(
    symbol: str,
    include_items: Set[str],
    collector: UnifiedMarketCollector,
    analyzer: CoinAnalyzer,
    cmc_collector: CMCCollector,
) -> Dict[str, Any]:
    """获取单币综合数据（原 get_coin_data 的核心逻辑）。

    参数:
        symbol: 标准化后的交易对名称（如 BTCUSDT）
        include_items: 需要包含的数据集合（如 {"price", "oi", "netflow", "ai500"}）
        collector: 行情采集器
        analyzer: 币种分析器
        cmc_collector: CMC 宏观数据采集器

    返回:
        包含请求数据的字典

    异常:
        HTTPException(404): 币种不存在
        HTTPException(500): 数据获取失败
    """
    cache = get_cache()
    include_key = ",".join(sorted(include_items)) or "default"
    cache_key = cache.get_coin_key(f"{symbol}:{include_key}")
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.debug(f"coin/{symbol} 命中缓存")
        return cached_data

    tickers = await collector.get_all_tickers()
    ticker = tickers.get(symbol)
    if not ticker:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")

    data: Dict[str, Any] = {
        "symbol": symbol,
        "price": ticker.price,
    }

    if "price" in include_items:
        all_price_changes = await collector.calculate_all_price_changes(symbol, ticker.price)
        data["price_change"] = {k: v / 100 for k, v in all_price_changes.items()}

    if "oi" in include_items:
        exchange_oi = await collector.get_exchange_oi_details(symbol)
        if exchange_oi:
            data["oi"] = {}
            for exchange_name, info in exchange_oi.items():
                data["oi"][exchange_name] = {
                    "current_oi": info.get("oi", 0.0),
                    "oi_value": info.get("oi_value", 0.0),
                    "net_long": info.get("net_long", 0.0),
                    "net_short": info.get("net_short", 0.0),
                    "delta": {
                        "1h": {
                            "oi_delta": (
                                info.get("oi", 0.0) * info.get("oi_delta_percent", 0.0) / 100
                            ) if info.get("oi") else 0.0,
                            "oi_delta_value": info.get("oi_delta_value", 0.0),
                            "oi_delta_percent": info.get("oi_delta_percent", 0.0) / 100,
                        }
                    },
                }

    if "netflow" in include_items:
        netflow = await collector.get_flow_proxy(symbol, duration="1h", trade="all")
        future_flow = netflow.get("future_flow", 0.0)
        spot_flow = netflow.get("spot_flow", 0.0)
        total_flow = netflow.get("amount", future_flow + spot_flow)
        data["netflow"] = {
            # 尽量贴近官方字段
            "institution": {
                "1h": total_flow,
                "future": {"1h": future_flow},
                "spot": {"1h": spot_flow},
            },
            "personal": {
                "1h": 0.0,
                "future": {"1h": 0.0},
                "spot": {"1h": 0.0},
            },
            # 本地额外字段，显式告知为代理模式
            "breakdown": {
                "future_flow": future_flow,
                "spot_flow": spot_flow,
                "amount": total_flow,
            },
            "mode": netflow.get("mode", "proxy_taker_imbalance"),
        }

    funding_data = await collector.get_all_funding_rates()
    funding = funding_data.get(symbol)
    if funding:
        data["funding_rate"] = funding.funding_rate

    if "ai500" in include_items:
        await load_cmc_data_for_analyzer(cmc_collector, analyzer)
        all_analysis = await analyzer.analyze_all(include_neutral=True, filter_low_oi=False)
        analysis = all_analysis.get(symbol)
        if analysis:
            data["ai500"] = {
                "score": analysis.score,
                "is_active": analysis.score >= 70 and analysis.direction != Direction.NEUTRAL,
                "direction": analysis.direction.value,
                "confidence": analysis.confidence,
            }

    cache.set(cache_key, data, ttl=settings.cache_ttl_analysis)
    return data
