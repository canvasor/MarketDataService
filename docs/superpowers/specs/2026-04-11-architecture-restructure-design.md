# MarketDataService 架构重构设计

> 日期: 2026-04-11
> 状态: 已审核修订
> 范围: 渐进式重构，分3个Phase执行

---

## 1. 背景与问题

MarketDataService 是一个基于 FastAPI 的加密货币市场数据聚合服务，当前代码量约 9,500 行 Python。项目面临以下架构问题：

### 1.1 核心问题

| 问题 | 严重程度 | 说明 |
|------|---------|------|
| main.py 膨胀 | 严重 | 1,783行，42个路由全部堆在一个文件，占全项目19% |
| 扁平目录结构 | 中等 | 所有源码、测试混在根目录，无分层 |
| 职责混乱 | 中等 | main.py 包含认证、数据转换、工具函数、响应模型、路由 |
| 收集器职责过重 | 中等 | binance_collector(961行) 混有 ATR/VWAP 计算逻辑 |
| 代码重复 | 轻微 | contains_non_ascii, normalize_symbol 等函数在多处重复 |
| 参数硬编码 | 轻微 | 权重系数、预热时机等不可配置 |

### 1.2 当前文件结构

```
MarketDataService/
├── main.py              (1,783行)  ← 路由+认证+模型+转换+工具
├── binance_collector.py  (961行)   ← 收集+计算混合
├── coin_analyzer.py      (1,042行) ← 分析+权重硬编码
├── market_data_collector.py (745行)
├── cmc_collector.py      (609行)
├── cache_warmer.py       (565行)
├── okx_collector.py      (344行)
├── hyperliquid_collector.py (289行)
├── strategy_tools.py     (235行)
├── nofx_mapping.py       (226行)
├── provider_budget.py    (179行)
├── config.py             (137行)
├── cache.py              (199行)
├── logging_utils.py      (63行)
├── test_*.py             (11个测试文件)
└── scripts/
```

---

## 2. 重构策略

采用**渐进式重构**，分3个Phase推进。每个Phase独立可验证，可以在任意Phase暂停而不影响系统运行。

### 2.1 Phase 概览

| Phase | 重点 | 预期效果 | 风险 |
|-------|------|---------|------|
| Phase 1 | 目录骨架 + main.py 路由拆分 + 测试归位 | main.py 从1783→~30行 | 低（纯移动+拆分） |
| Phase 2 | 收集器层整理 + 分析逻辑拆分 | 消除职责混乱和代码重复 | 中 |
| Phase 3 | 缓存装饰器 + 配置参数去硬编码 | 统一缓存策略，提升可配置性 | 低 |

---

## 3. Phase 1 详细设计：目录骨架 + 路由拆分

### 3.1 目标目录结构

```
MarketDataService/
├── app/                          # 应用包
│   ├── __init__.py               # 导出 create_app()
│   ├── factory.py                # FastAPI 应用工厂 + lifespan + CORS
│   ├── dependencies.py           # 全局实例管理 + FastAPI Depends
│   ├── auth.py                   # verify_auth + require_auth 依赖
│   ├── exceptions.py             # 统一异常类 + 全局异常处理器
│   ├── schemas.py                # CoinInfo, AI500Response, OIRankingResponse 等
│   ├── converters.py             # analysis_to_coin_info, load_cmc_data 等
│   ├── utils.py                  # normalize_symbol, build_*_metadata
│   └── routers/                  # 路由（按功能域拆分）
│       ├── __init__.py           # register_routers() 统一注册
│       ├── ai500.py              # /api/ai500/*
│       ├── oi.py                 # /api/oi/*, /api/oi-cap/*
│       ├── analysis.py           # /api/analysis/*
│       ├── sentiment.py          # /api/sentiment/*
│       ├── market_data.py        # /api/coin/*, /api/funding-rate/*, /api/heatmap/*, /api/price/*, /api/netflow/*
│       ├── cmc.py                # /api/cmc/*
│       ├── strategy.py           # /api/strategy/*
│       ├── system.py             # /api/system/*, /health, /
│       └── cache_admin.py        # /api/cache/*
├── collectors/                   # 数据收集层（文件移入，内部不改）
│   ├── __init__.py               # 重导出收集器类
│   ├── binance_collector.py
│   ├── market_data_collector.py
│   ├── cmc_collector.py
│   ├── hyperliquid_collector.py
│   └── okx_collector.py
├── analysis/                     # 分析层（文件移入，内部不改）
│   ├── __init__.py               # 重导出 CoinAnalyzer 等
│   └── coin_analyzer.py
├── core/                         # 基础设施
│   ├── __init__.py
│   ├── config.py
│   ├── cache.py
│   ├── cache_warmer.py
│   ├── logging_utils.py
│   └── provider_budget.py
├── tools/                        # 策略工具
│   ├── __init__.py
│   ├── strategy_tools.py
│   └── nofx_mapping.py
├── tests/                        # 测试
│   ├── __init__.py
│   ├── test_api.py
│   ├── test_binance_collector.py
│   ├── test_cache.py
│   ├── test_cache_warmer.py
│   ├── test_cmc_collector.py
│   ├── test_coin_analyzer.py
│   ├── test_config.py
│   ├── test_logging_utils.py
│   ├── test_market_data_collector.py
│   ├── test_okx_collector.py
│   └── test_provider_budget.py
├── scripts/                      # 运维脚本（不变）
├── data/                         # 数据目录（不变）
├── logs/                         # 日志目录（不变）
├── main.py                       # 瘦入口 (~15行)
├── requirements.txt
├── .env.example
└── README.md
```

### 3.2 各模块职责说明

#### 3.2.1 `app/factory.py` — 应用工厂

从 main.py 提取：
- `create_app()` 函数：创建 FastAPI 实例 + 注册路由 + CORS 中间件 + 全局异常处理器
- `lifespan()` 异步上下文：初始化/清理所有全局实例

```python
# app/factory.py 核心结构
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import register_routers
from app.exceptions import register_exception_handlers

def create_app() -> FastAPI:
    app = FastAPI(title="NOFX Local Data Server", version="2.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, ...)
    register_routers(app)
    register_exception_handlers(app)
    return app
```

#### 3.2.2 `app/dependencies.py` — 依赖注入

将 main.py 中的全局变量转化为 FastAPI 依赖：

```python
# app/dependencies.py
from fastapi import Depends, HTTPException

_collector = None
_analyzer = None
_cmc_collector = None
_cache_warmer = None

def init_services(...):
    """在 lifespan 中调用，初始化所有服务实例"""
    ...

def get_collector():
    if _collector is None:
        raise HTTPException(503, "采集器未就绪")
    return _collector

def get_analyzer():
    ...

def get_cmc_collector():
    ...
```

路由中使用方式：
```python
@router.get("/api/ai500/list")
async def ai500_list(
    collector=Depends(get_collector),
    analyzer=Depends(get_analyzer),
    auth: str = Query(...)
):
    ...
```

#### 3.2.3 `app/auth.py` — 认证

从 main.py 提取 verify_auth, get_auth_source, build_auth_metadata：

```python
# app/auth.py
from fastapi import Query, HTTPException, Depends
from core.config import settings, AUTH_ENV_KEYS

def require_auth(auth: str = Query(..., description="认证密钥")):
    """FastAPI 依赖：验证认证密钥，失败抛 401"""
    if auth != settings.auth_key:
        raise HTTPException(401, "认证失败")
    return auth
```

#### 3.2.4 `app/schemas.py` — 响应模型

从 main.py 提取所有 Pydantic 模型：
- `CoinInfo` (含 30+ 字段)
- `AI500Response`
- `OIPosition`
- `OIRankingResponse`

#### 3.2.5 `app/converters.py` — 数据转换

从 main.py 提取：
- `analysis_to_coin_info()` — CoinAnalysis → CoinInfo 转换
- `load_cmc_data_for_analyzer()` — CMC 数据加载到分析器

#### 3.2.6 `app/exceptions.py` — 统一异常处理

```python
# app/exceptions.py
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

#### 3.2.7 路由拆分详情

**`app/routers/ai500.py`** — 3个端点
- `GET /api/ai500/list` — AI500 币种列表（从 main.py L499-585）
- `GET /api/ai500/{symbol}` — 单币详情（从 main.py L587-628）
- `GET /api/ai500/stats` — 统计概览（从 main.py L630-668）

**`app/routers/oi.py`** — 4个端点
- `GET /api/oi/top-ranking` — OI 增长排名（从 main.py L670-740）
- `GET /api/oi/low-ranking` — OI 下降排名（从 main.py L741-796）
- `GET /api/oi/top` — OI Top（从 main.py L797-811）
- `GET /api/oi-cap/ranking` — OI/市值比排名（从 main.py L1347-1358）

**`app/routers/analysis.py`** — 6个端点
- `GET /api/analysis/short` — 做空信号（从 main.py L926-957）
- `GET /api/analysis/long` — 做多信号（从 main.py L959-990）
- `GET /api/analysis/flash-crash` — 闪崩风险（从 main.py L992-1023）
- `GET /api/analysis/high-volatility` — 高波动（从 main.py L1025-1058）
- `GET /api/analysis/early-signals` — 早期信号（从 main.py L1060-1107）
- `GET /api/analysis/market-overview` — 市场概览（从 main.py L1109-1171）

**`app/routers/sentiment.py`** — 2个端点
- `GET /api/sentiment/fear-greed` — 恐惧贪婪指数（从 main.py L1173-1234）
- `GET /api/sentiment/market` — 市场情绪（从 main.py L1236-1270）

**`app/routers/market_data.py`** — 10个端点
- `GET /api/coin/{symbol}` — 单币数据（从 main.py L813-924）
- `GET /api/netflow/top-ranking` — 资金流入排名
- `GET /api/netflow/low-ranking` — 资金流出排名
- `GET /api/price/ranking` — 价格排名
- `GET /api/funding-rate/top` — 资金费率 Top
- `GET /api/funding-rate/low` — 资金费率 Low
- `GET /api/funding-rate/{symbol}` — 单币资金费率
- `GET /api/heatmap/future/{symbol}` — 合约热力图
- `GET /api/heatmap/spot/{symbol}` — 现货热力图
- `GET /api/heatmap/list` — 热力图列表

**`app/routers/cmc.py`** — 4个端点
- `GET /api/cmc/listings` — 市值排名（从 main.py L1588-1638）
- `GET /api/cmc/trending` — 热门币种（从 main.py L1640-1683）
- `GET /api/cmc/gainers-losers` — 涨跌幅排名（从 main.py L1685-1734）
- `GET /api/cmc/market-overview` — 市场概览（从 main.py L1736-1783）

**`app/routers/strategy.py`** — 2个端点
- `GET /api/strategy/pair-neutral/template` — 配对模板
- `GET /api/strategy/pair-neutral/context` — 配对上下文

**`app/routers/system.py`** — 8个端点
- `GET /` — 根路由
- `GET /health` — 健康检查
- `GET /api/system/status` — 系统状态
- `GET /api/system/capabilities` — 系统能力
- `GET /api/system/provider-usage` — 提供商使用
- `GET /api/system/nofx-compatibility` — NoFx 兼容性
- `GET /api/system/strategy-universe` — 策略宇宙
- `GET /api/system/nofx-adaptation-checklist` — 适配清单

**`app/routers/cache_admin.py`** — 3个端点
- `GET /api/cache/status` — 缓存状态
- `POST /api/cache/warmup` — 手动预热
- `DELETE /api/cache/clear` — 清除缓存

### 3.3 `app/__init__.py` 与 `app/routers/__init__.py`

```python
# app/__init__.py
from app.factory import create_app

__all__ = ["create_app"]
```

```python
# app/routers/__init__.py
from fastapi import FastAPI

def register_routers(app: FastAPI):
    """统一注册所有路由模块，每个 router 自带完整路径前缀"""
    from app.routers import (
        ai500, oi, analysis, sentiment, market_data,
        cmc, strategy, system, cache_admin
    )
    for module in [ai500, oi, analysis, sentiment, market_data,
                   cmc, strategy, system, cache_admin]:
        app.include_router(module.router)
```

各 router 文件内自行定义前缀，例如：
```python
# app/routers/ai500.py
from fastapi import APIRouter
router = APIRouter(tags=["AI500"])
# 路由路径保留完整 /api/ai500/...，不使用 prefix 参数
```

### 3.4 瘦入口 `main.py`

重构后的根目录 main.py 仅作为入口点：

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

### 3.5 文件移动计划

Phase 1 的文件移动分两类：**纯移动**（只改路径和 import）和**拆分创建**（从 main.py 提取）。

#### 纯移动（修改 import 路径，内部逻辑不变）

| 源文件 | 目标路径 | import 变更 |
|--------|---------|------------|
| `config.py` | `core/config.py` | `from config import` → `from core.config import` |
| `cache.py` | `core/cache.py` | `from cache import` → `from core.cache import` |
| `cache_warmer.py` | `core/cache_warmer.py` | `from cache_warmer import` → `from core.cache_warmer import` |
| `logging_utils.py` | `core/logging_utils.py` | `from logging_utils import` → `from core.logging_utils import` |
| `provider_budget.py` | `core/provider_budget.py` | `from provider_budget import` → `from core.provider_budget import` |
| `binance_collector.py` | `collectors/binance_collector.py` | 同上模式 |
| `market_data_collector.py` | `collectors/market_data_collector.py` | 同上 |
| `cmc_collector.py` | `collectors/cmc_collector.py` | 同上 |
| `hyperliquid_collector.py` | `collectors/hyperliquid_collector.py` | 同上 |
| `okx_collector.py` | `collectors/okx_collector.py` | 同上 |
| `coin_analyzer.py` | `analysis/coin_analyzer.py` | 同上 |
| `strategy_tools.py` | `tools/strategy_tools.py` | 同上 |
| `nofx_mapping.py` | `tools/nofx_mapping.py` | 同上 |
| `test_*.py` (11个) | `tests/test_*.py` | 修改内部 import |

#### 从 main.py 拆分创建

| 新文件 | 来源行号 | 说明 |
|--------|---------|------|
| `app/schemas.py` | L218-290 | Pydantic 响应模型 |
| `app/auth.py` | L63-77, L294-296 | 认证函数 |
| `app/converters.py` | L304-418 | 数据转换+CMC加载 |
| `app/utils.py` | L79-100, L299-302 | 工具函数 |
| `app/dependencies.py` | L55-61 (全局变量) | 依赖注入 |
| `app/factory.py` | L118-213 (lifespan+app创建) | 应用工厂 |
| `app/exceptions.py` | 新建 | 统一异常处理 |
| `app/routers/*.py` (9个) | L423-1783 (路由) | 路由拆分 |

### 3.6 兼容性保证

1. **API 路径不变** — 所有 `/api/*` 路径完全保持不变
2. **启动命令不变** — `uvicorn main:app` 依然有效
3. **环境变量不变** — `.env` 配置方式不变
4. **scripts 兼容** — start.sh/stop.sh/status.sh 无需修改（它们通过 main:app 启动）

### 3.7 内部 import 路径变更影响

各模块间存在内部 import 依赖，移动后需要同步更新：

| 模块 | 原 import | 新 import |
|------|-----------|-----------|
| `market_data_collector.py` | `from binance_collector import` | `from collectors.binance_collector import` |
| `market_data_collector.py` | `from hyperliquid_collector import` | `from collectors.hyperliquid_collector import` |
| `market_data_collector.py` | `from okx_collector import` | `from collectors.okx_collector import` |
| `cmc_collector.py` | `from provider_budget import` | `from core.provider_budget import` |
| `cache_warmer.py` | `from cache import` | `from core.cache import` |
| `coin_analyzer.py` | `from binance_collector import` | `from collectors.binance_collector import` |
| `coin_analyzer.py` | `from config import` | `from core.config import` |
| `cache_warmer.py` (TYPE_CHECKING) | `from binance_collector import` | `from collectors.binance_collector import` |
| `cache_warmer.py` (TYPE_CHECKING) | `from cmc_collector import` | `from collectors.cmc_collector import` |
| `cache_warmer.py` (TYPE_CHECKING) | `from coin_analyzer import` | `from analysis.coin_analyzer import` |
| `strategy_tools.py` | `from config import` | `from core.config import` |

### 3.8 已知 Bug 修复

在文件移动过程中需同时修复以下已知问题：

1. **`normalize_symbol` 递归 Bug**（main.py L299-301）：当前实现会无限递归导致栈溢出。移入 `app/utils.py` 时需修复为正确实现：
   ```python
   def normalize_symbol(symbol: str) -> str:
       """标准化交易对名称：大写 + 确保以 USDT 结尾"""
       symbol = symbol.upper().strip()
       if not symbol.endswith("USDT"):
           symbol += "USDT"
       return symbol
   ```

2. **`get_ai500_symbol` 调用不存在的 `get_coin()` 函数**（main.py L606）：当前代码调用 `await get_coin(symbol=symbol, auth=auth, include=include)`，但实际函数名是 `get_coin_data()`（L814），会导致 `NameError`。重构时需修复此命名错误，并将 `get_coin_data` 的核心数据获取逻辑提取为可复用函数放入 `app/converters.py`，避免跨 router 直接调用路由处理函数。

### 3.9 工具函数归属说明

从 main.py 提取的辅助函数按职责归入不同模块：

| 函数 | 目标模块 | 理由 |
|------|---------|------|
| `normalize_symbol()` | `app/utils.py` | 通用工具函数 |
| `build_auth_metadata()` | `app/auth.py` | 认证相关 |
| `build_cache_warmup_metadata()` | `app/routers/system.py` | 仅被系统状态路由使用 |
| `build_health_checks()` | `app/routers/system.py` | 仅被系统状态路由使用 |
| `build_system_status_payload()` | `app/routers/system.py` | 仅被系统状态路由使用，依赖 collector 和 cache |
| `analysis_to_coin_info()` | `app/converters.py` | 数据转换，被多个 router 共享 |
| `load_cmc_data_for_analyzer()` | `app/converters.py` | 数据加载，被多个 router 共享 |
| 单币数据获取核心逻辑 | `app/converters.py` | 从 `get_coin_data` 路由中提取，供 ai500 和 market_data 共用 |

### 3.10 验证方案

Phase 1 完成后执行以下验证：

1. **语法检查**: `python -m py_compile main.py` + 所有新模块
2. **单元测试**: `python -m pytest tests/ -v`
3. **启动测试**: `python main.py` 确认服务正常启动
4. **API 冒烟测试**: 对关键端点发送请求确认响应正确
   - `GET /health`
   - `GET /api/ai500/list?auth=...`
   - `GET /api/system/status?auth=...`
5. **import 检查**: 确认无循环 import

---

## 4. Phase 2 设计概要：收集器层整理 + 分析拆分

> 待 Phase 1 完成后细化

### 4.1 主要任务

1. **拆分 binance_collector.py (961行)**
   - 纯数据收集 → `collectors/binance_collector.py`
   - ATR/VWAP/支撑阻力计算 → `analysis/technical.py`
   - 重复函数（contains_non_ascii）→ `app/utils.py`

2. **拆分 coin_analyzer.py (1042行)**
   - 评分引擎 → `analysis/scorer.py`
   - 方向判断 → `analysis/direction.py`
   - 入场时机 → `analysis/timing.py`
   - 权重系数 → `core/config.py` (可配置化)

3. **market_data_collector 从继承改为组合**
   - 不再继承 BinanceCollector
   - 通过组合持有各收集器实例

4. **统一去重**
   - `normalize_symbol()` → `app/utils.py`
   - `contains_non_ascii()` → `app/utils.py`

---

## 5. Phase 3 设计概要：缓存 + 配置去硬编码

> 待 Phase 2 完成后细化

### 5.1 主要任务

1. **缓存装饰器**
   ```python
   @cached(key="ai500_list", ttl=settings.cache_ttl_analysis)
   async def get_ai500_list(...):
       ...
   ```

2. **配置参数去硬编码**
   - CoinAnalyzer 权重系数 → `core/config.py`
   - CacheWarmer 预热时机 → `core/config.py`
   - FIXED_WARMUP_COINS → `core/config.py`

3. **缓存中间件**（可选）
   - 基于 URL + 参数的自动缓存
   - 支持 Cache-Control 头

---

## 6. 执行约束

1. **零停机**：每个 Phase 完成后系统必须正常运行
2. **API 兼容**：所有外部 API 路径和响应格式不变
3. **Git 原子性**：每个 Phase 独立提交，方便回滚
4. **同步移动**：源码和对应测试同步移动，避免 import 断裂。执行顺序：
   - 创建目录骨架和所有 `__init__.py`
   - 移动核心基础模块（core/）→ 更新其内部 import
   - 移动收集器和分析模块（collectors/, analysis/, tools/）→ 更新其内部 import
   - 从 main.py 拆分创建 app/ 模块
   - 移动测试文件到 tests/ → 更新测试内部 import
   - 验证全部通过后删除根目录旧文件

### 6.1 旧文件处理

所有迁移文件在确认以下条件后从根目录删除：
- 新路径下所有 import 更新完成
- `python -m pytest tests/ -v` 全部通过
- 服务可正常启动并响应

### 6.2 Python 路径解析

项目根目录作为 Python 包搜索路径的根。`uvicorn main:app` 启动时会自动将 `main.py` 所在目录加入 `sys.path`。每个子目录（`app/`, `core/`, `collectors/`, `analysis/`, `tools/`, `tests/`）都包含 `__init__.py`，确保 Python 能正确解析包路径。无需 `pyproject.toml` 或 `setup.py`。

### 6.3 回滚方案

Phase 1 作为单个 Git commit 提交。如果上线后发现问题：
```bash
git revert <phase1-commit-hash>
# 然后重启服务
bash scripts/stop.sh && bash scripts/start.sh
```
