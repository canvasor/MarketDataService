#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NoFx 官方数据接口与本地 MarketDataService 的字段映射说明。"""

from __future__ import annotations

from typing import Any, Dict, List


NOFX_COMPATIBILITY_MATRIX: List[Dict[str, Any]] = [
    {
        "official_endpoint": "/api/ai500/list",
        "local_endpoint": "/api/ai500/list",
        "support": "native",
        "fields": {
            "pair": "pair",
            "score": "score",
            "start_time": "start_time",
            "start_price": "start_price",
            "increase_percent": "increase_percent",
            "extra_local": ["direction", "confidence", "entry_timing", "timing_score", "vwap_signal"],
        },
        "notes": "本地 score 属于规则+宏观增强综合分，不等于官方专有 AI500 模型。",
    },
    {
        "official_endpoint": "/api/ai500/{symbol}",
        "local_endpoint": "/api/ai500/{symbol}",
        "support": "proxy",
        "fields": {
            "ai500.score": "data.ai500.score",
            "ai500.is_active": "data.ai500.is_active",
            "coin": "data.coin",
            "analysis": "data.analysis",
        },
        "notes": "通过本地分析结果和 /api/coin 聚合拼装，非官方专有因子。",
    },
    {
        "official_endpoint": "/api/ai500/stats",
        "local_endpoint": "/api/ai500/stats",
        "support": "proxy",
        "fields": {
            "active_count": "data.active_count",
            "score_stats": "data.score_stats",
            "direction_distribution": "data.direction_distribution",
        },
        "notes": "统计口径为本地 AI500 候选池，而非官方全市场专有分数。",
    },
    {
        "official_endpoint": "/api/oi/top-ranking",
        "local_endpoint": "/api/oi/top-ranking",
        "support": "native",
        "fields": {
            "symbol": "symbol",
            "current_oi": "current_oi",
            "oi_delta": "oi_delta",
            "oi_delta_percent": "oi_delta_percent",
            "oi_delta_value": "oi_delta_value",
            "price_delta_percent": "price_delta_percent",
        },
        "notes": "Binance 主、Hyperliquid 辅；duration 已支持。",
    },
    {
        "official_endpoint": "/api/netflow/top-ranking",
        "local_endpoint": "/api/netflow/top-ranking",
        "support": "proxy",
        "fields": {
            "amount": "amount",
            "price": "price",
            "mode": "proxy_taker_imbalance",
        },
        "notes": "仅为成交主动买卖不平衡代理，不是真实 institution/personal split。",
    },
    {
        "official_endpoint": "/api/price/ranking",
        "local_endpoint": "/api/price/ranking",
        "support": "native_plus_proxy",
        "fields": {
            "price_delta": "price_delta",
            "price": "price",
            "future_flow": "future_flow",
            "spot_flow": "spot_flow",
            "oi": "oi",
            "oi_delta": "oi_delta",
            "oi_delta_value": "oi_delta_value",
        },
        "notes": "price 与 OI 为原生；flow 为 proxy。",
    },
    {
        "official_endpoint": "/api/coin/{symbol}",
        "local_endpoint": "/api/coin/{symbol}",
        "support": "mixed",
        "fields": {
            "price_change.{duration}": "data.price_change.{duration}",
            "oi.binance": "data.oi.binance",
            "oi.hyperliquid": "data.oi.hyperliquid",
            "netflow.institution.{duration}": "data.netflow.institution.{duration}",
            "netflow.personal.{duration}": "data.netflow.personal.{duration}",
            "ai500.score": "data.ai500.score",
            "ai500.is_active": "data.ai500.is_active",
        },
        "notes": "netflow 为代理字段；额外暴露 breakdown.future/spot 和 mode。",
    },
    {
        "official_endpoint": "/api/funding-rate/top",
        "local_endpoint": "/api/funding-rate/top",
        "support": "native",
        "fields": {
            "funding_rate": "funding_rate",
            "mark_price": "mark_price",
            "next_funding_time": "next_funding_time",
        },
        "notes": "支持 Binance + Hyperliquid 聚合。",
    },
    {
        "official_endpoint": "/api/oi-cap/ranking",
        "local_endpoint": "/api/oi-cap/ranking",
        "support": "native_plus_macro",
        "fields": {
            "oi": "oi",
            "oi_value": "oi_value",
            "net_long": "net_long",
            "net_short": "net_short",
            "market_cap": "market_cap",
        },
        "notes": "market cap 由 CoinGecko/CMC 提供。",
    },
    {
        "official_endpoint": "/api/heatmap/future/{symbol}",
        "local_endpoint": "/api/heatmap/future/{symbol}",
        "support": "native",
        "fields": {
            "bid_volume": "bid_volume",
            "ask_volume": "ask_volume",
            "delta": "delta",
            "delta_history": "delta_history",
            "large_asks": "large_asks",
            "large_bids": "large_bids",
        },
        "notes": "future 优先 Binance futures depth，缺失时 Hyperliquid L2。",
    },
    {
        "official_endpoint": "/api/heatmap/list",
        "local_endpoint": "/api/heatmap/list",
        "support": "native",
        "fields": {"rows": "data.rows"},
        "notes": "trade=future/spot 已支持。",
    },
    {
        "official_endpoint": "/api/ai300/list",
        "local_endpoint": None,
        "support": "gap",
        "fields": {},
        "notes": "官方专有模型，当前不模拟。",
    },
    {
        "official_endpoint": "/api/long-short/list",
        "local_endpoint": None,
        "support": "gap",
        "fields": {},
        "notes": "可基于 Binance taker ratio/LSR 二阶段补齐，但当前未实现。",
    },
    {
        "official_endpoint": "/api/upbit/*",
        "local_endpoint": None,
        "support": "gap",
        "fields": {},
        "notes": "缺 Upbit 专项源。",
    },
    {
        "official_endpoint": "/api/query-rank/list",
        "local_endpoint": None,
        "support": "gap",
        "fields": {},
        "notes": "缺真实 query telemetry。",
    },
]


GAP_CHECKLIST: List[Dict[str, Any]] = [
    {
        "name": "真实 institution / personal 资金流拆分",
        "severity": "high",
        "status": "unavailable_free",
        "suggestion": "保持 proxy_taker_imbalance，策略层不要把它当真实机构流。",
    },
    {
        "name": "AI300 专有模型",
        "severity": "medium",
        "status": "not_implemented",
        "suggestion": "单独做本地 alpha 模型，不要冒充官方 AI300。",
    },
    {
        "name": "Upbit 热榜/净流",
        "severity": "medium",
        "status": "missing_source",
        "suggestion": "二阶段增加 Upbit public market endpoints。",
    },
    {
        "name": "Query Rank",
        "severity": "medium",
        "status": "missing_telemetry",
        "suggestion": "可在本地 UI / strategy layer 统计查询热度。",
    },
    {
        "name": "Bybit/OKX OI 横向对照",
        "severity": "medium",
        "status": "recommended_next",
        "suggestion": "二阶段优先补 Bybit 与 OKX 公共 market endpoints。",
    },
]


def build_mapping_summary() -> Dict[str, Any]:
    native = sum(1 for row in NOFX_COMPATIBILITY_MATRIX if row["support"] == "native")
    proxy = sum(1 for row in NOFX_COMPATIBILITY_MATRIX if row["support"] in {"proxy", "native_plus_proxy", "mixed", "native_plus_macro"})
    gaps = sum(1 for row in NOFX_COMPATIBILITY_MATRIX if row["support"] == "gap")
    return {
        "summary": {
            "native_supported": native,
            "proxy_or_mixed_supported": proxy,
            "gaps": gaps,
        },
        "matrix": NOFX_COMPATIBILITY_MATRIX,
        "gaps": GAP_CHECKLIST,
    }
