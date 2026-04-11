#!/usr/bin/env python3
"""Pydantic 响应模型。"""

from typing import Dict, List, Optional

from pydantic import BaseModel


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
