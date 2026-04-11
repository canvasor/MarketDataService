#!/usr/bin/env python3
"""路由统一注册。"""

from fastapi import FastAPI


def register_routers(app: FastAPI):
    from app.routers import (
        ai500, oi, analysis, sentiment, market_data,
        cmc, strategy, system, cache_admin,
    )
    for module in [system, ai500, oi, market_data, analysis, sentiment, cmc, strategy, cache_admin]:
        app.include_router(module.router)
