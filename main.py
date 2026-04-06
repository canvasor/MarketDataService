#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NOFX 本地数据服务器 - 主程序

提供与官方 nofxaios.com API 兼容的接口，同时增加以下功能:
1. 多空分类筛选
2. 闪崩风险识别
3. 高波动币种发现
4. 实时 Binance 数据

启动方式:
    python main.py
    或
    uvicorn main:app --host 0.0.0.0 --port 30007 --reload
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import settings
from market_data_collector import UnifiedMarketCollector as BinanceCollector
from cmc_collector import CMCCollector
from coin_analyzer import CoinAnalyzer, CoinAnalysis, Direction
from cache import APICache, init_cache, get_cache
from cache_warmer import CacheWarmer
from nofx_mapping import build_mapping_summary

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# 全局实例
collector: Optional[BinanceCollector] = None
cmc_collector: Optional[CMCCollector] = None
analyzer: Optional[CoinAnalyzer] = None
cache_warmer: Optional[CacheWarmer] = None
api_cache: Optional[APICache] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global collector, cmc_collector, analyzer, cache_warmer, api_cache

    logger.info("正在启动本地数据服务器...")

    # 初始化缓存
    api_cache = init_cache(default_ttl=settings.cache_warmup_ttl)
    logger.info(f"✓ API 缓存已初始化，TTL: {settings.cache_warmup_ttl}s")

    # 初始化 Binance 采集器
    collector = BinanceCollector(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        hyperliquid_enabled=settings.hyperliquid_enabled,
        hyperliquid_dex=settings.hyperliquid_dex,
        snapshot_file=settings.snapshot_file,
    )

    # 初始化宏观数据采集器（优先 CoinGecko Demo，其次 CMC）
    cmc_collector = CMCCollector(
        api_endpoint=settings.cmc_api_endpoint,
        api_key=settings.cmc_api_key,
        coingecko_api_endpoint=settings.coingecko_api_endpoint,
        coingecko_api_key=settings.coingecko_api_key,
        provider=settings.market_data_provider,
        usage_storage_path=settings.provider_usage_file,
        coingecko_monthly_soft_limit=settings.coingecko_monthly_soft_limit,
        coingecko_minute_soft_limit=settings.coingecko_minute_soft_limit,
        cmc_monthly_soft_limit=settings.cmc_monthly_soft_limit,
        cmc_minute_soft_limit=settings.cmc_minute_soft_limit,
    )
    if cmc_collector.is_available:
        logger.info(f"✓ 宏观数据源已配置: {cmc_collector.active_provider}")
    else:
        logger.warning("⚠ 未配置 CoinGecko Demo / CMC API，市值与全市场概览仅返回免费恐惧贪婪等基础数据")

    # 初始化分析器
    analyzer = CoinAnalyzer(collector)

    # 预加载数据
    try:
        await collector.get_usdt_symbols()
        logger.info("✓ 币种列表加载完成")
    except Exception as e:
        logger.error(f"加载币种列表失败: {e}")

    # 初始化并启动缓存预热器
    if settings.cache_warmup_enabled:
        cache_warmer = CacheWarmer(
            collector=collector,
            analyzer=analyzer,
            cmc_collector=cmc_collector,
            cache=api_cache,
            cache_ttl=settings.cache_warmup_ttl,
            ai500_limit=20
        )
        await cache_warmer.start()
        logger.info("✓ 缓存预热器已启动")

    logger.info(f"✓ 服务器启动完成，监听 {settings.host}:{settings.port}")

    yield

    # 清理
    if cache_warmer:
        await cache_warmer.stop()
    if collector:
        await collector.close()
    if cmc_collector:
        await cmc_collector.close()
    logger.info("服务器已关闭")


app = FastAPI(
    title="NOFX Local Data Server",
    description="本地数据服务器，兼容官方 API，提供增强的币种筛选功能",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 响应模型 ====================

class CoinInfo(BaseModel):
    """币种信息（兼容 AI500 格式）"""
    pair: str
    score: float
    start_time: int = 0
    start_price: float = 0
    last_score: float = 0
    max_score: float = 0
    max_price: float = 0
    increase_percent: float = 0

    # 扩展字段
    direction: Optional[str] = None
    confidence: Optional[float] = None
    price: Optional[float] = None
    price_change_1h: Optional[float] = None
    price_change_24h: Optional[float] = None
    volatility_24h: Optional[float] = None
    oi_change_1h: Optional[float] = None
    oi_value_usd: Optional[float] = None  # OI 价值（USD），用于验证流动性
    funding_rate: Optional[float] = None
    volume_24h: Optional[float] = None
    tags: Optional[List[str]] = None
    reasons: Optional[List[str]] = None

    # VWAP 相关字段
    vwap_1h: Optional[float] = None
    vwap_4h: Optional[float] = None
    price_vs_vwap_1h: Optional[float] = None
    price_vs_vwap_4h: Optional[float] = None
    vwap_signal: Optional[str] = None

    # === 入场时机相关字段（反追高核心）===
    entry_timing: Optional[str] = None          # "optimal" | "wait_pullback" | "chasing" | "extended"
    timing_score: Optional[float] = None        # 入场时机评分 0-100
    pullback_pct: Optional[float] = None        # 实际回调/反弹幅度
    required_pullback: Optional[float] = None   # 建议回调幅度（基于 ATR）
    atr_pct: Optional[float] = None             # ATR 占价格百分比（波动性）
    support_distance: Optional[float] = None    # 距支撑位距离 (%)
    resistance_distance: Optional[float] = None # 距阻力位距离 (%)

    # === 动态止损建议 ===
    suggested_stop_pct: Optional[float] = None    # 建议止损幅度 (%)
    suggested_stop_price: Optional[float] = None  # 建议止损价格
    volatility_level: Optional[str] = None        # 波动性级别: "low" / "medium" / "high" / "extreme"



class AI500Response(BaseModel):
    """AI500 接口响应"""
    success: bool
    data: Dict


class OIPosition(BaseModel):
    """OI 持仓数据"""
    rank: int
    symbol: str
    current_oi: float
    oi_delta: float
    oi_delta_percent: float
    oi_delta_value: float
    price_delta_percent: float
    net_long: float = 0
    net_short: float = 0


class OIRankingResponse(BaseModel):
    """OI 排行响应"""
    success: bool = True
    code: int = 0
    data: Dict


# ==================== 辅助函数 ====================

def verify_auth(auth: str) -> bool:
    """验证认证密钥"""
    return auth == settings.auth_key


def normalize_symbol(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    return symbol


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


async def load_cmc_data_for_analyzer():
    """加载 CMC 数据到分析器（安全调用，失败不影响主流程）"""
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
            trending_list = [{"symbol": t.symbol, "trending_score": t.trending_score, "rank": t.cmc_rank} for t in trending_result]

        if isinstance(gainers_losers_result, tuple) and len(gainers_losers_result) == 2:
            gainers, losers = gainers_losers_result
            gainers_list = [{"symbol": g.symbol, "percent_change_24h": g.percent_change_24h, "rank": g.cmc_rank} for g in gainers]
            losers_list = [{"symbol": l.symbol, "percent_change_24h": l.percent_change_24h, "rank": l.cmc_rank} for l in losers]

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
            logger.info(f"CMC 数据已加载: trending={len(trending_list)}, gainers={len(gainers_list)}, losers={len(losers_list)}, listings={len(listings_dict)}")
    except Exception as e:
        logger.warning(f"加载 CMC 数据失败（不影响主流程）: {e}")


# ==================== API 接口 ====================

@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "NOFX Local Data Server",
        "version": "2.1.0",
        "status": "running",
        "compatibility_mode": settings.compatibility_mode,
        "providers": {
            "binance": True,
            "hyperliquid": settings.hyperliquid_enabled,
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
        },
    }


@app.get("/api/ai500/list", response_model=AI500Response)
async def get_ai500_list(
    auth: str = Query(..., description="认证密钥"),
    direction: Optional[str] = Query(None, description="筛选方向: long/short/balanced/all"),
    limit: int = Query(20, ge=1, le=100, description="返回数量")
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
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
        await load_cmc_data_for_analyzer()

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
                reverse=True
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
                "timestamp": int(time.time())
            }
        )
    except Exception as e:
        logger.error(f"获取 AI500 列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@app.get("/api/ai500/{symbol}")
async def get_ai500_symbol(
    symbol: str,
    auth: str = Query(..., description="认证密钥"),
    include: str = Query("price,oi,netflow,ai500", description="逗号分隔的字段集合"),
):
    """获取单币 AI500 视图（本地拼装版）。"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    symbol = normalize_symbol(symbol)
    include_items = [x.strip() for x in include.split(",") if x.strip()]

    await load_cmc_data_for_analyzer()
    all_analysis = await analyzer.analyze_all(include_neutral=True, filter_low_oi=False)
    analysis = all_analysis.get(symbol)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")

    coin_resp = await get_coin(symbol=symbol, auth=auth, include=include)
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
            "coin": coin_resp.get("data", {}),
            "analysis": analysis_to_coin_info(analysis).model_dump(),
            "include": include_items,
            "mode": "local_proxy_ai500",
            "timestamp": int(time.time()),
        }
    }


@app.get("/api/ai500/stats")
async def get_ai500_stats(auth: str = Query(..., description="认证密钥")):
    """获取本地 AI500 候选池统计。"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    await load_cmc_data_for_analyzer()
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
        }
    }

@app.get("/api/oi/top-ranking", response_model=OIRankingResponse)
async def get_oi_top_ranking(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    duration: str = Query("1h", description="时间范围: 1m/5m/15m/30m/1h/4h/8h/12h/24h")
):
    """获取 OI 持仓增加排行（兼容官方接口，支持缓存）"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                "net_short": 0
            })

        duration_map = {
            "1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
            "1h": "1小时", "4h": "4小时", "8h": "8小时", "12h": "12小时",
            "24h": "24小时", "1d": "1天", "2d": "2天", "3d": "3天"
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
                "limit": limit
            }
        )
    except Exception as e:
        logger.error(f"获取 OI Top 排行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/oi/low-ranking", response_model=OIRankingResponse)
async def get_oi_low_ranking(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    duration: str = Query("1h", description="时间范围")
):
    """获取 OI 持仓减少排行（兼容官方接口）"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                "net_short": 0
            })

        duration_map = {
            "1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟",
            "1h": "1小时", "4h": "4小时", "8h": "8小时", "12h": "12小时",
            "24h": "24小时", "1d": "1天", "2d": "2天", "3d": "3天"
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
                "limit": limit
            }
        )
    except Exception as e:
        logger.error(f"获取 OI Low 排行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/oi/top", response_model=OIRankingResponse)
async def get_oi_top(auth: str = Query(..., description="认证密钥")):
    """获取 OI Top 20（固定参数，兼容官方接口，支持缓存）"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    # 尝试从缓存获取
    cache = get_cache()
    cached_data = cache.get(APICache.KEY_OI_TOP)
    if cached_data:
        logger.debug("oi/top 命中缓存")
        return OIRankingResponse(success=True, code=0, data=cached_data)

    return await get_oi_top_ranking(auth=auth, limit=20, duration="1h")


@app.get("/api/coin/{symbol}")
async def get_coin_data(
    symbol: str,
    auth: str = Query(..., description="认证密钥"),
    include: str = Query("netflow,oi,price", description="返回数据类型")
):
    """获取单个币种综合数据（兼容官方接口，支持多源 OI 与资金流代理）。"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    symbol = normalize_symbol(symbol)

    cache = get_cache()
    include_items = {item.strip() for item in include.split(",") if item.strip()}
    include_key = ",".join(sorted(include_items)) or "default"
    cache_key = cache.get_coin_key(f"{symbol}:{include_key}")
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.debug(f"coin/{symbol} 命中缓存")
        return {"success": True, "data": cached_data}

    try:
        tickers = await collector.get_all_tickers()
        ticker = tickers.get(symbol)
        if not ticker:
            raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")

        result = {
            "success": True,
            "data": {
                "symbol": symbol,
                "price": ticker.price,
            },
        }

        if "price" in include_items:
            all_price_changes = await collector.calculate_all_price_changes(symbol, ticker.price)
            result["data"]["price_change"] = {k: v / 100 for k, v in all_price_changes.items()}

        if "oi" in include_items:
            exchange_oi = await collector.get_exchange_oi_details(symbol)
            if exchange_oi:
                result["data"]["oi"] = {}
                for exchange_name, info in exchange_oi.items():
                    result["data"]["oi"][exchange_name] = {
                        "current_oi": info.get("oi", 0.0),
                        "oi_value": info.get("oi_value", 0.0),
                        "net_long": info.get("net_long", 0.0),
                        "net_short": info.get("net_short", 0.0),
                        "delta": {
                            "1h": {
                                "oi_delta": (info.get("oi", 0.0) * info.get("oi_delta_percent", 0.0) / 100) if info.get("oi") else 0.0,
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
            result["data"]["netflow"] = {
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
            result["data"]["funding_rate"] = funding.funding_rate

        if "ai500" in include_items:
            await load_cmc_data_for_analyzer()
            all_analysis = await analyzer.analyze_all(include_neutral=True, filter_low_oi=False)
            analysis = all_analysis.get(symbol)
            if analysis:
                result["data"]["ai500"] = {
                    "score": analysis.score,
                    "is_active": analysis.score >= 70 and analysis.direction != Direction.NEUTRAL,
                    "direction": analysis.direction.value,
                    "confidence": analysis.confidence,
                }

        cache.set(cache_key, result["data"], ttl=settings.cache_ttl_analysis)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取币种数据失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 增强接口 ====================

@app.get("/api/analysis/short")
async def get_short_candidates(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量")
):
    """
    获取做空候选币种

    筛选逻辑:
    1. 价格下跌 + OI 增加 = 空头主导
    2. 高资金费率 = 过度做多
    3. 高波动下跌趋势
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    try:
        coins = await analyzer.get_short_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "direction": "short",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取做空候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/long")
async def get_long_candidates(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量")
):
    """
    获取做多候选币种

    筛选逻辑:
    1. 价格上涨 + OI 增加 = 多头主导
    2. 负资金费率 = 过度做空
    3. 回调后企稳反弹
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    try:
        coins = await analyzer.get_long_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "direction": "long",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取做多候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/flash-crash")
async def get_flash_crash_candidates(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量")
):
    """
    获取闪崩风险币种（适合做空埋伏）

    筛选逻辑:
    1. 高波动 + 下跌趋势
    2. OI 急剧增加（空头在砸盘）
    3. 极端资金费率
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    try:
        coins = await analyzer.get_flash_crash_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "type": "flash_crash_risk",
                "timestamp": int(time.time()),
                "description": "这些币种有闪崩风险，适合在反弹时做空埋伏"
            }
        }
    except Exception as e:
        logger.error(f"获取闪崩风险币种失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/high-volatility")
async def get_high_volatility_coins(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    min_volatility: float = Query(5.0, description="最小波动率(%)")
):
    """
    获取高波动币种

    这些币种波动大，适合:
    - 高频交易
    - 做空埋伏
    - 趋势跟踪
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    try:
        coins = await analyzer.get_high_volatility_coins(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "type": "high_volatility",
                "min_volatility": min_volatility,
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取高波动币种失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/early-signals")
async def get_early_signal_candidates(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量")
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
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                "description": "基于 VWAP 的早期信号，用于提前布局避免追高"
            }
        }
    except Exception as e:
        logger.error(f"获取早期信号候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/market-overview")
async def get_market_overview(auth: str = Query(..., description="认证密钥")):
    """
    获取市场概览（整合 Binance 和全网数据）

    返回:
    - Binance 合约市场的多空分布
    - 全网恐惧贪婪指数（无需 CMC key）
    - CMC 全市场数据（需要 CMC key，可选）
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                    "sentiment_description": binance_sentiment_desc
                },
                # 全网市场情绪
                "global": global_sentiment,
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sentiment/fear-greed")
async def get_fear_greed(
    auth: str = Query(..., description="认证密钥"),
    history: int = Query(0, ge=0, le=30, description="历史天数（0=仅当前）")
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
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    try:
        result = {
            "success": True,
            "data": {
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }

        # 获取当前指数
        current = await cmc_collector.get_fear_greed_index()
        if current:
            result["data"]["current"] = {
                "value": current.value,
                "classification": current.value_classification,
                "timestamp": current.timestamp
            }
        else:
            result["data"]["current"] = None
            result["data"]["error"] = "无法获取恐惧贪婪指数"

        # 获取历史数据
        if history > 0:
            history_data = await cmc_collector.get_fear_greed_history(history)
            result["data"]["history"] = history_data

        return result

    except Exception as e:
        logger.error(f"获取恐惧贪婪指数失败: {e}")
        # 返回错误但不抛异常，保持接口可用
        return {
            "success": False,
            "data": {
                "error": str(e),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }


@app.get("/api/sentiment/market")
async def get_market_sentiment(auth: str = Query(..., description="认证密钥")):
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
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    try:
        sentiment = await cmc_collector.safe_get_market_sentiment()
        return {
            "success": True,
            "data": sentiment
        }
    except Exception as e:
        logger.error(f"获取市场情绪失败: {e}")
        return {
            "success": False,
            "data": {
                "available": False,
                "error": str(e),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }


@app.get("/api/netflow/top-ranking")
async def get_netflow_top_ranking(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100),
    duration: str = Query("1h", description="时间范围"),
    type: str = Query("proxy", description="proxy/institution/personal"),
    trade: str = Query("all", description="all/future/spot"),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    rows = await collector.get_netflow_ranking(rank_type="top", duration=duration, limit=limit, trade=trade)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "duration": duration, "trade": trade, "type": type, "mode": "proxy_taker_imbalance", "timestamp": int(time.time())}}


@app.get("/api/netflow/low-ranking")
async def get_netflow_low_ranking(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100),
    duration: str = Query("1h", description="时间范围"),
    type: str = Query("proxy", description="proxy/institution/personal"),
    trade: str = Query("all", description="all/future/spot"),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    rows = await collector.get_netflow_ranking(rank_type="low", duration=duration, limit=limit, trade=trade)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "duration": duration, "trade": trade, "type": type, "mode": "proxy_taker_imbalance", "timestamp": int(time.time())}}


@app.get("/api/price/ranking")
async def get_price_ranking(
    auth: str = Query(..., description="认证密钥"),
    duration: str = Query("1h", description="时间范围"),
    limit: int = Query(20, ge=1, le=100),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    rows = await collector.get_price_ranking(duration=duration, limit=limit)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "duration": duration, "timestamp": int(time.time())}}


@app.get("/api/funding-rate/top")
async def get_top_funding_rates(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    rows = await collector.get_funding_rate_ranking(rank_type="top", limit=limit)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "rank_type": "top", "timestamp": int(time.time())}}


@app.get("/api/funding-rate/low")
async def get_low_funding_rates(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    rows = await collector.get_funding_rate_ranking(rank_type="low", limit=limit)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "rank_type": "low", "timestamp": int(time.time())}}


@app.get("/api/funding-rate/{symbol}")
async def get_symbol_funding_rate(symbol: str, auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    symbol = normalize_symbol(symbol)
    rates = await collector.get_all_funding_rates()
    row = rates.get(symbol)
    if not row:
        raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")
    tickers = await collector.get_all_tickers()
    return {"success": True, "data": {"symbol": symbol, "funding_rate": row.funding_rate * 100, "mark_price": tickers.get(symbol).price if tickers.get(symbol) else 0.0, "next_funding_time": row.next_funding_time, "timestamp": int(time.time())}}


@app.get("/api/oi-cap/ranking")
async def get_oi_cap_ranking(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=100),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    listings = await cmc_collector.get_latest_listings(300)
    lookup = {k: {"market_cap": v.market_cap, "cmc_rank": v.cmc_rank} for k, v in listings.items()}
    rows = await collector.get_oi_cap_ranking(market_cap_lookup=lookup, limit=limit)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "timestamp": int(time.time()), "market_cap_provider": cmc_collector.active_provider}}


@app.get("/api/heatmap/future/{symbol}")
async def get_future_heatmap(symbol: str, auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    symbol = normalize_symbol(symbol)
    row = await collector.get_heatmap(symbol, trade="future")
    if not row:
        raise HTTPException(status_code=404, detail=f"热力图数据不存在: {symbol}")
    return {"success": True, "data": row}


@app.get("/api/heatmap/spot/{symbol}")
async def get_spot_heatmap(symbol: str, auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    symbol = normalize_symbol(symbol)
    row = await collector.get_heatmap(symbol, trade="spot")
    if not row:
        raise HTTPException(status_code=404, detail=f"热力图数据不存在: {symbol}")
    return {"success": True, "data": row}


@app.get("/api/heatmap/list")
async def get_heatmap_list(
    auth: str = Query(..., description="认证密钥"),
    trade: str = Query("future", description="future/spot"),
    limit: int = Query(20, ge=1, le=100),
):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    rows = await collector.get_heatmap_list(trade=trade, limit=limit)
    return {"success": True, "data": {"rows": rows, "count": len(rows), "trade": trade, "timestamp": int(time.time())}}


@app.get("/api/system/status")
async def get_system_status(auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    status = await collector.get_system_status()
    return {"success": True, "data": status}


@app.get("/api/system/capabilities")
async def get_system_capabilities(auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    return {
        "success": True,
        "data": {
            "core_supported": [
                "ai500", "oi_ranking", "coin", "price_ranking", "funding_rate", "oi_cap_ranking", "heatmap", "sentiment"
            ],
            "proxy_supported": [
                "netflow_top_ranking", "netflow_low_ranking", "coin.netflow"
            ],
            "not_fully_supported": [
                "institution_vs_personal_true_split", "upbit_specific_endpoints", "query_rank", "ai300_proprietary_signal"
            ],
            "providers": {
                "market_cap_provider": cmc_collector.active_provider,
                "configured_macro_providers": cmc_collector.configured_providers,
                "hyperliquid_enabled": settings.hyperliquid_enabled,
            },
            "compatibility_summary": build_mapping_summary()["summary"],
            "timestamp": int(time.time()),
        }
    }




@app.get("/api/system/provider-usage")
async def get_provider_usage(auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    return {"success": True, "data": await cmc_collector.get_provider_usage()}


@app.get("/api/system/nofx-compatibility")
async def get_nofx_compatibility(auth: str = Query(..., description="认证密钥")):
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")
    data = build_mapping_summary()
    data["timestamp"] = int(time.time())
    return {"success": True, "data": data}


@app.get("/health")
async def health_check():
    """健康检查"""
    provider_status = collector.get_provider_status() if collector and hasattr(collector, "get_provider_status") else {}
    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "providers": provider_status,
        "coingecko_api": settings.coingecko_api_key is not None,
        "cmc_api": settings.cmc_api_key is not None,
    }


@app.get("/api/cache/status")
async def get_cache_status(auth: str = Query(..., description="认证密钥")):
    """
    获取缓存状态

    返回:
    - 缓存命中率
    - 缓存条目数量
    - 上次预热时间
    - 预热器运行状态
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    cache = get_cache()
    stats = cache.get_stats()
    entries = cache.list_entries()

    result = {
        "success": True,
        "data": {
            "enabled": settings.cache_warmup_enabled,
            "ttl": settings.cache_warmup_ttl,
            "stats": stats,
            "entries": entries,
            "warmer": {
                "running": cache_warmer.is_running() if cache_warmer else False,
                "last_warmup": cache_warmer.get_last_warmup_time() if cache_warmer else 0
            },
            "timestamp": int(time.time())
        }
    }

    return result


@app.post("/api/cache/warmup")
async def trigger_warmup(auth: str = Query(..., description="认证密钥")):
    """手动触发缓存预热"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    if not cache_warmer:
        raise HTTPException(status_code=503, detail="缓存预热器未启用")

    try:
        result = await cache_warmer.warmup()
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"手动预热失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/cache/clear")
async def clear_cache(auth: str = Query(..., description="认证密钥")):
    """清空缓存"""
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

    cache = get_cache()
    cache.clear()

    return {
        "success": True,
        "message": "缓存已清空"
    }


# ==================== CMC 接口 ====================

@app.get("/api/cmc/listings")
async def get_cmc_listings(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(100, ge=1, le=200, description="返回数量")
):
    """
    获取 CMC 市值排名列表

    返回前N名币种的市值、价格、涨跌幅等数据
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                "total_supply": coin.total_supply
            })

        # 按市值排序
        coin_list.sort(key=lambda x: x["rank"])

        return {
            "success": True,
            "data": {
                "coins": coin_list,
                "count": len(coin_list),
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取 CMC 列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cmc/trending")
async def get_cmc_trending(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量")
):
    """
    获取 CMC 热门/趋势币种

    返回当前最活跃的币种（按交易量/市值比率排序）
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                "trending_score": coin.trending_score
            })

        return {
            "success": True,
            "data": {
                "coins": coin_list,
                "count": len(coin_list),
                "type": "trending",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取 CMC 热门币种失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cmc/gainers-losers")
async def get_cmc_gainers_losers(
    auth: str = Query(..., description="认证密钥"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    time_period: str = Query("24h", description="时间周期: 1h/24h/7d/30d")
):
    """
    获取 CMC 涨跌幅排行

    返回涨幅最大和跌幅最大的币种
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                        "percent_change_24h": c.percent_change_24h
                    } for c in gainers
                ],
                "losers": [
                    {
                        "symbol": c.symbol,
                        "name": c.name,
                        "rank": c.cmc_rank,
                        "price": c.price,
                        "percent_change_24h": c.percent_change_24h
                    } for c in losers
                ],
                "time_period": time_period,
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time())
            }
        }
    except Exception as e:
        logger.error(f"获取 CMC 涨跌幅排行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cmc/market-overview")
async def get_cmc_market_overview(auth: str = Query(..., description="认证密钥")):
    """
    获取 CMC 全市场概览

    返回全市场总市值、BTC 主导率等宏观指标
    """
    if not verify_auth(auth):
        raise HTTPException(status_code=401, detail="认证失败")

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
                "timestamp": int(time.time())
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 CMC 市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
