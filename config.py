#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NOFX 本地数据服务器 - 配置文件

环境变量:
- CMC_PRO_API_ENDPOINT: CoinMarketCap API 端点
- CMC_PRO_API_KEY: CoinMarketCap API 密钥
- BINANCE_API_KEY_READONLY: Binance 只读 API Key
- BINANCE_API_SECRET_READONLY: Binance 只读 API Secret
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """服务器配置"""

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 30007  # 与官方 30006 不同，避免冲突
    debug: bool = False

    # 认证密钥（与官方兼容）
    auth_key: str = "cm_568c67eae410d912c54c"

    # Binance API
    binance_api_key: Optional[str] = None
    binance_api_secret: Optional[str] = None

    # CoinMarketCap API
    cmc_api_endpoint: Optional[str] = None
    cmc_api_key: Optional[str] = None

    # 缓存配置（秒）
    cache_ttl_ticker: int = 5  # 行情数据缓存
    cache_ttl_oi: int = 30  # OI 数据缓存
    cache_ttl_coin_list: int = 300  # 币种列表缓存
    cache_ttl_analysis: int = 60  # 分析结果缓存

    # 缓存预热配置
    cache_warmup_enabled: bool = True  # 是否启用缓存预热
    cache_warmup_ttl: int = 1800  # 预热缓存 TTL（秒），默认 30 分钟

    # 筛选参数
    max_coins: int = 20  # 最多返回币种数
    min_volume_24h: float = 10_000_000  # 最小24h交易量(USDT)
    min_oi_value: float = 5_000_000  # 最小持仓价值(USDT)

    # OI 流动性过滤（与 nofx 后端同步）
    # nofx 后端使用 15M USD 阈值过滤低流动性币种
    min_oi_value_usd: float = 15_000_000  # 最小 OI 价值阈值（USD），低于此值的币种会被过滤

    # 闪崩检测参数
    flash_crash_price_drop: float = -3.0  # 1小时跌幅阈值(%)
    flash_crash_oi_surge: float = 10.0  # OI 增加阈值(%)
    high_volatility_threshold: float = 5.0  # 高波动率阈值(%)

    class Config:
        env_file = ".env"
        case_sensitive = False


def load_settings() -> Settings:
    """加载配置，优先从环境变量读取"""
    settings = Settings()

    # 从环境变量加载 Binance API
    settings.binance_api_key = os.getenv("BINANCE_API_KEY_READONLY")
    settings.binance_api_secret = os.getenv("BINANCE_API_SECRET_READONLY")

    # 从环境变量加载 CMC API
    settings.cmc_api_endpoint = os.getenv("CMC_PRO_API_ENDPOINT")
    settings.cmc_api_key = os.getenv("CMC_PRO_API_KEY")

    return settings


# 全局配置实例
settings = load_settings()
