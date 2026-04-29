# MarketDataService API 接口文档

> 版本: 2.1.0 | 更新日期: 2026-04-13 | 基础地址: `http://127.0.0.1:30007`

---

## 目录

- [认证方式](#认证方式)
- [统一响应格式](#统一响应格式)
- [错误码说明](#错误码说明)
- [接口列表](#接口列表)
  - [1. 系统与健康检查](#1-系统与健康检查)
  - [2. AI500 智能筛选](#2-ai500-智能筛选)
  - [3. OI 持仓量排行](#3-oi-持仓量排行)
  - [4. 单币种综合数据](#4-单币种综合数据)
  - [5. 资金流排行](#5-资金流排行)
  - [6. 价格排行](#6-价格排行)
  - [7. 资金费率](#7-资金费率)
  - [8. 热力图](#8-热力图)
  - [9. 策略分析](#9-策略分析)
  - [10. 市场情绪](#10-市场情绪)
  - [11. 宏观市场数据](#11-宏观市场数据)
  - [12. 策略辅助](#12-策略辅助)
  - [13. 缓存管理](#13-缓存管理)
- [数据模型参考](#数据模型参考)
- [数据源说明](#数据源说明)

---

## 认证方式

除 `GET /` 和 `GET /health` 外，所有接口均需认证。

| 方式 | 说明 |
|------|------|
| **请求头**（推荐） | `X-API-Key: <your_key>` |
| **查询参数**（仅本地回环） | `?auth=<your_key>` |

认证密钥通过环境变量配置，优先级: `NOFXOS_API_KEY` > `NOFX_LOCAL_AUTH_KEY` > 内置默认值。

**认证失败响应:**
```json
{ "detail": "认证失败" }
```
HTTP 状态码: `401`

---

## 统一响应格式

所有业务接口返回统一 JSON 结构:

```json
{
  "success": true,
  "data": { ... }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 请求是否成功 |
| `data` | object | 业务数据，具体结构见各接口说明 |

OI 排行接口额外包含 `code` 字段（兼容 NOFX 格式）:
```json
{
  "success": true,
  "code": 0,
  "data": { ... }
}
```

---

## 错误码说明

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 成功 |
| 400 | 请求参数错误（如不支持的 type 值） |
| 401 | 认证失败 |
| 404 | 资源不存在（如指定币种无数据） |
| 500 | 服务端错误 |

---

## 接口列表

### 1. 系统与健康检查

#### 1.1 GET `/` — 服务信息

获取服务基本信息与可用接口列表。**无需认证。**

**请求参数:** 无

**响应示例:**
```json
{
  "name": "NOFX Local Data Server",
  "version": "2.1.0",
  "status": "running",
  "compatibility_mode": "nofx-core",
  "providers": {
    "binance": true,
    "okx": false,
    "coingecko": true,
    "cmc": true
  },
  "endpoints": {
    "core": {
      "description": "NoFx 核心兼容接口",
      "endpoints": ["/api/ai500/list", "..."]
    },
    "extended": { "..." },
    "macro": { "..." },
    "strategy": { "..." }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 服务名称 |
| `version` | string | 版本号 |
| `status` | string | 运行状态，固定 `"running"` |
| `compatibility_mode` | string | 兼容模式 |
| `providers` | object | 各数据源是否已配置 |
| `endpoints` | object | 按分类分组的接口列表 |

---

#### 1.2 GET `/health` — 健康检查

系统健康状态检查。**无需认证。**

**请求参数:** 无

**响应示例:**
```json
{
  "status": "healthy",
  "timestamp": 1712000000,
  "providers": {
    "binance": {
      "enabled": true,
      "errors": 0,
      "last_success": 1712000000
    }
  },
  "coingecko_api": true,
  "cmc_api": true,
  "auth": {
    "required": false,
    "header": "X-API-Key"
  },
  "cache_warmup": {
    "enabled": true,
    "ttl": 600
  },
  "checks": {
    "collector_initialized": true,
    "provider_count": 2,
    "degraded_providers": []
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"healthy"` 或 `"degraded"` |
| `timestamp` | int | Unix 时间戳（秒） |
| `providers` | object | 各数据提供者的运行状态 |
| `coingecko_api` | boolean | CoinGecko API 是否已配置 |
| `cmc_api` | boolean | CMC API 是否已配置 |
| `checks.collector_initialized` | boolean | 采集器是否初始化完成 |
| `checks.degraded_providers` | array | 处于降级状态的提供者列表 |

---

#### 1.3 GET `/api/system/status` — 系统详细状态

**请求参数:** 无

**响应字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.collector_status` | object | 采集器详细状态 |
| `data.auth` | object | 认证配置信息 |
| `data.cache_warmup` | object | 缓存预热配置 |
| `data.status_cache_ttl` | int | 状态缓存 TTL（秒） |

---

#### 1.4 GET `/api/system/capabilities` — 系统能力

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "core_supported": ["ai500", "oi_ranking", "coin", "price_ranking", "funding_rate", "oi_cap_ranking", "heatmap", "sentiment"],
    "proxy_supported": ["netflow_top_ranking", "netflow_low_ranking", "coin.netflow"],
    "not_fully_supported": ["institution_vs_personal_true_split", "upbit_specific_endpoints"],
    "providers": {
      "market_cap_provider": "coingecko",
      "configured_macro_providers": ["coingecko", "cmc"],
      "okx_enabled": false
    },
    "compatibility_summary": { "..." },
    "timestamp": 1712000000
  }
}
```

---

#### 1.5 GET `/api/system/provider-usage` — API 配额使用

**请求参数:** 无

**响应说明:** 返回各数据提供者的月度/分钟级 API 调用量和配额状态。

---

#### 1.6 GET `/api/system/nofx-compatibility` — NOFX 兼容性映射

**请求参数:** 无

**响应说明:** 返回本服务与官方 NOFX 接口的映射关系和兼容性摘要。

---

#### 1.7 GET `/api/system/strategy-universe` — 策略宇宙配置

**请求参数:** 无

**响应说明:** 返回固定币种池和分析范围配置。

---

#### 1.8 GET `/api/system/nofx-adaptation-checklist` — 适配检查清单

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "items": [{ "..." }],
    "timestamp": 1712000000
  }
}
```

---

### 2. AI500 智能筛选

#### 2.1 GET `/api/ai500/list` — 智能筛选币种列表

获取 AI 筛选的推荐交易币种列表。数据源优先使用 ValueScan（机会币 + 风险币），不可用时回退到本地 CoinAnalyzer 分析。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `direction` | string | 否 | `balanced` | 筛选方向: `long`(做多) / `short`(做空) / `balanced`(多空均衡) / `all`(全部) |
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [
      {
        "pair": "BTCUSDT",
        "score": 82.5,
        "start_time": 1712000000,
        "start_price": 45000.0,
        "last_score": 82.5,
        "max_score": 85.0,
        "max_price": 46200.0,
        "increase_percent": 2.5,
        "direction": "long",
        "confidence": 90.0,
        "price": 46125.0,
        "price_change_1h": 0.5,
        "price_change_24h": 2.5,
        "volatility_24h": 3.2,
        "oi_change_1h": 5.3,
        "oi_value_usd": 50000000.0,
        "funding_rate": 0.015,
        "volume_24h": 25000000000.0,
        "tags": ["DIRECTION:LONG", "TIMING:optimal", "VWAP:breakout_long"],
        "reasons": ["OI 1h 涨 5.3%", "价格突破 VWAP"],
        "vwap_1h": 45900.0,
        "vwap_4h": 45500.0,
        "price_vs_vwap_1h": 0.49,
        "price_vs_vwap_4h": 1.37,
        "vwap_signal": "breakout_long",
        "entry_timing": "optimal",
        "timing_score": 88.0,
        "pullback_pct": 0.2,
        "required_pullback": 1.5,
        "atr_pct": 2.1,
        "support_distance": 3.5,
        "resistance_distance": 2.8,
        "suggested_stop_pct": 3.0,
        "suggested_stop_price": 44761.25,
        "volatility_level": "medium"
      }
    ],
    "count": 20,
    "direction": "balanced",
    "long_count": 10,
    "short_count": 10,
    "source": "valuescan",
    "timestamp": 1712000000
  }
}
```

**`coins[*]` 字段说明:** 见 [CoinInfo 数据模型](#coininfo-数据模型)。

**`data` 顶层字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `coins` | array | CoinInfo 对象数组 |
| `count` | int | 返回币种总数 |
| `direction` | string | 请求的方向参数 |
| `long_count` | int | 做多方向币种数 |
| `short_count` | int | 做空方向币种数 |
| `source` | string | 数据来源: `"valuescan"` 或 `"local_analysis"` |
| `timestamp` | int | Unix 时间戳（秒） |

---

#### 2.2 GET `/api/ai500/{symbol}` — 单币 AI500 详情

获取指定币种的 AI500 视图，包含价格、OI、资金流、AI 评分等综合数据。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | string | 是 | — | 路径参数，交易对名称（如 `BTCUSDT`） |
| `include` | string | 否 | `price,oi,netflow,ai500` | 逗号分隔的数据模块: `price` / `oi` / `netflow` / `ai500` |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "ai500": {
      "score": 82.5,
      "is_active": true,
      "direction": "long",
      "confidence": 90.0,
      "reasons": ["OI 1h 涨 5.3%"],
      "tags": ["DIRECTION:LONG"],
      "entry_timing": "optimal",
      "timing_score": 88.0
    },
    "coin": {
      "symbol": "BTCUSDT",
      "price": 46125.0,
      "price_change": { "1h": 0.005, "4h": 0.025, "24h": 0.025 },
      "oi": { "..." },
      "netflow": { "..." },
      "funding_rate": 0.00015
    },
    "analysis": { "...CoinInfo 全部字段..." },
    "include": ["price", "oi", "netflow", "ai500"],
    "mode": "local_proxy_ai500",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.ai500` | object | AI 评分摘要 |
| `data.ai500.score` | float | 综合评分 0-100 |
| `data.ai500.is_active` | boolean | 是否活跃信号（score >= 70 且方向非 neutral） |
| `data.ai500.direction` | string | `"long"` / `"short"` / `"neutral"` |
| `data.ai500.confidence` | float | 置信度 0-100 |
| `data.ai500.entry_timing` | string | 入场时机评估 |
| `data.ai500.timing_score` | float | 入场时机评分 0-100 |
| `data.coin` | object | 币种基础数据，结构见 [单币种综合数据](#4-单币种综合数据) |
| `data.analysis` | object | 完整 CoinInfo 分析结果 |
| `data.mode` | string | 数据模式标识 |

---

#### 2.3 GET `/api/ai500/stats` — AI500 统计概览

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "universe_count": 50,
    "active_count": 20,
    "active_ratio": 0.4,
    "direction_distribution": {
      "long": 12,
      "short": 8,
      "neutral": 30
    },
    "score_stats": {
      "avg": 65.5,
      "max": 92.3,
      "min": 42.1,
      "active_avg": 75.8
    },
    "mode": "local_proxy_ai500",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `universe_count` | int | 分析宇宙总币种数 |
| `active_count` | int | 活跃信号币种数 |
| `active_ratio` | float | 活跃信号占比 |
| `direction_distribution` | object | 各方向数量分布 |
| `score_stats` | object | 评分统计（均值/最大/最小/活跃均值） |

---

### 3. OI 持仓量排行

#### 3.1 GET `/api/oi/top-ranking` — OI 增加排行

获取指定时间范围内 OI（未平仓合约量）增幅最大的币种排行。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |
| `duration` | string | 否 | `1h` | 时间范围: `1m` / `5m` / `15m` / `30m` / `1h` / `4h` / `8h` / `12h` / `24h` / `1d` / `2d` / `3d` |

**响应示例:**
```json
{
  "success": true,
  "code": 0,
  "data": {
    "positions": [
      {
        "rank": 1,
        "symbol": "BTCUSDT",
        "current_oi": 123456.78,
        "oi_delta": 5000.0,
        "oi_delta_percent": 4.13,
        "oi_delta_value": 230000000.0,
        "price_delta_percent": 2.5,
        "net_long": 0,
        "net_short": 0
      }
    ],
    "count": 20,
    "exchange": "binance",
    "rank_type": "top",
    "time_range": "1小时",
    "time_range_param": "1h",
    "limit": 20
  }
}
```

**`positions[*]` 字段说明:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `rank` | int | 排名（1 开始） |
| `symbol` | string | 交易对名称 |
| `current_oi` | float | 当前 OI 数量（币量） |
| `oi_delta` | float | OI 变化数量 |
| `oi_delta_percent` | float | OI 变化百分比（%） |
| `oi_delta_value` | float | OI 变化价值（USD） |
| `price_delta_percent` | float | 对应时间段价格变化（%） |
| `net_long` | float | 多头净头寸 |
| `net_short` | float | 空头净头寸 |

---

#### 3.2 GET `/api/oi/low-ranking` — OI 减少排行

参数和响应结构同 `/api/oi/top-ranking`，`rank_type` 为 `"low"`，按 OI 减少幅度排序。

---

#### 3.3 GET `/api/oi/top` — OI Top 20（快捷接口）

固定参数的快捷接口，等同于 `/api/oi/top-ranking?limit=20&duration=1h`。

**请求参数:** 无

---

#### 3.4 GET `/api/oi-cap/ranking` — OI/市值比排行

按 OI 占市值比例排序，用于发现 OI 相对市值异常偏高的币种。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "rows": [
      {
        "symbol": "BTCUSDT",
        "oi": 123456.78,
        "market_cap": 900000000000.0,
        "market_cap_rank": 1,
        "oi_cap_ratio": 0.000137
      }
    ],
    "count": 20,
    "timestamp": 1712000000,
    "market_cap_provider": "coingecko"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `rows[*].symbol` | string | 交易对名称 |
| `rows[*].oi` | float | 当前 OI（币量） |
| `rows[*].market_cap` | float | 市值（USD） |
| `rows[*].market_cap_rank` | int | 市值排名 |
| `rows[*].oi_cap_ratio` | float | OI/市值比 |
| `market_cap_provider` | string | 市值数据来源（`"coingecko"` 或 `"cmc"`） |

---

### 4. 单币种综合数据

#### 4.1 GET `/api/coin/{symbol}` — 单币种综合数据

获取指定币种的价格、OI、资金流、资金费率等综合数据。资金流优先使用 ValueScan 链上数据，不可用时回退到 Binance Taker Imbalance 代理。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | string | 是 | — | 路径参数，交易对名称（如 `BTCUSDT`） |
| `include` | string | 否 | `netflow,oi,price` | 逗号分隔的数据模块: `price` / `oi` / `netflow` / `ai500` |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "price": 46125.0,
    "price_change": {
      "1m": 0.001,
      "5m": 0.003,
      "15m": 0.008,
      "30m": 0.012,
      "1h": 0.005,
      "4h": 0.025,
      "8h": 0.018,
      "12h": 0.032,
      "24h": 0.025
    },
    "oi": {
      "binance": {
        "current_oi": 123456.78,
        "oi_value": 5694000000.0,
        "net_long": 55000000.0,
        "net_short": 45000000.0,
        "delta": {
          "1h": {
            "oi_delta": 5000.0,
            "oi_delta_value": 230000000.0,
            "oi_delta_percent": 0.0413
          }
        }
      }
    },
    "netflow": {
      "institution": {
        "future": { "5m": 1000000.0, "15m": 2500000.0, "1h": 5000000.0 },
        "spot": { "5m": 500000.0, "15m": 1200000.0, "1h": 2500000.0 }
      },
      "personal": {
        "future": {},
        "spot": {}
      },
      "breakdown": {
        "future_flow": 5000000.0,
        "spot_flow": 2500000.0,
        "amount": 7500000.0,
        "spot_max_accumulation": 10000000.0,
        "contract_max_accumulation": 20000000.0
      },
      "mode": "valuescan_fund_flow"
    },
    "funding_rate": 0.015,
    "ai500": {
      "score": 82.5,
      "is_active": true,
      "direction": "long",
      "confidence": 90.0
    }
  }
}
```

**`data` 字段说明:**

| 字段 | 类型 | include 条件 | 说明 |
|------|------|-------------|------|
| `symbol` | string | 始终 | 交易对名称 |
| `price` | float | 始终 | 当前价格 |
| `price_change` | object | `price` | 各时间段涨跌幅（小数形式，0.01 = 1%） |
| `oi` | object | `oi` | 各交易所 OI 数据 |
| `netflow` | object | `netflow` | 资金流数据 |
| `funding_rate` | float | 始终 | 资金费率（%，如 0.015 表示 0.015%） |
| `ai500` | object | `ai500` | AI 评分数据 |

**`oi.{exchange}` 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `current_oi` | float | 当前 OI 数量（币量） |
| `oi_value` | float | OI 价值（USD） |
| `net_long` | float | 多头净头寸（USD） |
| `net_short` | float | 空头净头寸（USD） |
| `delta.{timeframe}` | object | 指定时间段的 OI 变化 |
| `delta.{timeframe}.oi_delta` | float | OI 变化数量 |
| `delta.{timeframe}.oi_delta_value` | float | OI 变化价值（USD） |
| `delta.{timeframe}.oi_delta_percent` | float | OI 变化百分比（小数形式） |

**`netflow` 字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `institution.future` | object | 机构合约资金流，key 为时间周期（`5m`/`15m`/`1h`/`4h`/`1d`），value 为资金量（USD） |
| `institution.spot` | object | 机构现货资金流，结构同上 |
| `personal.future` | object | 散户合约资金流（ValueScan 模式下为空） |
| `personal.spot` | object | 散户现货资金流（ValueScan 模式下为空） |
| `breakdown.future_flow` | float | 合约 1h 资金流总量 |
| `breakdown.spot_flow` | float | 现货 1h 资金流总量 |
| `breakdown.amount` | float | 1h 总资金流量 |
| `breakdown.spot_max_accumulation` | float | 现货最大累计流入（仅 ValueScan） |
| `breakdown.contract_max_accumulation` | float | 合约最大累计流入（仅 ValueScan） |
| `mode` | string | 数据模式: `"valuescan_fund_flow"` 或 `"proxy_taker_imbalance"` |

---

### 5. 资金流排行

#### 5.1 GET `/api/netflow/top-ranking` — 资金流入排行

基于 Binance Taker Buy/Sell 数据计算的资金流代理排行。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |
| `duration` | string | 否 | `1h` | 时间范围 |
| `type` | string | 否 | `proxy` | 数据类型，当前仅支持 `proxy` |
| `trade` | string | 否 | `all` | 交易类型: `all` / `future` / `spot` |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "rows": [
      {
        "rank": 1,
        "symbol": "BTCUSDT",
        "netflow": 5000000.0,
        "netflow_pct": 0.5
      }
    ],
    "count": 20,
    "duration": "1h",
    "trade": "all",
    "type": "proxy",
    "mode": "proxy_taker_imbalance",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `rows[*].rank` | int | 排名 |
| `rows[*].symbol` | string | 交易对名称 |
| `rows[*].netflow` | float | 净资金流量（USD），正值为流入 |
| `rows[*].netflow_pct` | float | 资金流占成交量百分比 |
| `mode` | string | 固定 `"proxy_taker_imbalance"` |

---

#### 5.2 GET `/api/netflow/low-ranking` — 资金流出排行

参数和响应结构同 `/api/netflow/top-ranking`，按资金流出排序。

---

### 6. 价格排行

#### 6.1 GET `/api/price/ranking` — 价格涨跌排行

该接口只读取缓存预热结果，不在请求链路中实时计算排行。缓存预热器会定时生成 `1h`、`4h`、`24h` 三个周期；如果缓存过期但仍有上一版数据，会继续返回旧缓存；如果服务刚启动或缓存完全未就绪，接口返回 `503`，`detail` 为 `price_ranking_warming_up`。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `duration` | string | 否 | `1h` | 时间范围 |
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |

**缓存未就绪响应:**
```json
{
  "detail": "price_ranking_warming_up"
}
```

**响应示例:**
```json
{
  "success": true,
  "data": {
    "rows": [
      {
        "rank": 1,
        "symbol": "SOLUSDT",
        "price_change_percent": 5.23
      }
    ],
    "count": 20,
    "duration": "1h",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `rows[*].rank` | int | 排名 |
| `rows[*].symbol` | string | 交易对名称 |
| `rows[*].price_change_percent` | float | 价格变化百分比（%） |

---

### 7. 资金费率

#### 7.1 GET `/api/funding-rate/top` — 资金费率最高排行

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "rows": [
      {
        "rank": 1,
        "symbol": "BTCUSDT",
        "funding_rate": 0.025
      }
    ],
    "count": 20,
    "rank_type": "top",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `rows[*].symbol` | string | 交易对名称 |
| `rows[*].funding_rate` | float | 资金费率（%） |
| `rank_type` | string | `"top"` 或 `"low"` |

---

#### 7.2 GET `/api/funding-rate/low` — 资金费率最低排行

参数和响应结构同 `/api/funding-rate/top`，`rank_type` 为 `"low"`。

---

#### 7.3 GET `/api/funding-rate/{symbol}` — 单币资金费率

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | string | 是 | — | 路径参数，交易对名称 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "funding_rate": 0.015,
    "mark_price": 46125.0,
    "next_funding_time": "2026-04-13T08:00:00Z",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `funding_rate` | float | 资金费率（%，已乘以 100） |
| `mark_price` | float | 标记价格 |
| `next_funding_time` | string | 下次结算时间 |

---

### 8. 热力图

#### 8.1 GET `/api/heatmap/future/{symbol}` — 合约热力图

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | string | 是 | — | 路径参数，交易对名称 |

**响应:** `{"success": true, "data": {...}}` — 热力图数据结构取决于采集器实现。

---

#### 8.2 GET `/api/heatmap/spot/{symbol}` — 现货热力图

参数和响应结构同 `/api/heatmap/future/{symbol}`。

---

#### 8.3 GET `/api/heatmap/list` — 热力图列表

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `trade` | string | 否 | `future` | 市场类型: `future` / `spot` |
| `limit` | int | 否 | 20 | 返回数量，范围 1-100 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "rows": [{ "..." }],
    "count": 20,
    "trade": "future",
    "timestamp": 1712000000
  }
}
```

---

### 9. 策略分析

#### 9.1 GET `/api/analysis/long` — 做多候选

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-50 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [{ "...CoinInfo..." }],
    "count": 20,
    "direction": "long",
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

`coins[*]` 字段见 [CoinInfo 数据模型](#coininfo-数据模型)。

---

#### 9.2 GET `/api/analysis/short` — 做空候选

参数和响应结构同 `/api/analysis/long`，`direction` 为 `"short"`。

---

#### 9.3 GET `/api/analysis/flash-crash` — 闪崩风险币种

适合在反弹时做空埋伏的高风险币种。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-50 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [{ "...CoinInfo..." }],
    "count": 5,
    "type": "flash_crash_risk",
    "timestamp": 1712000000,
    "description": "这些币种有闪崩风险，适合在反弹时做空埋伏"
  }
}
```

---

#### 9.4 GET `/api/analysis/high-volatility` — 高波动币种

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-50 |
| `min_volatility` | float | 否 | 5.0 | 最小 24h 波动率阈值（%） |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [{ "...CoinInfo..." }],
    "count": 15,
    "type": "high_volatility",
    "min_volatility": 5.0,
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

---

#### 9.5 GET `/api/analysis/early-signals` — 早期信号

基于 VWAP 偏离的早期信号，用于提前布局避免追高。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-50 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [{ "...CoinInfo..." }],
    "count": 12,
    "type": "early_signals",
    "signal_distribution": {
      "early_long": 4,
      "early_short": 3,
      "breakout_long": 3,
      "breakout_short": 2
    },
    "timestamp": 1712000000,
    "description": "基于 VWAP 的早期信号，用于提前布局避免追高"
  }
}
```

**VWAP 信号类型说明:**

| 信号 | 说明 |
|------|------|
| `early_long` | 价格低于 VWAP 但 OI 增加（资金悄悄进场） |
| `early_short` | 价格高于 VWAP 且资金费率偏高（可能回调） |
| `breakout_long` | 价格刚向上突破 VWAP |
| `breakout_short` | 价格刚向下跌破 VWAP |

---

#### 9.6 GET `/api/analysis/market-overview` — 市场概览

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "binance": {
      "total_coins": 50,
      "long_candidates": 18,
      "short_candidates": 20,
      "neutral": 12,
      "high_volatility": 8,
      "flash_crash_risk": 3,
      "market_sentiment": "bearish",
      "sentiment_description": "空头占优，short_candidates > long_candidates"
    },
    "global": {
      "fear_greed_index": 35,
      "sentiment": "fear",
      "total_market_cap": 1200000000000.0,
      "btc_dominance": 45.5,
      "eth_dominance": 18.2
    },
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `binance.market_sentiment` | string | `"bullish"` / `"neutral"` / `"bearish"` |
| `global.fear_greed_index` | float | 恐惧贪婪指数 0-100 |
| `global.sentiment` | string | `"extreme_fear"` / `"fear"` / `"neutral"` / `"greed"` / `"extreme_greed"` |
| `global.total_market_cap` | float | 总市值（USD） |
| `global.btc_dominance` | float | BTC 市值占比（%） |

---

### 10. 市场情绪

#### 10.1 GET `/api/sentiment/fear-greed` — 恐惧贪婪指数

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `history` | int | 否 | 0 | 历史天数，范围 0-30，0 表示仅返回当前值 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "current": {
      "value": 65,
      "classification": "Greed",
      "timestamp": 1712000000
    },
    "history": [
      { "value": 64, "classification": "Greed", "timestamp": 1711913600 }
    ],
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

**恐惧贪婪分类:**

| 区间 | 分类 |
|------|------|
| 0-24 | Extreme Fear（极度恐惧） |
| 25-44 | Fear（恐惧） |
| 45-55 | Neutral（中性） |
| 56-75 | Greed（贪婪） |
| 76-100 | Extreme Greed（极度贪婪） |

---

#### 10.2 GET `/api/sentiment/market` — 综合市场情绪

**请求参数:** 无

**响应说明:** 返回综合市场情绪数据，包含恐惧贪婪指数、市值、BTC 主导率等。

---

### 11. 宏观市场数据

数据源优先使用 CoinGecko Demo API，不可用时切换到 CMC。

#### 11.1 GET `/api/cmc/listings` — 市值排名列表

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 100 | 返回数量，范围 1-200 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [
      {
        "symbol": "BTC",
        "name": "Bitcoin",
        "rank": 1,
        "price": 46125.0,
        "market_cap": 900000000000.0,
        "volume_24h": 25000000000.0,
        "percent_change_1h": 0.5,
        "percent_change_24h": 2.5,
        "percent_change_7d": 8.3,
        "circulating_supply": 19600000.0,
        "total_supply": 21000000.0
      }
    ],
    "count": 100,
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `coins[*].symbol` | string | 币种符号（如 `BTC`） |
| `coins[*].name` | string | 币种名称 |
| `coins[*].rank` | int | 市值排名 |
| `coins[*].price` | float | 当前价格（USD） |
| `coins[*].market_cap` | float | 市值（USD） |
| `coins[*].volume_24h` | float | 24 小时交易量（USD） |
| `coins[*].percent_change_1h` | float | 1 小时涨跌幅（%） |
| `coins[*].percent_change_24h` | float | 24 小时涨跌幅（%） |
| `coins[*].percent_change_7d` | float | 7 天涨跌幅（%） |
| `coins[*].circulating_supply` | float | 流通供应量 |
| `coins[*].total_supply` | float | 总供应量 |
| `provider` | string | 数据来源: `"coingecko"` 或 `"cmc"` |

---

#### 11.2 GET `/api/cmc/trending` — 热门币种

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-50 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "coins": [
      {
        "symbol": "SOL",
        "name": "Solana",
        "rank": 5,
        "price": 120.0,
        "percent_change_24h": 5.2,
        "trending_score": 85.5
      }
    ],
    "count": 20,
    "type": "trending",
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

---

#### 11.3 GET `/api/cmc/gainers-losers` — 涨跌幅排行

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回数量，范围 1-50 |
| `time_period` | string | 否 | `24h` | 时间周期: `1h` / `24h` / `7d` / `30d` |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "gainers": [
      { "symbol": "SOL", "name": "Solana", "rank": 5, "price": 120.0, "percent_change_24h": 5.2 }
    ],
    "losers": [
      { "symbol": "ADA", "name": "Cardano", "rank": 8, "price": 0.85, "percent_change_24h": -3.2 }
    ],
    "time_period": "24h",
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

---

#### 11.4 GET `/api/cmc/market-overview` — 全市场概览

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "total_market_cap": 1200000000000.0,
    "total_volume_24h": 50000000000.0,
    "btc_dominance": 45.5,
    "eth_dominance": 18.2,
    "active_cryptocurrencies": 25000,
    "market_cap_change_24h": 2.5,
    "volume_change_24h": 5.2,
    "provider": "coingecko",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_market_cap` | float | 加密市场总市值（USD） |
| `total_volume_24h` | float | 24 小时总交易量（USD） |
| `btc_dominance` | float | BTC 市值占比（%） |
| `eth_dominance` | float | ETH 市值占比（%） |
| `active_cryptocurrencies` | int | 活跃加密货币数量 |
| `market_cap_change_24h` | float | 24h 市值变化（%） |
| `volume_change_24h` | float | 24h 交易量变化（%） |

---

### 12. 策略辅助

#### 12.1 GET `/api/strategy/pair-neutral/template` — 配对中性策略模板

获取配对交易策略模板定义，包含回测字段规范。

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "template": {
      "pair_name": "BTC-ETH Neutral",
      "symbol_a": "BTCUSDT",
      "symbol_b": "ETHUSDT",
      "entry_ratio": 0.08,
      "exit_ratio": 0.07,
      "hedge_ratio": 1.0,
      "stops": ["..."]
    },
    "backtest_fields": [
      "timestamp", "leg_a_price", "leg_b_price", "ratio",
      "signal", "pnl"
    ],
    "fixed_universe": { "..." },
    "timestamp": 1712000000
  }
}
```

---

#### 12.2 GET `/api/strategy/pair-neutral/context` — 配对策略历史上下文

获取配对交易的历史价格、比率、波动率和相关性数据。

**请求参数:**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol_a` | string | 否 | `BTCUSDT` | 腿 A 交易对 |
| `symbol_b` | string | 否 | `ETHUSDT` | 腿 B 交易对 |
| `lookback_bars` | int | 否 | 288 | 回看 K 线数量，范围 48-2000 |
| `interval` | string | 否 | `15m` | K 线周期 |

**响应示例:**
```json
{
  "success": true,
  "data": {
    "pairs": [
      {
        "timestamp": 1712000000,
        "leg_a_price": 46125.0,
        "leg_b_price": 2650.0,
        "ratio": 17.41,
        "leg_a_sma": 46000.0,
        "leg_b_sma": 2640.0,
        "ratio_sma": 17.42,
        "leg_a_vol": 2.3,
        "leg_b_vol": 2.1,
        "correlation": 0.95
      }
    ],
    "stats": {
      "ratio_mean": 17.4,
      "ratio_std": 0.5,
      "correlation": 0.95
    },
    "symbol_a": "BTCUSDT",
    "symbol_b": "ETHUSDT",
    "lookback_bars": 288,
    "interval": "15m",
    "timestamp": 1712000000
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `pairs[*].ratio` | float | 腿 A / 腿 B 价格比率 |
| `pairs[*].ratio_sma` | float | 比率 SMA 均线 |
| `pairs[*].leg_a_vol` | float | 腿 A 波动率 |
| `pairs[*].correlation` | float | 两腿相关性 |
| `stats.ratio_mean` | float | 比率均值 |
| `stats.ratio_std` | float | 比率标准差 |

---

### 13. 缓存管理

#### 13.1 GET `/api/cache/status` — 缓存状态

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "data": {
    "enabled": true,
    "ttl": 600,
    "stats": {
      "hit_count": 1250,
      "miss_count": 150,
      "hit_rate": 0.893
    },
    "entries": [
      { "key": "ai500:list:balanced", "ttl_remaining": 580 }
    ],
    "warmer": {
      "running": true,
      "last_warmup": 1712000000
    },
    "timestamp": 1712000000
  }
}
```

---

#### 13.2 POST `/api/cache/warmup` — 手动触发预热

**请求参数:** 无（POST body 为空）

**响应说明:** 返回预热结果详情，包含各缓存键的更新状态和耗时。

---

#### 13.3 DELETE `/api/cache/clear` — 清空缓存

**请求参数:** 无

**响应示例:**
```json
{
  "success": true,
  "message": "缓存已清空"
}
```

---

## 数据模型参考

### CoinInfo 数据模型

所有返回 `coins` 数组的接口（AI500、分析策略等）共用 CoinInfo 结构:

#### 基础字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `pair` | string | 交易对名称（如 `BTCUSDT`） |
| `score` | float | 综合评分 0-100 |
| `start_time` | int | 信号生成时间戳（Unix 秒） |
| `start_price` | float | 信号生成时的价格 |
| `last_score` | float | 最近一次评分 |
| `max_score` | float | 历史最高评分 |
| `max_price` | float | 历史最高价格 |
| `increase_percent` | float | 涨幅百分比 |

#### 方向与信心

| 字段 | 类型 | 说明 |
|------|------|------|
| `direction` | string | 推荐方向: `"long"` / `"short"` / `"neutral"` |
| `confidence` | float | 置信度 0-100 |

#### 价格与波动

| 字段 | 类型 | 说明 |
|------|------|------|
| `price` | float | 当前价格 |
| `price_change_1h` | float | 1 小时价格变化（%） |
| `price_change_24h` | float | 24 小时价格变化（%） |
| `volatility_24h` | float | 24 小时波动率（%） |

#### 衍生品指标

| 字段 | 类型 | 说明 |
|------|------|------|
| `oi_change_1h` | float | OI 1 小时变化（%） |
| `oi_value_usd` | float | OI 价值（USD） |
| `funding_rate` | float | 资金费率 |
| `volume_24h` | float | 24 小时交易量（USD） |

#### 标签与原因

| 字段 | 类型 | 说明 |
|------|------|------|
| `tags` | array[string] | 标签列表，格式: `TIMING:optimal`、`DIRECTION:LONG`、`VWAP:breakout_long`、`VS:alpha` |
| `reasons` | array[string] | 分析原因的中文描述列表 |

#### VWAP 相关（本地分析源）

| 字段 | 类型 | 说明 |
|------|------|------|
| `vwap_1h` | float | 1 小时 VWAP 值 |
| `vwap_4h` | float | 4 小时 VWAP 值 |
| `price_vs_vwap_1h` | float | 价格相对 1h VWAP 偏离（%） |
| `price_vs_vwap_4h` | float | 价格相对 4h VWAP 偏离（%） |
| `vwap_signal` | string | VWAP 信号: `early_long` / `early_short` / `breakout_long` / `breakout_short` |

#### 入场时机（本地分析源）

| 字段 | 类型 | 说明 |
|------|------|------|
| `entry_timing` | string | 入场时机: `optimal`(最佳) / `wait_pullback`(等回调) / `chasing`(追高) / `extended`(过度延伸) |
| `timing_score` | float | 入场时机评分 0-100 |
| `pullback_pct` | float | 实际回调/反弹幅度（%） |
| `required_pullback` | float | 建议回调幅度（%） |
| `atr_pct` | float | ATR 占价格百分比（波动性指标） |
| `support_distance` | float | 距支撑位距离（%） |
| `resistance_distance` | float | 距阻力位距离（%） |

#### 动态止损建议（本地分析源）

| 字段 | 类型 | 说明 |
|------|------|------|
| `suggested_stop_pct` | float | 建议止损幅度（%） |
| `suggested_stop_price` | float | 建议止损价格 |
| `volatility_level` | string | 波动等级: `low` / `medium` / `high` / `extreme` |

#### ValueScan 专有字段（source="valuescan" 时）

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 固定 `"valuescan"` |
| `vs_cost` | float | 主力成本价 |
| `vs_deviation` | float | 当前价格偏离主力成本的百分比 |
| `vs_grade` | int | ValueScan 评级: 1(一般) / 2(较好) / 3(优秀) |

---

## 数据源说明

### 主数据源与回退机制

| 数据类型 | 主数据源 | 回退数据源 |
|---------|---------|-----------|
| AI500 智能筛选 | ValueScan (机会币 + 风险币) | 本地 CoinAnalyzer 分析 |
| 单币资金流 | ValueScan getCoinTrade | Binance Taker Imbalance 代理 |
| OI / 价格 / 资金费率 | Binance | OKX（如已配置） |
| 宏观市场数据 | CoinGecko Demo API | CMC API |

### ValueScan 积分预算

- 每次 AI/Trade 接口调用消耗 **3 积分**
- Token 列表接口消耗 **1 积分**
- 默认月预算: **50,000 积分**
- AI500 预热间隔: **10 分钟**（每次消耗 6 积分，约 26,000 积分/月）
- 预算耗尽时自动回退到本地分析

---

## 接口速查表

| 接口 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/` | GET | 否 | 服务信息 |
| `/health` | GET | 否 | 健康检查 |
| `/api/system/status` | GET | 是 | 系统状态 |
| `/api/system/capabilities` | GET | 是 | 系统能力 |
| `/api/system/provider-usage` | GET | 是 | API 配额 |
| `/api/system/nofx-compatibility` | GET | 是 | 兼容性映射 |
| `/api/system/strategy-universe` | GET | 是 | 策略宇宙 |
| `/api/system/nofx-adaptation-checklist` | GET | 是 | 适配清单 |
| `/api/ai500/list` | GET | 是 | AI 智能筛选列表 |
| `/api/ai500/{symbol}` | GET | 是 | 单币 AI500 详情 |
| `/api/ai500/stats` | GET | 是 | AI500 统计 |
| `/api/oi/top-ranking` | GET | 是 | OI 增加排行 |
| `/api/oi/low-ranking` | GET | 是 | OI 减少排行 |
| `/api/oi/top` | GET | 是 | OI Top 20 |
| `/api/oi-cap/ranking` | GET | 是 | OI/市值比排行 |
| `/api/coin/{symbol}` | GET | 是 | 单币综合数据 |
| `/api/netflow/top-ranking` | GET | 是 | 资金流入排行 |
| `/api/netflow/low-ranking` | GET | 是 | 资金流出排行 |
| `/api/price/ranking` | GET | 是 | 价格涨跌排行 |
| `/api/funding-rate/top` | GET | 是 | 费率最高排行 |
| `/api/funding-rate/low` | GET | 是 | 费率最低排行 |
| `/api/funding-rate/{symbol}` | GET | 是 | 单币资金费率 |
| `/api/heatmap/future/{symbol}` | GET | 是 | 合约热力图 |
| `/api/heatmap/spot/{symbol}` | GET | 是 | 现货热力图 |
| `/api/heatmap/list` | GET | 是 | 热力图列表 |
| `/api/analysis/long` | GET | 是 | 做多候选 |
| `/api/analysis/short` | GET | 是 | 做空候选 |
| `/api/analysis/flash-crash` | GET | 是 | 闪崩风险 |
| `/api/analysis/high-volatility` | GET | 是 | 高波动币种 |
| `/api/analysis/early-signals` | GET | 是 | 早期信号 |
| `/api/analysis/market-overview` | GET | 是 | 市场概览 |
| `/api/sentiment/fear-greed` | GET | 是 | 恐惧贪婪指数 |
| `/api/sentiment/market` | GET | 是 | 综合情绪 |
| `/api/cmc/listings` | GET | 是 | 市值排名 |
| `/api/cmc/trending` | GET | 是 | 热门币种 |
| `/api/cmc/gainers-losers` | GET | 是 | 涨跌排行 |
| `/api/cmc/market-overview` | GET | 是 | 全市场概览 |
| `/api/strategy/pair-neutral/template` | GET | 是 | 配对策略模板 |
| `/api/strategy/pair-neutral/context` | GET | 是 | 配对策略上下文 |
| `/api/cache/status` | GET | 是 | 缓存状态 |
| `/api/cache/warmup` | POST | 是 | 手动预热 |
| `/api/cache/clear` | DELETE | 是 | 清空缓存 |
