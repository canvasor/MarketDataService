#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NOFX 本地数据服务器配置。"""

from __future__ import annotations

import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


AUTH_ENV_KEYS = ("NOFXOS_API_KEY", "NOFX_LOCAL_AUTH_KEY")


class Settings(BaseSettings):
    """服务器配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # 基础服务配置
    host: str = "0.0.0.0"
    port: int = 30007
    debug: bool = False

    # 认证配置
    auth_key: str = "cm_568c67eae410d912c54c"
    allow_legacy_public_key: bool = True

    # Binance 只读配置
    binance_api_key: Optional[str] = None
    binance_api_secret: Optional[str] = None

    # Hyperliquid（行情接口本身不需要私钥，但预留给后续账户态功能）
    hyperliquid_enabled: bool = True
    hyperliquid_address: Optional[str] = None
    hyperliquid_private_key: Optional[str] = None
    hyperliquid_dex: str = ""

    # OKX（公共行情接口默认无需认证；认证信息仅为后续私有接口/执行层预留）
    okx_enabled: bool = True
    okx_api_key: Optional[str] = None
    okx_api_secret: Optional[str] = None
    okx_api_passphrase: Optional[str] = None

    # Market-cap / macro 数据源（优先 CoinGecko Demo，其次 CMC）
    market_data_provider: str = "auto"  # auto|coingecko|cmc|none
    coingecko_api_endpoint: str = "https://api.coingecko.com/api/v3"
    coingecko_api_key: Optional[str] = None
    cmc_api_endpoint: Optional[str] = None
    cmc_api_key: Optional[str] = None

    # 免费 API 预算保护（默认按 free/demo 10k 月度、30 rpm 做保守预留）
    provider_usage_file: str = "data/provider_usage.json"
    coingecko_monthly_soft_limit: int = 9500
    coingecko_minute_soft_limit: int = 25
    cmc_monthly_soft_limit: int = 9500
    cmc_minute_soft_limit: int = 25

    # 缓存 TTL（秒）
    cache_ttl_ticker: int = 5
    cache_ttl_oi: int = 30
    cache_ttl_coin_list: int = 300
    cache_ttl_analysis: int = 60
    cache_ttl_macro: int = 300
    cache_ttl_heatmap: int = 15
    cache_ttl_ranking: int = 30

    # 缓存预热配置
    cache_warmup_enabled: bool = True
    cache_warmup_ttl: int = 1800

    # 选币阈值
    max_coins: int = 20
    min_volume_24h: float = 10_000_000
    min_oi_value: float = 5_000_000
    min_oi_value_usd: float = 15_000_000

    # 风险/波动阈值
    flash_crash_price_drop: float = -3.0
    flash_crash_oi_surge: float = 10.0
    high_volatility_threshold: float = 5.0

    # 监控与本地持久化
    snapshot_dir: str = "data"
    snapshot_file: str = "data/provider_snapshots.json"

    # 分析宇宙配置
    analysis_universe_mode: str = "fixed"  # fixed|hybrid|all
    analysis_fixed_symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,HYPEUSDT,ZECUSDT"

    # 兼容性说明
    compatibility_mode: str = "nofx-core"  # nofx-core|nofx-plus



def load_settings() -> Settings:
    """从环境变量加载配置。"""
    settings = Settings()

    settings.binance_api_key = os.getenv("BINANCE_API_KEY_READONLY") or os.getenv("BINANCE_API_KEY")
    settings.binance_api_secret = os.getenv("BINANCE_API_SECRET_READONLY") or os.getenv("BINANCE_API_SECRET")

    settings.cmc_api_endpoint = os.getenv("CMC_PRO_API_ENDPOINT") or settings.cmc_api_endpoint or "https://pro-api.coinmarketcap.com"
    settings.cmc_api_key = os.getenv("CMC_PRO_API_KEY") or settings.cmc_api_key

    settings.coingecko_api_key = os.getenv("COINGECKO_API_KEY") or os.getenv("COINGECKO_DEMO_API_KEY") or settings.coingecko_api_key
    settings.hyperliquid_address = os.getenv("HYPERLIQUID_ADDRESS") or settings.hyperliquid_address
    settings.hyperliquid_private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY") or settings.hyperliquid_private_key

    settings.okx_api_key = os.getenv("OKX_API_KEY_READONLY") or os.getenv("OKX_API_KEY") or settings.okx_api_key
    settings.okx_api_secret = os.getenv("OKX_API_SECRET_READONLY") or os.getenv("OKX_API_SECRET") or settings.okx_api_secret
    settings.okx_api_passphrase = os.getenv("OKX_API_PASSPHRASE_READONLY") or os.getenv("OKX_API_PASSPHRASE") or settings.okx_api_passphrase

    if os.getenv("ANALYSIS_UNIVERSE_MODE"):
        settings.analysis_universe_mode = os.getenv("ANALYSIS_UNIVERSE_MODE", settings.analysis_universe_mode)
    if os.getenv("ANALYSIS_FIXED_SYMBOLS"):
        settings.analysis_fixed_symbols = os.getenv("ANALYSIS_FIXED_SYMBOLS", settings.analysis_fixed_symbols)

    for env_key in AUTH_ENV_KEYS:
        if os.getenv(env_key):
            settings.auth_key = os.getenv(env_key, settings.auth_key)
            break

    return settings


settings = load_settings()
