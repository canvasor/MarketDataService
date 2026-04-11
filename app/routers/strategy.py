#!/usr/bin/env python3
"""策略辅助路由（配对中性模板与上下文）。"""

import logging
import time

from fastapi import APIRouter, Depends, Query

from app.auth import require_auth
from app.dependencies import get_collector
from collectors.market_data_collector import UnifiedMarketCollector
from tools.strategy_tools import (
    BACKTEST_FIELDS,
    PAIR_TEMPLATE,
    build_pair_neutral_context,
    build_universe_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["strategy"])


@router.get("/api/strategy/pair-neutral/template")
async def get_pair_neutral_template(auth: str = Depends(require_auth)):
    return {
        "success": True,
        "data": {
            "template": PAIR_TEMPLATE,
            "backtest_fields": BACKTEST_FIELDS,
            "fixed_universe": build_universe_summary(),
            "timestamp": int(time.time()),
        },
    }


@router.get("/api/strategy/pair-neutral/context")
async def get_pair_neutral_context(
    auth: str = Depends(require_auth),
    symbol_a: str = Query("BTCUSDT", description="腿A"),
    symbol_b: str = Query("ETHUSDT", description="腿B"),
    lookback_bars: int = Query(288, ge=48, le=2000),
    interval: str = Query("15m"),
    collector: UnifiedMarketCollector = Depends(get_collector),
):
    data = await build_pair_neutral_context(
        collector, symbol_a, symbol_b, lookback_bars=lookback_bars, interval=interval,
    )
    return {"success": True, "data": data}
