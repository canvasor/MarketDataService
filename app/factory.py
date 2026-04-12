#!/usr/bin/env python3
"""FastAPI 应用工厂。

将 lifespan 与应用创建逻辑从 main.py 抽出，
使 main.py 缩减为不到 10 行的瘦入口。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies import init_services, cleanup_services
from app.exceptions import register_exception_handlers
from app.routers import register_routers
from collectors.market_data_collector import UnifiedMarketCollector
from collectors.cmc_collector import CMCCollector
from collectors.valuescan_collector import ValueScanCollector
from analysis.coin_analyzer import CoinAnalyzer
from core.cache import init_cache
from core.cache_warmer import CacheWarmer
from core.config import settings, validate_runtime_settings
from core.logging_utils import configure_logging
from tools.strategy_tools import parse_fixed_symbols

configure_logging(
    log_dir=settings.log_dir,
    log_filename=settings.log_file,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：初始化 -> yield -> 清理"""

    validate_runtime_settings(settings)
    logger.info("正在启动本地数据服务器...")

    # 初始化缓存
    api_cache = init_cache(default_ttl=settings.cache_warmup_ttl)
    logger.info(f"API 缓存已初始化，TTL: {settings.cache_warmup_ttl}s")

    # 初始化 Binance 采集器
    collector = UnifiedMarketCollector(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        okx_enabled=settings.okx_enabled,
        okx_api_key=settings.okx_api_key,
        okx_api_secret=settings.okx_api_secret,
        okx_api_passphrase=settings.okx_api_passphrase,
        snapshot_file=settings.snapshot_file,
        focus_symbols=parse_fixed_symbols(),
        universe_mode=settings.analysis_universe_mode,
    )
    if settings.binance_api_key:
        logger.info("Binance API key 已配置，使用认证模式（更高限流额度）")
    else:
        logger.warning("Binance API key 未配置，使用 IP 限流模式（较低额度）")

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
        logger.info(f"宏观数据源已配置: {cmc_collector.active_provider}")
    else:
        logger.warning("未配置 CoinGecko Demo / CMC API，市值与全市场概览仅返回免费恐惧贪婪等基础数据")

    # 初始化 ValueScan 主数据源
    vs_collector = None
    if settings.vs_enabled and settings.vs_open_api_key and settings.vs_open_secret_key:
        vs_collector = ValueScanCollector(
            base_url=settings.vs_open_api_base_url or "https://api.valuescan.io/api/open/v1",
            api_key=settings.vs_open_api_key,
            secret_key=settings.vs_open_secret_key,
            budget_tracker=cmc_collector.budget_tracker,
            monthly_point_limit=settings.vs_monthly_point_limit,
            minute_point_limit=settings.vs_minute_point_limit,
            coin_trade_cache_ttl=settings.vs_coin_trade_cache_ttl,
            token_list_cache_ttl=settings.vs_token_list_cache_ttl,
        )
        try:
            count = await vs_collector.refresh_token_map()
            logger.info(f"ValueScan 主数据源已初始化，映射 {count} 个币种")
        except Exception as e:
            logger.warning(f"ValueScan token 映射加载失败（不影响启动）: {e}")
    else:
        logger.info("ValueScan 未配置或已禁用，使用本地分析作为 AI500 数据源")

    # 初始化分析器
    analyzer = CoinAnalyzer(collector)

    # 预加载数据
    try:
        await collector.get_usdt_symbols()
        logger.info("币种列表加载完成")
    except Exception as e:
        logger.error(f"加载币种列表失败: {e}")

    # 初始化并启动缓存预热器
    cache_warmer = None
    if settings.cache_warmup_enabled:
        cache_warmer = CacheWarmer(
            collector=collector,
            analyzer=analyzer,
            cmc_collector=cmc_collector,
            vs_collector=vs_collector,
            cache=api_cache,
            cache_ttl=settings.cache_warmup_ttl,
            ai500_limit=20,
            vs_warmup_interval_minutes=settings.vs_warmup_interval_minutes,
        )
        await cache_warmer.start()
        logger.info("缓存预热器已启动")

    # 注册到全局依赖容器
    init_services(
        collector=collector,
        cmc_collector=cmc_collector,
        analyzer=analyzer,
        api_cache=api_cache,
        cache_warmer=cache_warmer,
        vs_collector=vs_collector,
    )

    logger.info(f"服务器启动完成，监听 {settings.host}:{settings.port}")

    yield

    # ---------- 清理 ----------
    if cache_warmer:
        await cache_warmer.stop()
    if vs_collector:
        await vs_collector.close()
    if collector:
        await collector.close()
    if cmc_collector:
        await cmc_collector.close()

    cleanup_services()
    logger.info("服务器已关闭")


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""

    app = FastAPI(
        title="NOFX Local Data Server",
        description="本地数据服务器，兼容官方 API，提供增强的币种筛选功能",
        version="2.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routers(app)
    register_exception_handlers(app)

    return app
