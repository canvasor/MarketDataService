# Phase 1 架构重构实施计划：目录骨架 + 路由拆分

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 main.py 1,783 行代码拆分为分层目录结构，main.py 缩减为 ~15 行瘦入口。

**Architecture:** 按职责分层——core/（基础设施）、collectors/（数据采集）、analysis/（分析）、tools/（策略工具）、app/（FastAPI 应用层含 routers/）、tests/（测试）。所有源码从根目录移入对应子包，更新 import 路径，保持 API 完全兼容。

**Tech Stack:** Python 3, FastAPI, Pydantic, aiohttp, uvicorn

**Spec:** `docs/superpowers/specs/2026-04-11-architecture-restructure-design.md`

---

## File Structure

### 新建文件

| 文件 | 职责 |
|------|------|
| `core/__init__.py` | core 包初始化 |
| `collectors/__init__.py` | 重导出收集器类 |
| `analysis/__init__.py` | 重导出 CoinAnalyzer 等 |
| `tools/__init__.py` | tools 包初始化 |
| `tests/__init__.py` | tests 包初始化 |
| `app/__init__.py` | 导出 `create_app()` |
| `app/routers/__init__.py` | `register_routers()` 统一注册 |
| `app/exceptions.py` | ServiceError 异常类 + 全局处理器 |
| `app/auth.py` | verify_auth, require_auth, get_auth_source, build_auth_metadata |
| `app/schemas.py` | CoinInfo, AI500Response, OIPosition, OIRankingResponse |
| `app/utils.py` | normalize_symbol (修复递归 bug) |
| `app/dependencies.py` | 全局实例管理 + FastAPI Depends |
| `app/converters.py` | analysis_to_coin_info, load_cmc_data_for_analyzer, fetch_coin_data |
| `app/factory.py` | create_app() + lifespan() |
| `app/routers/system.py` | 8 个端点: /, /health, /api/system/* |
| `app/routers/ai500.py` | 3 个端点: /api/ai500/* |
| `app/routers/oi.py` | 4 个端点: /api/oi/*, /api/oi-cap/* |
| `app/routers/market_data.py` | 10 个端点: /api/coin/*, /api/netflow/*, /api/price/*, /api/funding-rate/*, /api/heatmap/* |
| `app/routers/analysis.py` | 6 个端点: /api/analysis/* |
| `app/routers/sentiment.py` | 2 个端点: /api/sentiment/* |
| `app/routers/cmc.py` | 4 个端点: /api/cmc/* |
| `app/routers/strategy.py` | 2 个端点: /api/strategy/* |
| `app/routers/cache_admin.py` | 3 个端点: /api/cache/* |

### 移动文件（内部 import 需更新）

| 源 | 目标 |
|----|------|
| `config.py` | `core/config.py` |
| `cache.py` | `core/cache.py` |
| `cache_warmer.py` | `core/cache_warmer.py` |
| `logging_utils.py` | `core/logging_utils.py` |
| `provider_budget.py` | `core/provider_budget.py` |
| `binance_collector.py` | `collectors/binance_collector.py` |
| `market_data_collector.py` | `collectors/market_data_collector.py` |
| `cmc_collector.py` | `collectors/cmc_collector.py` |
| `hyperliquid_collector.py` | `collectors/hyperliquid_collector.py` |
| `okx_collector.py` | `collectors/okx_collector.py` |
| `coin_analyzer.py` | `analysis/coin_analyzer.py` |
| `strategy_tools.py` | `tools/strategy_tools.py` |
| `nofx_mapping.py` | `tools/nofx_mapping.py` |
| `test_api.py` | `tests/test_api.py` |
| `test_binance_collector.py` | `tests/test_binance_collector.py` |
| `test_cache.py` | `tests/test_cache.py` |
| `test_cache_warmer.py` | `tests/test_cache_warmer.py` |
| `test_cmc_collector.py` | `tests/test_cmc_collector.py` |
| `test_coin_analyzer.py` | `tests/test_coin_analyzer.py` |
| `test_config.py` | `tests/test_config.py` |
| `test_logging_utils.py` | `tests/test_logging_utils.py` |
| `test_market_data_collector.py` | `tests/test_market_data_collector.py` |
| `test_okx_collector.py` | `tests/test_okx_collector.py` |
| `test_provider_budget.py` | `tests/test_provider_budget.py` |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `main.py` | 替换为瘦入口（~15行） |

### 删除（由移动操作隐含）

重构完成验证通过后，删除根目录的旧 .py 文件（main.py 保留为瘦入口）。

---

## Task 1: 创建目录骨架

**Files:**
- Create: `core/__init__.py`
- Create: `collectors/__init__.py`
- Create: `analysis/__init__.py`
- Create: `tools/__init__.py`
- Create: `tests/__init__.py`
- Create: `app/__init__.py`
- Create: `app/routers/__init__.py`

- [ ] **Step 1: 创建所有包目录和 `__init__.py`**

```bash
mkdir -p core collectors analysis tools tests app/routers
```

```python
# core/__init__.py
```

```python
# collectors/__init__.py
```

```python
# analysis/__init__.py
```

```python
# tools/__init__.py
```

```python
# tests/__init__.py
```

```python
# app/__init__.py
# 暂时为空，Task 9 中填充 create_app 导出
```

```python
# app/routers/__init__.py
# 暂时为空，Task 9 中填充 register_routers
```

- [ ] **Step 2: 验证目录结构**

Run: `find core collectors analysis tools tests app -name "__init__.py" | sort`
Expected:
```
analysis/__init__.py
app/__init__.py
app/routers/__init__.py
collectors/__init__.py
core/__init__.py
tests/__init__.py
tools/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add core/ collectors/ analysis/ tools/ tests/ app/
git commit -m "chore: 创建分层目录骨架"
```

---

## Task 2: 移动 core/ 基础设施模块（无内部项目依赖的模块）

这些模块没有项目内 import 依赖，可以直接移动：`logging_utils.py`, `cache.py`, `provider_budget.py`。

**Files:**
- Move: `logging_utils.py` → `core/logging_utils.py`
- Move: `cache.py` → `core/cache.py`
- Move: `provider_budget.py` → `core/provider_budget.py`

- [ ] **Step 1: 移动无依赖的 core 模块**

```bash
git mv logging_utils.py core/logging_utils.py
git mv cache.py core/cache.py
git mv provider_budget.py core/provider_budget.py
```

- [ ] **Step 2: 验证这些模块可以被 import**

Run: `python -c "from core.logging_utils import configure_logging; print('OK')"`
Expected: `OK`

Run: `python -c "from core.cache import APICache; print('OK')"`
Expected: `OK`

Run: `python -c "from core.provider_budget import ProviderBudgetTracker; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: 移动无依赖模块到 core/"
```

---

## Task 3: 移动 config.py 到 core/ 并更新消费者

config.py 无项目内 import，但被其他模块引用。先移动，再更新引用者。

**Files:**
- Move: `config.py` → `core/config.py`
- Modify: `strategy_tools.py` (还在根目录，暂时更新 import)

- [ ] **Step 1: 移动 config.py**

```bash
git mv config.py core/config.py
```

- [ ] **Step 2: 更新 strategy_tools.py 中的 import**

在 `strategy_tools.py` 中：
```python
# 旧:
from config import settings
# 新:
from core.config import settings
```

- [ ] **Step 3: 验证**

Run: `python -c "from core.config import settings; print(settings.host)"`
Expected: `127.0.0.1`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: 移动 config.py 到 core/ 并更新引用"
```

---

## Task 4: 移动 collectors/ 数据收集模块

依赖链：`market_data_collector` → `binance_collector`, `hyperliquid_collector`, `okx_collector`；`cmc_collector` → `provider_budget`（已在 core/）。

**Files:**
- Move: `binance_collector.py` → `collectors/binance_collector.py`
- Move: `hyperliquid_collector.py` → `collectors/hyperliquid_collector.py`
- Move: `okx_collector.py` → `collectors/okx_collector.py`
- Move: `cmc_collector.py` → `collectors/cmc_collector.py`
- Move: `market_data_collector.py` → `collectors/market_data_collector.py`
- Modify: `collectors/market_data_collector.py` (更新内部 import)
- Modify: `collectors/cmc_collector.py` (更新内部 import)

- [ ] **Step 1: 移动所有收集器文件**

```bash
git mv binance_collector.py collectors/binance_collector.py
git mv hyperliquid_collector.py collectors/hyperliquid_collector.py
git mv okx_collector.py collectors/okx_collector.py
git mv cmc_collector.py collectors/cmc_collector.py
git mv market_data_collector.py collectors/market_data_collector.py
```

- [ ] **Step 2: 更新 collectors/market_data_collector.py 的内部 import**

```python
# 旧:
from binance_collector import BinanceCollector, FundingData, OIData, TickerData
from hyperliquid_collector import HyperliquidCollector
from okx_collector import OKXCollector
# 新:
from collectors.binance_collector import BinanceCollector, FundingData, OIData, TickerData
from collectors.hyperliquid_collector import HyperliquidCollector
from collectors.okx_collector import OKXCollector
```

- [ ] **Step 3: 更新 collectors/cmc_collector.py 的内部 import**

```python
# 旧:
from provider_budget import ProviderBudgetTracker
# 新:
from core.provider_budget import ProviderBudgetTracker
```

- [ ] **Step 4: 更新 collectors/__init__.py 提供便捷重导出**

```python
# collectors/__init__.py
from collectors.market_data_collector import UnifiedMarketCollector
from collectors.cmc_collector import CMCCollector
from collectors.binance_collector import BinanceCollector, TickerData, OIData, FundingData
```

- [ ] **Step 5: 验证**

Run: `python -c "from collectors.market_data_collector import UnifiedMarketCollector; print('OK')"`
Expected: `OK`

Run: `python -c "from collectors.cmc_collector import CMCCollector; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: 移动数据收集模块到 collectors/ 并更新 import"
```

---

## Task 5: 移动 analysis/ 和 tools/ 模块

**Files:**
- Move: `coin_analyzer.py` → `analysis/coin_analyzer.py`
- Modify: `analysis/coin_analyzer.py` (更新内部 import)
- Move: `strategy_tools.py` → `tools/strategy_tools.py`
- Move: `nofx_mapping.py` → `tools/nofx_mapping.py`

- [ ] **Step 1: 移动 coin_analyzer.py 到 analysis/**

```bash
git mv coin_analyzer.py analysis/coin_analyzer.py
```

- [ ] **Step 2: 更新 analysis/coin_analyzer.py 的内部 import**

```python
# 旧:
from binance_collector import BinanceCollector, TickerData, OIData
from config import settings
# 新:
from collectors.binance_collector import BinanceCollector, TickerData, OIData
from core.config import settings
```

- [ ] **Step 3: 移动 strategy_tools.py 和 nofx_mapping.py 到 tools/**

```bash
git mv strategy_tools.py tools/strategy_tools.py
git mv nofx_mapping.py tools/nofx_mapping.py
```

注意：`strategy_tools.py` 的 `from config import settings` 已在 Task 3 中更新为 `from core.config import settings`。

- [ ] **Step 4: 更新 analysis/__init__.py**

```python
# analysis/__init__.py
from analysis.coin_analyzer import CoinAnalyzer, CoinAnalysis, Direction
```

- [ ] **Step 5: 验证**

Run: `python -c "from analysis.coin_analyzer import CoinAnalyzer; print('OK')"`
Expected: `OK`

Run: `python -c "from tools.strategy_tools import parse_fixed_symbols; print('OK')"`
Expected: `OK`

Run: `python -c "from tools.nofx_mapping import build_mapping_summary; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: 移动分析和工具模块到 analysis/ 和 tools/"
```

---

## Task 6: 移动 cache_warmer.py 到 core/ 并更新 import

cache_warmer 有多个 TYPE_CHECKING 导入需要更新。

**Files:**
- Move: `cache_warmer.py` → `core/cache_warmer.py`
- Modify: `core/cache_warmer.py` (更新 import)

- [ ] **Step 1: 移动 cache_warmer.py**

```bash
git mv cache_warmer.py core/cache_warmer.py
```

- [ ] **Step 2: 更新 core/cache_warmer.py 的 import**

```python
# 旧:
from cache import APICache, get_cache

if TYPE_CHECKING:
    from binance_collector import BinanceCollector
    from cmc_collector import CMCCollector
    from coin_analyzer import CoinAnalyzer

# 新:
from core.cache import APICache, get_cache

if TYPE_CHECKING:
    from collectors.binance_collector import BinanceCollector
    from collectors.cmc_collector import CMCCollector
    from analysis.coin_analyzer import CoinAnalyzer
```

- [ ] **Step 3: 验证**

Run: `python -c "from core.cache_warmer import CacheWarmer; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: 移动 cache_warmer 到 core/ 并更新 TYPE_CHECKING import"
```

---

## Task 7: 创建 app/ 基础模块（exceptions, auth, schemas, utils）

从 main.py 提取非路由代码到 app/ 模块。

**Files:**
- Create: `app/exceptions.py`
- Create: `app/auth.py`
- Create: `app/schemas.py`
- Create: `app/utils.py`

- [ ] **Step 1: 创建 app/exceptions.py**

```python
#!/usr/bin/env python3
"""统一异常处理。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ServiceError(Exception):
    """业务异常基类"""
    def __init__(self, code: int, msg: str, data=None):
        self.code = code
        self.msg = msg
        self.data = data


class CollectorNotReady(ServiceError):
    def __init__(self):
        super().__init__(503, "采集器未就绪")


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.code,
            content={"code": exc.code, "msg": exc.msg, "data": exc.data}
        )
```

- [ ] **Step 2: 创建 app/auth.py**

从 main.py L63-77, L294-296 提取：

```python
#!/usr/bin/env python3
"""认证模块。"""

import os
from typing import Any, Dict

from fastapi import Query, HTTPException

from core.config import settings, AUTH_ENV_KEYS


def get_auth_source() -> str:
    for env_key in AUTH_ENV_KEYS:
        if os.getenv(env_key):
            return env_key
    return "default"


def build_auth_metadata(required: bool) -> Dict[str, Any]:
    return {
        "required": required,
        "query_param": "auth",
        "env_keys": list(AUTH_ENV_KEYS),
        "source": get_auth_source(),
    }


def verify_auth(auth: str) -> bool:
    """验证认证密钥"""
    return auth == settings.auth_key


def require_auth(auth: str = Query(..., description="认证密钥")) -> str:
    """FastAPI 依赖：验证认证密钥，失败抛 401"""
    if auth != settings.auth_key:
        raise HTTPException(status_code=401, detail="认证失败")
    return auth
```

- [ ] **Step 3: 创建 app/schemas.py**

从 main.py L218-290 提取：

```python
#!/usr/bin/env python3
"""API 响应模型。"""

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
    oi_value_usd: Optional[float] = None
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

    # 入场时机相关字段
    entry_timing: Optional[str] = None
    timing_score: Optional[float] = None
    pullback_pct: Optional[float] = None
    required_pullback: Optional[float] = None
    atr_pct: Optional[float] = None
    support_distance: Optional[float] = None
    resistance_distance: Optional[float] = None

    # 动态止损建议
    suggested_stop_pct: Optional[float] = None
    suggested_stop_price: Optional[float] = None
    volatility_level: Optional[str] = None


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
```

- [ ] **Step 4: 创建 app/utils.py**

修复 normalize_symbol 递归 bug（原 main.py L299-301）：

```python
#!/usr/bin/env python3
"""通用工具函数。"""


def normalize_symbol(symbol: str) -> str:
    """标准化交易对名称：大写 + 确保以 USDT 结尾"""
    symbol = symbol.upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    return symbol
```

- [ ] **Step 5: 验证所有模块可以 import**

Run: `python -c "from app.exceptions import ServiceError; from app.auth import require_auth; from app.schemas import CoinInfo; from app.utils import normalize_symbol; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/exceptions.py app/auth.py app/schemas.py app/utils.py
git commit -m "feat: 创建 app/ 基础模块（exceptions, auth, schemas, utils）"
```

---

## Task 8: 创建 app/dependencies.py 和 app/converters.py

**Files:**
- Create: `app/dependencies.py`
- Create: `app/converters.py`

- [ ] **Step 1: 创建 app/dependencies.py**

```python
#!/usr/bin/env python3
"""全局服务实例管理与 FastAPI 依赖注入。"""

import logging
from typing import Optional

from fastapi import HTTPException

from collectors.market_data_collector import UnifiedMarketCollector
from collectors.cmc_collector import CMCCollector
from analysis.coin_analyzer import CoinAnalyzer
from core.cache_warmer import CacheWarmer
from core.cache import APICache

logger = logging.getLogger(__name__)

# 全局服务实例
_collector: Optional[UnifiedMarketCollector] = None
_cmc_collector: Optional[CMCCollector] = None
_analyzer: Optional[CoinAnalyzer] = None
_cache_warmer: Optional[CacheWarmer] = None
_api_cache: Optional[APICache] = None


def init_services(
    collector: UnifiedMarketCollector,
    cmc_collector: CMCCollector,
    analyzer: CoinAnalyzer,
    api_cache: APICache,
    cache_warmer: Optional[CacheWarmer] = None,
):
    """在 lifespan 中调用，初始化所有服务实例"""
    global _collector, _cmc_collector, _analyzer, _cache_warmer, _api_cache
    _collector = collector
    _cmc_collector = cmc_collector
    _analyzer = analyzer
    _api_cache = api_cache
    _cache_warmer = cache_warmer


def cleanup_services():
    """清理全局引用"""
    global _collector, _cmc_collector, _analyzer, _cache_warmer, _api_cache
    _collector = None
    _cmc_collector = None
    _analyzer = None
    _cache_warmer = None
    _api_cache = None


def get_collector() -> UnifiedMarketCollector:
    if _collector is None:
        raise HTTPException(status_code=503, detail="采集器未就绪")
    return _collector


def get_collector_optional() -> Optional[UnifiedMarketCollector]:
    """可选注入：collector 未就绪时返回 None 而非抛异常。
    用于 /health 等需要在启动期间优雅降级的端点。"""
    return _collector


def get_cmc_collector() -> CMCCollector:
    if _cmc_collector is None:
        raise HTTPException(status_code=503, detail="宏观数据采集器未就绪")
    return _cmc_collector


def get_analyzer() -> CoinAnalyzer:
    if _analyzer is None:
        raise HTTPException(status_code=503, detail="分析器未就绪")
    return _analyzer


def get_cache_warmer() -> Optional[CacheWarmer]:
    return _cache_warmer


def get_api_cache() -> Optional[APICache]:
    return _api_cache
```

- [ ] **Step 2: 创建 app/converters.py**

从 main.py L304-418 和 L813-921（get_coin_data 的核心逻辑）提取：

```python
#!/usr/bin/env python3
"""数据转换与加载函数。"""

import asyncio
import logging
from typing import Any, Dict, Optional, Set

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
    tags_with_info = list(analysis.tags) if analysis.tags else []

    direction_tag = f"DIRECTION:{analysis.direction.value.upper()}"
    timing_idx = 0
    for i, tag in enumerate(tags_with_info):
        if tag.startswith("TIMING:"):
            timing_idx = i + 1
            break
    tags_with_info.insert(timing_idx, direction_tag)

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
        oi_value_usd=analysis.oi_value,
        funding_rate=analysis.funding_rate,
        volume_24h=analysis.volume_24h,
        tags=tags_with_info,
        reasons=analysis.reasons,
        vwap_1h=analysis.vwap_1h,
        vwap_4h=analysis.vwap_4h,
        price_vs_vwap_1h=analysis.price_vs_vwap_1h,
        price_vs_vwap_4h=analysis.price_vs_vwap_4h,
        vwap_signal=analysis.vwap_signal if analysis.vwap_signal else None,
        entry_timing=analysis.entry_timing,
        timing_score=analysis.timing_score,
        pullback_pct=analysis.pullback_pct,
        required_pullback=analysis.required_pullback,
        atr_pct=analysis.atr_pct,
        support_distance=analysis.support_distance,
        resistance_distance=analysis.resistance_distance,
        suggested_stop_pct=analysis.suggested_stop_pct,
        suggested_stop_price=analysis.suggested_stop_price,
        volatility_level=analysis.volatility_level,
    )


async def load_cmc_data_for_analyzer(
    cmc_collector: CMCCollector,
    analyzer: CoinAnalyzer,
):
    """加载 CMC 数据到分析器（安全调用，失败不影响主流程）"""
    if not cmc_collector or not analyzer:
        return

    try:
        trending_result, gainers_losers_result, listings_result = await asyncio.gather(
            cmc_collector.get_trending(limit=50),
            cmc_collector.get_gainers_losers(limit=50),
            cmc_collector.get_latest_listings(limit=200),
            return_exceptions=True
        )

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


async def fetch_coin_data(
    symbol: str,
    include_items: Set[str],
    collector: UnifiedMarketCollector,
    cmc_collector: CMCCollector,
    analyzer: CoinAnalyzer,
) -> Dict[str, Any]:
    """获取单个币种综合数据的核心逻辑。

    从原 get_coin_data 路由处理函数中提取，供 ai500 和 market_data 路由共用。
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
        return None

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
        data["netflow"] = {
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
```

- [ ] **Step 3: 验证**

Run: `python -c "from app.dependencies import get_collector; from app.converters import analysis_to_coin_info; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/dependencies.py app/converters.py
git commit -m "feat: 创建依赖注入和数据转换模块"
```

---

## Task 9: 创建所有路由模块

将 main.py L423-1783 的 42 个路由端点拆分到 9 个路由文件。

**Files:**
- Create: `app/routers/system.py`
- Create: `app/routers/ai500.py`
- Create: `app/routers/oi.py`
- Create: `app/routers/market_data.py`
- Create: `app/routers/analysis.py`
- Create: `app/routers/sentiment.py`
- Create: `app/routers/cmc.py`
- Create: `app/routers/strategy.py`
- Create: `app/routers/cache_admin.py`

**重要规则：**
每个路由文件遵循以下模式：
1. `router = APIRouter(tags=["域名"])`
2. 路由路径保留完整路径（如 `/api/ai500/list`），不使用 prefix
3. 认证使用 `Depends(require_auth)` 替换手动 `verify_auth` 调用
4. 通过 `Depends(get_collector)` 等注入服务依赖
5. 从 `app.converters` 导入共享转换函数

- [ ] **Step 1: 创建 app/routers/system.py**

```python
#!/usr/bin/env python3
"""系统状态、健康检查和能力查询路由。"""

import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.auth import build_auth_metadata, require_auth
from app.dependencies import get_collector, get_cmc_collector, get_cache_warmer, get_collector_optional
from core.cache import APICache, get_cache
from core.cache_warmer import get_warmup_schedule
from core.config import settings
from tools.nofx_mapping import build_mapping_summary
from tools.strategy_tools import (
    NOFX_ADAPTATION_CHECKLIST,
    build_universe_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["System"])


def build_cache_warmup_metadata() -> Dict[str, Any]:
    return {
        "enabled": settings.cache_warmup_enabled,
        "ttl": settings.cache_warmup_ttl,
        **get_warmup_schedule(),
    }


def build_health_checks(provider_status: Dict[str, Any], collector_initialized: bool) -> Dict[str, Any]:
    degraded_providers: List[str] = []
    for provider, info in provider_status.items():
        if not isinstance(info, dict):
            continue
        if info.get("enabled", True) and int(info.get("errors") or 0) > 0 and int(info.get("last_success") or 0) == 0:
            degraded_providers.append(provider)

    return {
        "collector_initialized": collector_initialized,
        "provider_count": len(provider_status),
        "degraded_providers": degraded_providers,
    }


async def build_system_status_payload(collector) -> Dict[str, Any]:
    cache = get_cache()
    cached = cache.get(APICache.KEY_SYSTEM_STATUS)
    if isinstance(cached, dict):
        return cached

    status = await collector.get_system_status()
    if not isinstance(status, dict):
        status = {"collector_status": status}
    status["auth"] = build_auth_metadata(required=True)
    status["cache_warmup"] = build_cache_warmup_metadata()
    status["status_cache_ttl"] = settings.cache_ttl_ranking
    cache.set(APICache.KEY_SYSTEM_STATUS, status, ttl=settings.cache_ttl_ranking)
    return status


@router.get("/")
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
                    "/api/ai500/list", "/api/ai500/{symbol}", "/api/ai500/stats",
                    "/api/oi/top-ranking", "/api/oi/low-ranking", "/api/oi-cap/ranking",
                    "/api/price/ranking",
                    "/api/funding-rate/top", "/api/funding-rate/low", "/api/funding-rate/{symbol}",
                    "/api/heatmap/future/{symbol}", "/api/heatmap/spot/{symbol}", "/api/heatmap/list",
                    "/api/coin/{symbol}",
                ],
            },
            "extended": {
                "description": "增强分析与监控接口",
                "endpoints": [
                    "/api/analysis/short", "/api/analysis/long", "/api/analysis/early-signals",
                    "/api/analysis/flash-crash", "/api/analysis/high-volatility",
                    "/api/analysis/market-overview",
                    "/api/netflow/top-ranking", "/api/netflow/low-ranking",
                    "/api/system/status", "/api/system/capabilities", "/api/system/provider-usage",
                    "/api/system/nofx-compatibility", "/api/system/strategy-universe",
                    "/api/system/nofx-adaptation-checklist",
                    "/api/cache/status",
                ],
            },
            "macro": {
                "description": "宏观与市值数据（优先 CoinGecko Demo，其次 CMC）",
                "endpoints": [
                    "/api/sentiment/fear-greed", "/api/sentiment/market",
                    "/api/cmc/listings", "/api/cmc/trending", "/api/cmc/gainers-losers",
                    "/api/cmc/market-overview",
                ],
            },
            "strategy": {
                "description": "配对中性 / 固定币池策略辅助接口",
                "endpoints": [
                    "/api/strategy/pair-neutral/template",
                    "/api/strategy/pair-neutral/context",
                ],
            },
        },
    }


@router.get("/health")
async def health_check(collector=Depends(get_collector_optional)):
    """健康检查（不需要认证，collector 未就绪时优雅降级）"""
    provider_status = collector.get_provider_status() if collector and hasattr(collector, "get_provider_status") else {}
    checks = build_health_checks(provider_status, collector_initialized=collector is not None)
    return {
        "status": "healthy" if checks["collector_initialized"] and not checks["degraded_providers"] else "degraded",
        "timestamp": int(time.time()),
        "providers": provider_status,
        "coingecko_api": settings.coingecko_api_key is not None,
        "cmc_api": settings.cmc_api_key is not None,
        "auth": build_auth_metadata(required=False),
        "cache_warmup": build_cache_warmup_metadata(),
        "checks": checks,
    }


@router.get("/api/system/status")
async def get_system_status(auth: str = Depends(require_auth), collector=Depends(get_collector)):
    status = await build_system_status_payload(collector)
    return {"success": True, "data": status}


@router.get("/api/system/capabilities")
async def get_system_capabilities(auth: str = Depends(require_auth), cmc_collector=Depends(get_cmc_collector)):
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


@router.get("/api/system/provider-usage")
async def get_provider_usage(auth: str = Depends(require_auth), cmc_collector=Depends(get_cmc_collector)):
    return {"success": True, "data": await cmc_collector.get_provider_usage()}


@router.get("/api/system/nofx-compatibility")
async def get_nofx_compatibility(auth: str = Depends(require_auth)):
    data = build_mapping_summary()
    data["timestamp"] = int(time.time())
    return {"success": True, "data": data}


@router.get("/api/system/strategy-universe")
async def get_strategy_universe(auth: str = Depends(require_auth)):
    data = build_universe_summary()
    data["timestamp"] = int(time.time())
    return {"success": True, "data": data}


@router.get("/api/system/nofx-adaptation-checklist")
async def get_nofx_adaptation_checklist(auth: str = Depends(require_auth)):
    return {
        "success": True,
        "data": {
            "items": NOFX_ADAPTATION_CHECKLIST,
            "timestamp": int(time.time()),
        },
    }
```

- [ ] **Step 2: 创建 app/routers/ai500.py**

从 main.py L499-668 提取，修复 L606 的 `get_coin` → `fetch_coin_data` 调用：

完整代码参照 main.py L499-668，关键变更：
- `@app.get(...)` → `@router.get(...)`
- 手动 `verify_auth(auth)` → `Depends(require_auth)`
- 全局 `collector`/`analyzer`/`cmc_collector` → `Depends(get_xxx)`
- `analysis_to_coin_info` → `from app.converters import analysis_to_coin_info`
- `load_cmc_data_for_analyzer()` → `load_cmc_data_for_analyzer(cmc_collector, analyzer)`
- L606 `get_coin(...)` → `fetch_coin_data(symbol, include_items, collector, cmc_collector, analyzer)`

- [ ] **Step 3: 创建 app/routers/oi.py**

从 main.py L670-811, L1347-1358 提取。同样的模式转换。

- [ ] **Step 4: 创建 app/routers/market_data.py**

从 main.py L813-921, L1272-1345, L1360-1391 提取。
- `get_coin_data` 路由体改为调用 `fetch_coin_data()`，完整路由代码框架：

```python
@router.get("/api/coin/{symbol}")
async def get_coin_data(
    symbol: str,
    auth: str = Depends(require_auth),
    include: str = Query("netflow,oi,price", description="返回数据类型"),
    collector=Depends(get_collector),
    cmc_collector=Depends(get_cmc_collector),
    analyzer=Depends(get_analyzer),
):
    """获取单个币种综合数据"""
    symbol = normalize_symbol(symbol)
    include_items = {item.strip() for item in include.split(",") if item.strip()}

    try:
        data = await fetch_coin_data(symbol, include_items, collector, cmc_collector, analyzer)
        if data is None:
            raise HTTPException(status_code=404, detail=f"币种 {symbol} 不存在")
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取币种数据失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 5: 创建 app/routers/analysis.py**

从 main.py L926-1171 提取。

- [ ] **Step 6: 创建 app/routers/sentiment.py**

从 main.py L1173-1270 提取。

- [ ] **Step 7: 创建 app/routers/cmc.py**

从 main.py L1588-1773 提取。

- [ ] **Step 8: 创建 app/routers/strategy.py**

从 main.py L1469-1495 提取。

- [ ] **Step 9: 创建 app/routers/cache_admin.py**

从 main.py L1515-1583 提取。

- [ ] **Step 10: 填充 app/routers/__init__.py**

```python
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
```

- [ ] **Step 11: 验证所有路由模块可以 import**

Run: `python -c "from app.routers.system import router; from app.routers.ai500 import router; from app.routers.oi import router; print('OK')"`
Expected: `OK`

- [ ] **Step 12: Commit**

```bash
git add app/routers/
git commit -m "feat: 创建 9 个路由模块，拆分 42 个端点"
```

---

## Task 10: 创建 app/factory.py 和 app/__init__.py，替换 main.py

**Files:**
- Create: `app/factory.py`
- Modify: `app/__init__.py`
- Modify: `main.py` (替换为瘦入口)

- [ ] **Step 1: 创建 app/factory.py**

```python
#!/usr/bin/env python3
"""FastAPI 应用工厂。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies import init_services, cleanup_services
from app.exceptions import register_exception_handlers
from app.routers import register_routers
from collectors.market_data_collector import UnifiedMarketCollector
from collectors.cmc_collector import CMCCollector
from analysis.coin_analyzer import CoinAnalyzer
from core.cache import init_cache
from core.cache_warmer import CacheWarmer
from core.config import settings
from core.logging_utils import configure_logging
from tools.strategy_tools import parse_fixed_symbols

configure_logging(
    log_dir=settings.log_dir,
    log_filename=settings.log_file,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("正在启动本地数据服务器...")

    # 初始化缓存
    api_cache = init_cache(default_ttl=settings.cache_warmup_ttl)
    logger.info(f"✓ API 缓存已初始化，TTL: {settings.cache_warmup_ttl}s")

    # 初始化 Binance 采集器
    collector = UnifiedMarketCollector(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        hyperliquid_enabled=settings.hyperliquid_enabled,
        hyperliquid_dex=settings.hyperliquid_dex,
        okx_enabled=settings.okx_enabled,
        okx_api_key=settings.okx_api_key,
        okx_api_secret=settings.okx_api_secret,
        okx_api_passphrase=settings.okx_api_passphrase,
        snapshot_file=settings.snapshot_file,
        focus_symbols=parse_fixed_symbols(),
        universe_mode=settings.analysis_universe_mode,
    )

    # 初始化宏观数据采集器
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
    cache_warmer = None
    if settings.cache_warmup_enabled:
        cache_warmer = CacheWarmer(
            collector=collector,
            analyzer=analyzer,
            cmc_collector=cmc_collector,
            cache=api_cache,
            cache_ttl=settings.cache_warmup_ttl,
            ai500_limit=20,
        )
        await cache_warmer.start()
        logger.info("✓ 缓存预热器已启动")

    # 注册全局服务实例
    init_services(
        collector=collector,
        cmc_collector=cmc_collector,
        analyzer=analyzer,
        api_cache=api_cache,
        cache_warmer=cache_warmer,
    )

    logger.info(f"✓ 服务器启动完成，监听 {settings.host}:{settings.port}")

    yield

    # 清理
    if cache_warmer:
        await cache_warmer.stop()
    await collector.close()
    await cmc_collector.close()
    cleanup_services()
    logger.info("服务器已关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
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
```

- [ ] **Step 2: 填充 app/__init__.py**

```python
from app.factory import create_app

__all__ = ["create_app"]
```

- [ ] **Step 3: 替换 main.py 为瘦入口**

保存旧 main.py 为 `main.py.bak`（备份），然后替换内容为：

```python
#!/usr/bin/env python3
"""NOFX 本地数据服务器入口"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    from core.config import settings
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
```

- [ ] **Step 4: 验证应用可以创建**

Run: `python -c "from app import create_app; app = create_app(); print(f'Routes: {len(app.routes)}')"`
Expected: 输出路由数量 > 40

- [ ] **Step 5: Commit**

```bash
git add app/factory.py app/__init__.py main.py
git commit -m "feat: 创建应用工厂，main.py 缩减为瘦入口"
```

---

## Task 11: 移动测试文件并更新 import

**Files:**
- Move: 所有 11 个 `test_*.py` → `tests/test_*.py`
- Modify: 每个测试文件的内部 import

- [ ] **Step 1: 移动所有测试文件**

```bash
git mv test_api.py tests/test_api.py
git mv test_binance_collector.py tests/test_binance_collector.py
git mv test_cache.py tests/test_cache.py
git mv test_cache_warmer.py tests/test_cache_warmer.py
git mv test_cmc_collector.py tests/test_cmc_collector.py
git mv test_coin_analyzer.py tests/test_coin_analyzer.py
git mv test_config.py tests/test_config.py
git mv test_logging_utils.py tests/test_logging_utils.py
git mv test_market_data_collector.py tests/test_market_data_collector.py
git mv test_okx_collector.py tests/test_okx_collector.py
git mv test_provider_budget.py tests/test_provider_budget.py
```

- [ ] **Step 2: 更新 tests/test_api.py 的 import（完整改写 mock 策略）**

原 test_api.py 使用模块级 mock（`patch('main.BinanceCollector')` 等），重构后需要完整改写：

```python
# 旧（删除整个 mock 块）:
with patch('main.BinanceCollector'), \
     patch('main.CMCCollector'), \
     patch('main.CoinAnalyzer'), \
     patch('main.CacheWarmer'), \
     patch('main.init_cache'), \
     patch('main.get_cache'):
    import main
    from main import app, verify_auth, analysis_to_coin_info
    from coin_analyzer import CoinAnalysis, Direction

# 新:
with patch('app.factory.UnifiedMarketCollector'), \
     patch('app.factory.CMCCollector'), \
     patch('app.factory.CoinAnalyzer'), \
     patch('app.factory.CacheWarmer'), \
     patch('app.factory.init_cache'), \
     patch('app.factory.get_cache'):
    from app import create_app
    app = create_app()

from app.auth import verify_auth
from app.converters import analysis_to_coin_info
from app.schemas import CoinInfo, AI500Response, OIRankingResponse
from analysis.coin_analyzer import CoinAnalysis, Direction
from core.config import settings
```

还需要全文替换：
- `main.settings` → `settings`（已从 core.config 导入）
- `from main import CoinInfo` → 删除（已在顶层导入）
- `from main import AI500Response` → 删除（已在顶层导入）
- `from main import OIRankingResponse` → 删除（已在顶层导入）
- `from cache import init_cache` → `from core.cache import init_cache`
- `from cache import APICache` → `from core.cache import APICache`

- [ ] **Step 3: 更新 tests/test_binance_collector.py 的 import**

```python
# 旧:
from binance_collector import BinanceCollector, TickerData, OIData, FundingData
# 新:
from collectors.binance_collector import BinanceCollector, TickerData, OIData, FundingData
```

- [ ] **Step 4: 更新 tests/test_cache.py 的 import**

```python
# 旧:
from cache import APICache
# 新:
from core.cache import APICache
```

- [ ] **Step 5: 更新 tests/test_cache_warmer.py 的 import**

```python
# 旧:
from cache_warmer import get_warmup_schedule
# 新:
from core.cache_warmer import get_warmup_schedule
```

- [ ] **Step 6: 更新 tests/test_cmc_collector.py 的 import**

```python
# 旧:
from cmc_collector import CMCCollector
# 新:
from collectors.cmc_collector import CMCCollector
```

- [ ] **Step 7: 更新 tests/test_coin_analyzer.py 的 import**

```python
# 旧:
from coin_analyzer import CoinAnalyzer, CoinAnalysis, Direction
from binance_collector import BinanceCollector, TickerData, OIData, FundingData
# 新:
from analysis.coin_analyzer import CoinAnalyzer, CoinAnalysis, Direction
from collectors.binance_collector import BinanceCollector, TickerData, OIData, FundingData
```

注意：需要读取文件确认具体 import 的名称列表。

- [ ] **Step 8: 更新 tests/test_config.py 的 import**

```python
# 旧:
from config import load_settings
# 新:
from core.config import load_settings
```

- [ ] **Step 9: 更新 tests/test_logging_utils.py 的 import**

```python
# 旧:
from logging_utils import build_logging_handlers
# 新:
from core.logging_utils import build_logging_handlers
```

- [ ] **Step 10: 更新 tests/test_market_data_collector.py 的 import**

```python
# 旧:
from binance_collector import OIData, TickerData
from hyperliquid_collector import HyperliquidAssetContext
from market_data_collector import UnifiedMarketCollector
# 新:
from collectors.binance_collector import OIData, TickerData
from collectors.hyperliquid_collector import HyperliquidAssetContext
from collectors.market_data_collector import UnifiedMarketCollector
```

- [ ] **Step 11: 更新 tests/test_okx_collector.py 的 import**

```python
# 旧:
from okx_collector import OKXCollector
# 新:
from collectors.okx_collector import OKXCollector
```

- [ ] **Step 12: 更新 tests/test_provider_budget.py 的 import**

```python
# 旧:
from provider_budget import ProviderBudgetTracker
# 新:
from core.provider_budget import ProviderBudgetTracker
```

- [ ] **Step 13: 运行所有测试**

Run: `cd /home/admin/MarketDataService && python -m pytest tests/ -v`
Expected: 所有测试通过

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "refactor: 移动测试文件到 tests/ 并更新 import"
```

---

## Task 12: 删除根目录旧文件并最终验证

**Files:**
- Delete: 根目录已迁移的 `.py` 源文件（不含 main.py，已被替换为瘦入口）

- [ ] **Step 1: 确认无遗留引用指向旧路径**

Run: `grep -rn "^from config import\|^from cache import\|^from cache_warmer import\|^from logging_utils import\|^from provider_budget import\|^from binance_collector import\|^from market_data_collector import\|^from cmc_collector import\|^from hyperliquid_collector import\|^from okx_collector import\|^from coin_analyzer import\|^from strategy_tools import\|^from nofx_mapping import" --include="*.py" . | grep -v __pycache__ | grep -v venv | grep -v ".py.bak"`
Expected: 无输出（所有旧路径 import 都已更新）

- [ ] **Step 2: 删除根目录旧文件**

```bash
rm -f config.py cache.py cache_warmer.py logging_utils.py provider_budget.py
rm -f binance_collector.py market_data_collector.py cmc_collector.py hyperliquid_collector.py okx_collector.py
rm -f coin_analyzer.py strategy_tools.py nofx_mapping.py
rm -f test_api.py test_binance_collector.py test_cache.py test_cache_warmer.py
rm -f test_cmc_collector.py test_coin_analyzer.py test_config.py test_logging_utils.py
rm -f test_market_data_collector.py test_okx_collector.py test_provider_budget.py
```

- [ ] **Step 3: 清理 __pycache__**

```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 4: 运行完整测试**

Run: `cd /home/admin/MarketDataService && python -m pytest tests/ -v`
Expected: 所有测试通过

- [ ] **Step 5: 语法验证所有新模块**

```bash
python -m py_compile main.py
python -m py_compile app/__init__.py
python -m py_compile app/factory.py
python -m py_compile app/dependencies.py
python -m py_compile app/auth.py
python -m py_compile app/schemas.py
python -m py_compile app/utils.py
python -m py_compile app/converters.py
python -m py_compile app/exceptions.py
```

- [ ] **Step 6: 验证应用启动**

Run: `timeout 10 python -c "from app import create_app; app = create_app(); print('App created successfully'); print(f'Total routes: {len(app.routes)}')" 2>&1 || true`
Expected: `App created successfully` + 路由数量

- [ ] **Step 7: 验证最终目录结构**

Run: `find . -name "*.py" -not -path "./venv/*" -not -path "./__pycache__/*" -not -path "./.pytest_cache/*" | sort`
Expected: 所有 .py 文件都在 app/, core/, collectors/, analysis/, tools/, tests/ 子目录下，根目录仅有 main.py

- [ ] **Step 8: 删除备份文件（如有）**

```bash
rm -f main.py.bak
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: Phase 1 完成 - 删除根目录旧文件，架构重构就绪"
```

---

## Task 13: 合并为单个 Phase 1 commit（可选但推荐）

设计文档要求 Phase 1 作为单个 commit 以便一次性回滚。将 Task 1-12 的多个 commit 合并。

- [ ] **Step 1: 查看本次重构的 commit 数量**

Run: `git log --oneline HEAD~15..HEAD` 确认本轮所有 commit

- [ ] **Step 2: 将所有 Phase 1 commit 合并为一个**

假设有 N 个新 commit：
```bash
git reset --soft HEAD~N
git commit -m "refactor: Phase 1 架构重构 - 目录分层 + main.py 路由拆分"
```

注意：此步骤会丢失中间 commit 的历史，但保留所有文件变更。如果更倾向保留详细历史以便 bisect，可以跳过此步骤，改用 `git revert HEAD~N..HEAD` 方式回滚。

---

## 注意事项

### 路由模块编写规范

每个路由文件（Task 9 的 Step 2-9）遵循相同模式，以 `app/routers/analysis.py` 为例：

```python
#!/usr/bin/env python3
"""分析类路由。"""

import logging
import time

from fastapi import APIRouter, Depends, Query

from app.auth import require_auth
from app.converters import analysis_to_coin_info, load_cmc_data_for_analyzer
from app.dependencies import get_analyzer, get_cmc_collector
from analysis.coin_analyzer import Direction

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Analysis"])


@router.get("/api/analysis/short")
async def get_short_candidates(
    auth: str = Depends(require_auth),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    analyzer=Depends(get_analyzer),
    cmc_collector=Depends(get_cmc_collector),
):
    """获取做空候选币种"""
    try:
        coins = await analyzer.get_short_candidates(limit)
        return {
            "success": True,
            "data": {
                "coins": [analysis_to_coin_info(c).model_dump() for c in coins],
                "count": len(coins),
                "direction": "short",
                "provider": cmc_collector._pick_provider(),
                "timestamp": int(time.time()),
            }
        }
    except Exception as e:
        logger.error(f"获取做空候选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**关键转换规则（适用于所有路由文件）：**
1. `@app.get(...)` → `@router.get(...)`
2. `if not verify_auth(auth): raise HTTPException(...)` → `auth: str = Depends(require_auth)`
3. 直接访问全局 `collector` → `collector=Depends(get_collector)`
4. 直接访问全局 `analyzer` → `analyzer=Depends(get_analyzer)`
5. 直接访问全局 `cmc_collector` → `cmc_collector=Depends(get_cmc_collector)`
6. 直接访问全局 `cache_warmer` → `cache_warmer=Depends(get_cache_warmer)`
7. `load_cmc_data_for_analyzer()` → `load_cmc_data_for_analyzer(cmc_collector, analyzer)`
8. `normalize_symbol(symbol)` → `from app.utils import normalize_symbol`
9. `analysis_to_coin_info(c)` → `from app.converters import analysis_to_coin_info`
10. `from fastapi import HTTPException` 需要在使用 HTTPException 的路由文件中导入

### OI 路由跨函数引用

`get_oi_top`（main.py L797-810）调用了 `get_oi_top_ranking`。在拆分后，两者都在 `app/routers/oi.py` 中，可直接调用（同文件内函数调用）。
