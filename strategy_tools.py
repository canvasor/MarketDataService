#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略辅助模块：固定宇宙说明、配对中性上下文、NoFx 策略对接清单。"""

from __future__ import annotations

import math
import statistics
import time
from typing import Any, Dict, List, Optional

from config import settings

PAIR_TEMPLATE = {
    "strategy_id": "btc_eth_pair_neutral_v1",
    "name": "BTC/ETH 配对中性策略",
    "objective": "在低风险、低回报前提下做相对价值回归，信号 15m，执行 3-5m。",
    "entry": {
        "signal_interval": "15m",
        "execution_interval": "5m",
        "beta_lookback_bars": 288,
        "entry_z_abs": 2.0,
        "exit_z_abs": 0.5,
        "stop_z_abs": 3.2,
        "min_correlation": 0.65,
        "max_holding_hours": 12,
    },
    "risk": {
        "per_trade_nav_risk": 0.003,
        "max_gross_leverage": 1.8,
        "max_single_leg_notional_pct": 0.2,
        "skip_if_spread_volatility_extreme": True,
        "skip_if_depth_imbalance_extreme": True,
        "skip_if_funding_divergence_extreme": True,
    },
    "execution": {
        "open_both_legs": True,
        "hedge_by_beta": True,
        "post_only_preferred": True,
        "slippage_guard_bps": 8,
    },
    "notes": [
        "不要 1:1 等金额对冲，优先用滚动 beta 做动态腿比。",
        "资金费率、OI、深度只作为过滤器，不作为单独开仓理由。",
        "AI 在这个框架里更适合做 regime filter，而不是裸方向预测。",
    ],
}

BACKTEST_FIELDS = [
    "timestamp",
    "symbol",
    "close",
    "quote_volume",
    "oi.current",
    "oi.delta_1h",
    "funding_rate",
    "heatmap.delta",
    "future_flow_proxy",
    "spot_flow_proxy",
]

NOFX_ADAPTATION_CHECKLIST = [
    {
        "layer": "前端候选池",
        "nofx_usage": "/api/ai500/list + /api/ai500/{symbol}",
        "local_status": "ready",
        "local_endpoint": "/api/ai500/list, /api/ai500/{symbol}",
        "notes": "已支持固定币池分析，score 为本地综合分。",
    },
    {
        "layer": "单币详情页",
        "nofx_usage": "/api/coin/{symbol}",
        "local_status": "ready_with_proxy",
        "local_endpoint": "/api/coin/{symbol}",
        "notes": "包含 price_change, oi.binance/hyperliquid/okx, netflow 代理, ai500。",
    },
    {
        "layer": "资金费率榜单",
        "nofx_usage": "/api/funding-rate/*",
        "local_status": "ready",
        "local_endpoint": "/api/funding-rate/top, /low, /{symbol}",
        "notes": "Binance+Hyperliquid+OKX 聚合。",
    },
    {
        "layer": "OI 榜单与对照",
        "nofx_usage": "/api/oi/top-ranking, /api/oi-cap/ranking",
        "local_status": "ready",
        "local_endpoint": "/api/oi/top-ranking, /api/oi-cap/ranking, /api/coin/{symbol}",
        "notes": "exchange OI 现含 Binance/Hyperliquid/OKX。",
    },
    {
        "layer": "热力图 / 下单过滤",
        "nofx_usage": "/api/heatmap/*",
        "local_status": "ready",
        "local_endpoint": "/api/heatmap/future/{symbol}, /api/heatmap/list",
        "notes": "优先 Binance，缺失时可回退 Hyperliquid/OKX。",
    },
    {
        "layer": "策略层配对上下文",
        "nofx_usage": "本地扩展",
        "local_status": "ready",
        "local_endpoint": "/api/strategy/pair-neutral/context",
        "notes": "新增 beta/zscore/相关性/资金费率分化/深度过滤字段。",
    },
    {
        "layer": "Long-short ratio / query rank / AI300",
        "nofx_usage": "/api/long-short/*, /api/query-rank/list, /api/ai300/*",
        "local_status": "gap",
        "local_endpoint": None,
        "notes": "暂未原生实现。",
    },
]


def parse_fixed_symbols() -> List[str]:
    return [s.upper().strip() for s in settings.analysis_fixed_symbols.split(",") if s.strip()]


def build_universe_summary() -> Dict[str, Any]:
    return {
        "mode": settings.analysis_universe_mode,
        "symbols": parse_fixed_symbols(),
        "why": [
            "用固定币池可以把免费额度集中在高流动性标的。",
            "也更适合配对、对冲和横向 OI/funding 比较。",
            "对 NoFx Core 自托管场景，固定币池比伪全市场更稳。",
        ],
        "recommendation": {
            "core": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
            "alt_or_event": ["HYPEUSDT", "ZECUSDT"],
            "note": "建议把核心交易池定为 4 个，高波动补充池定为 2 个；先在核心池里找信号，再决定是否放开补充池。",
        },
    }


def _ols_beta(x: List[float], y: List[float]) -> float:
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return 1.0
    mx = statistics.fmean(x)
    my = statistics.fmean(y)
    var_y = sum((v - my) ** 2 for v in y)
    if var_y <= 1e-12:
        return 1.0
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return cov / var_y


def _corr(x: List[float], y: List[float]) -> float:
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return 0.0
    try:
        return statistics.correlation(x, y)
    except Exception:
        return 0.0


def _log_returns(prices: List[float]) -> List[float]:
    out: List[float] = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            out.append(math.log(prices[i] / prices[i - 1]))
    return out


def _zscore(values: List[float]) -> float:
    if len(values) < 10:
        return 0.0
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    if stdev <= 1e-12:
        return 0.0
    return (values[-1] - mean) / stdev


async def build_pair_neutral_context(collector, symbol_a: str, symbol_b: str, lookback_bars: int = 288, interval: str = "15m") -> Dict[str, Any]:
    symbol_a = symbol_a.upper().strip()
    symbol_b = symbol_b.upper().strip()
    k_a, k_b = await collector.get_symbol_klines(symbol_a, interval=interval, limit=lookback_bars), await collector.get_symbol_klines(symbol_b, interval=interval, limit=lookback_bars)
    closes_a = [float(x.get("close") or 0) for x in k_a if float(x.get("close") or 0) > 0]
    closes_b = [float(x.get("close") or 0) for x in k_b if float(x.get("close") or 0) > 0]
    n = min(len(closes_a), len(closes_b))
    closes_a, closes_b = closes_a[-n:], closes_b[-n:]
    ret_a, ret_b = _log_returns(closes_a), _log_returns(closes_b)
    m = min(len(ret_a), len(ret_b))
    ret_a, ret_b = ret_a[-m:], ret_b[-m:]
    beta = _ols_beta(ret_a, ret_b) if m else 1.0
    corr = _corr(ret_a, ret_b) if m else 0.0
    spreads = []
    for pa, pb in zip(closes_a[-m:], closes_b[-m:]):
        if pa > 0 and pb > 0:
            spreads.append(math.log(pa) - beta * math.log(pb))
    z = _zscore(spreads)

    oi_details_a, oi_details_b = await collector.get_exchange_oi_details(symbol_a), await collector.get_exchange_oi_details(symbol_b)
    fundings = await collector.get_all_funding_rates()
    heat_a, heat_b = await collector.get_heatmap(symbol_a, trade="future"), await collector.get_heatmap(symbol_b, trade="future")
    flow_a, flow_b = await collector.get_flow_proxy(symbol_a, duration="1h", trade="all"), await collector.get_flow_proxy(symbol_b, duration="1h", trade="all")

    funding_a = fundings.get(symbol_a).funding_rate if fundings.get(symbol_a) else 0.0
    funding_b = fundings.get(symbol_b).funding_rate if fundings.get(symbol_b) else 0.0

    return {
        "pair": {"long_leg": symbol_a, "short_leg": symbol_b, "interval": interval, "lookback_bars": lookback_bars},
        "stats": {
            "beta": beta,
            "correlation": corr,
            "spread_zscore": z,
            "spread_latest": spreads[-1] if spreads else 0.0,
            "funding_divergence": funding_a - funding_b,
            "depth_delta_a": (heat_a or {}).get("delta", 0.0),
            "depth_delta_b": (heat_b or {}).get("delta", 0.0),
        },
        "legs": {
            symbol_a: {
                "funding_rate": funding_a,
                "oi": oi_details_a,
                "flow_proxy": flow_a,
                "heatmap": heat_a,
            },
            symbol_b: {
                "funding_rate": funding_b,
                "oi": oi_details_b,
                "flow_proxy": flow_b,
                "heatmap": heat_b,
            },
        },
        "decision_hints": {
            "mean_reversion_ready": abs(z) >= PAIR_TEMPLATE["entry"]["entry_z_abs"] and corr >= PAIR_TEMPLATE["entry"]["min_correlation"],
            "prefer_wait": abs(z) < PAIR_TEMPLATE["entry"]["entry_z_abs"],
            "risk_off": abs(z) >= PAIR_TEMPLATE["entry"]["stop_z_abs"] or corr < 0.4,
        },
        "template": PAIR_TEMPLATE,
        "backtest_fields": BACKTEST_FIELDS,
        "timestamp": int(time.time()),
    }
