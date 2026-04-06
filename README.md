# NOFX 本地数据服务器

本地数据服务器提供与官方 nofxaios.com API 兼容的接口，同时增加多空分类筛选、闪崩风险识别等增强功能。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    NOFX Local Data Server                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐    ┌──────────────────────────────┐  │
│  │  Binance API     │    │  辅助数据源                   │  │
│  │  (主数据源)       │    │                              │  │
│  │                  │    │  ┌────────────────────────┐  │  │
│  │  - 合约行情      │    │  │ 恐惧贪婪指数 (免费)     │  │  │
│  │  - OI 持仓量     │    │  │ alternative.me/fng     │  │  │
│  │  - 资金费率      │    │  └────────────────────────┘  │  │
│  │  - K线数据       │    │                              │  │
│  │                  │    │  ┌────────────────────────┐  │  │
│  └──────────────────┘    │  │ CMC API (可选)         │  │  │
│          │               │  │ - 全网市值             │  │  │
│          ▼               │  │ - BTC/ETH 主导率       │  │  │
│  ┌──────────────────┐    │  │ - 涨跌幅排行           │  │  │
│  │  币种分析器      │    │  └────────────────────────┘  │  │
│  │                  │    └──────────────────────────────┘  │
│  │  - 多空分类      │                 │                    │
│  │  - 闪崩风险      │                 │                    │
│  │  - 评分系统      │                 ▼                    │
│  └──────────────────┘    ┌──────────────────────────────┐  │
│          │               │  市场情绪分析                 │  │
│          │               │  - 综合恐惧贪婪               │  │
│          │               │  - 山寨季指数                 │  │
│          │               │  - 市场趋势判断               │  │
│          │               └──────────────────────────────┘  │
│          │                           │                      │
│          └───────────────────────────┘                      │
│                          │                                  │
│                          ▼                                  │
│                 ┌─────────────────┐                         │
│                 │  FastAPI Server │                         │
│                 │  :30007         │                         │
│                 └─────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

**设计原则**:
- **Binance 为主，CMC 为辅**: 策略跑在 Binance 上，数据以 Binance 为准
- **CMC 异常不影响主流程**: 所有 CMC 调用都有异常保护
- **恐惧贪婪指数免费可用**: 不需要 CMC key 也能获取市场情绪

## 快速开始

### 环境要求
- Python 3.10+
- 虚拟环境（自动创建）

### 服务器管理

```bash
cd /home/admin/AI/nofx/data/local_data_server

# 启动服务器（后台运行）
./start.sh

# 查看运行状态
./status.sh

# 停止服务器
./stop.sh

# 查看实时日志
tail -f server.log
```

服务器将在 `http://localhost:30007` 后台运行。

| 脚本 | 功能 |
|------|------|
| `start.sh` | 后台启动服务器，自动管理 PID |
| `stop.sh` | 停止服务器 |
| `status.sh` | 查看状态、端口、API 健康检查 |

### 环境变量配置

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `BINANCE_API_KEY_READONLY` | 可选 | Binance 只读 API Key（提高请求限额） |
| `BINANCE_API_SECRET_READONLY` | 可选 | Binance 只读 API Secret |
| `CMC_PRO_API_KEY` | 可选 | CoinMarketCap API 密钥（启用 CMC 高级功能） |

**注意**:
- Binance 公开 API 无需 Key 即可使用，但有请求限频
- 恐惧贪婪指数使用 alternative.me 免费 API，无需任何 Key
- CMC API 可选，用于获取全网市值、BTC 主导率等数据

---

## API 接口文档

### 认证

所有接口需要传入 `auth` 参数：
```
?auth=cm_568c67eae410d912c54c
```

---

## 一、Binance 数据接口（主数据源）

### 1. AI500 智能筛选列表

**GET** `/api/ai500/list`

获取智能筛选的币种列表，支持按方向筛选。

**参数**:
| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| auth | string | 是 | - | 认证密钥 |
| direction | string | 否 | balanced | 筛选方向: `long`/`short`/`balanced`/`all` |
| limit | int | 否 | 20 | 返回数量 (1-100) |

**direction 参数说明**:
| 值 | 说明 |
|----|------|
| `balanced` | 多空平衡模式（默认），偶数各半，奇数空多一个【推荐】 |
| `long` | 只返回做多候选 |
| `short` | 只返回做空候选 |
| `all` | 返回所有分析结果，不做平衡 |

**示例**:
```bash
curl "http://localhost:30007/api/ai500/list?auth=cm_568c67eae410d912c54c&direction=balanced&limit=10"
```

**响应字段说明**:
| 字段 | 说明 |
|------|------|
| `pair` | 交易对符号 |
| `score` | 综合评分（0-100） |
| `direction` | 方向: long/short/neutral |
| `confidence` | 置信度（0-100） |
| `price` | 当前价格 |
| `price_change_1h` | 1小时涨跌幅 (%) |
| `price_change_24h` | 24小时涨跌幅 (%) |
| `volatility_24h` | 24小时波动率 (%) |
| `oi_change_1h` | 1小时 OI 变化 (%) |
| `oi_value_usd` | OI 价值（USD），用于验证流动性 |
| `funding_rate` | 资金费率 |
| `vwap_1h` | 1小时 VWAP |
| `vwap_4h` | 4小时 VWAP |
| `price_vs_vwap_1h` | 价格相对于 1h VWAP 偏离度 (%) |
| `price_vs_vwap_4h` | 价格相对于 4h VWAP 偏离度 (%) |
| `vwap_signal` | VWAP 信号类型 |
| `tags` | 币种标签列表 |
| `reasons` | 分类原因列表 |

**响应示例**:
```json
{
  "success": true,
  "data": {
    "coins": [
      {
        "pair": "BTCUSDT",
        "score": 85.5,
        "direction": "long",
        "confidence": 75.0,
        "price": 87000.0,
        "vwap_1h": 86500.0,
        "vwap_4h": 86000.0,
        "price_vs_vwap_1h": 0.58,
        "price_vs_vwap_4h": 1.16,
        "vwap_signal": "breakout_long",
        "tags": ["cmc_trending"],
        "reasons": ["价格上涨 + OI 增加"]
      }
    ],
    "count": 10,
    "direction": "balanced",
    "long_count": 5,
    "short_count": 5,
    "timestamp": 1767110000
  }
```

### 2. 做空候选 `/api/analysis/short`

### 3. 做多候选 `/api/analysis/long`

### 4. 早期信号 `/api/analysis/early-signals`

基于 VWAP 分析的早期信号识别，用于在动量确认之前提前布局。

**参数**:
| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| auth | string | 是 | - | 认证密钥 |
| limit | int | 否 | 20 | 返回数量 (1-50) |

**VWAP 信号类型**:
| 信号 | 说明 |
|------|------|
| `early_long` | 价格低于 VWAP 但 OI 增加（资金悄悄进场） |
| `early_short` | 价格高于 VWAP 且资金费率偏高（可能回调） |
| `breakout_long` | 价格刚向上突破 VWAP |
| `breakout_short` | 价格刚向下跌破 VWAP |

**响应示例**:
```json
{
  "success": true,
  "data": {
    "coins": [...],
    "count": 15,
    "type": "early_signals",
    "signal_distribution": {
      "early_long": 5,
      "early_short": 6,
      "breakout_long": 2,
      "breakout_short": 2
    },
    "timestamp": 1767110000,
    "description": "基于 VWAP 的早期信号，用于提前布局避免追高"
  }
}
```

### 5. 闪崩风险 `/api/analysis/flash-crash`

### 6. 高波动币种 `/api/analysis/high-volatility`

### 7. OI 排行 `/api/oi/top-ranking` `/api/oi/low-ranking`

### 8. 单币种数据 `/api/coin/{symbol}`

---

## 二、市场情绪接口（免费，无需 CMC key）

### 1. 恐惧贪婪指数

**GET** `/api/sentiment/fear-greed`

获取恐惧贪婪指数，使用 alternative.me 免费 API。

**参数**:
| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| auth | string | 是 | - | 认证密钥 |
| history | int | 否 | 0 | 历史天数（0=仅当前，最多30天） |

**响应**:
```json
{
  "success": true,
  "data": {
    "current": {
      "value": 24,
      "classification": "Extreme Fear",
      "timestamp": 1766880000
    },
    "timestamp": 1766931047
  }
}
```

**恐惧贪婪指数说明**:
| 范围 | 分类 | 含义 |
|------|------|------|
| 0-24 | Extreme Fear | 极度恐惧，可能是买入机会 |
| 25-44 | Fear | 恐惧 |
| 45-55 | Neutral | 中性 |
| 56-75 | Greed | 贪婪 |
| 76-100 | Extreme Greed | 极度贪婪，可能是卖出信号 |

### 2. 综合市场情绪

**GET** `/api/sentiment/market`

获取综合市场情绪数据。

**无需 CMC key 返回**:
- 恐惧贪婪指数
- 市场趋势判断

**有 CMC key 额外返回**:
- 全网总市值
- BTC/ETH 主导率
- 山寨季指数

**响应**:
```json
{
  "success": true,
  "data": {
    "available": true,
    "fear_greed_index": 24,
    "fear_greed_label": "Extreme Fear",
    "btc_dominance": 58.97,
    "eth_dominance": 11.93,
    "total_market_cap": 2976799529983,
    "total_market_cap_change_24h": 0.78,
    "total_volume_24h": 48400577902,
    "altcoin_season_index": 26,
    "market_trend": "bearish",
    "timestamp": 1766931070
  }
}
```

**山寨季指数说明**:
- 0-25: BTC 主导，山寨币弱势
- 26-50: 偏向 BTC
- 51-75: 偏向山寨
- 76-100: 山寨季，山寨币活跃

---

## 三、市场概览（整合数据）

**GET** `/api/analysis/market-overview`

整合 Binance 合约市场分析和全网市场情绪。

**响应**:
```json
{
  "success": true,
  "data": {
    "binance": {
      "total_coins": 266,
      "long_candidates": 3,
      "short_candidates": 0,
      "neutral": 263,
      "high_volatility": 183,
      "flash_crash_risk": 5,
      "market_sentiment": "bullish",
      "sentiment_description": "多头主导，做多机会较多"
    },
    "global": {
      "available": true,
      "fear_greed_index": 24,
      "fear_greed_label": "Extreme Fear",
      "btc_dominance": 58.97,
      "altcoin_season_index": 26,
      "market_trend": "bearish"
    },
    "timestamp": 1766931096
  }
}
```

---

## 四、CMC 数据接口（需要 CMC key）

这些接口需要配置 `CMC_PRO_API_KEY` 环境变量。

### 1. 市值排名 `/api/cmc/listings`
### 2. 热门币种 `/api/cmc/trending`
### 3. 涨跌幅排行 `/api/cmc/gainers-losers`
### 4. 全市场概览 `/api/cmc/market-overview`

**注意**: CMC 币种列表可能包含 Binance 没有的币种，仅作参考。

---

## 币种分类逻辑

### 做空信号 (SHORT)

| 信号 | 权重 | 说明 |
|------|------|------|
| 价格下跌 > 1.5% (1h) | +1 | 短期下跌趋势 |
| 价格下跌 + OI 增加 > 3% | +2 | **强信号**: 空头主导入场 |
| 资金费率 > 0.03% | +1 | 过度做多，有回调风险 |
| 高波动 + 下跌趋势 | +1 | 波动率 > 6% 且 24h 跌幅 > 3% |
| CMC 跌幅榜 | +1 | 全网关注的下跌币种 |

### 做多信号 (LONG)

| 信号 | 权重 | 说明 |
|------|------|------|
| 价格上涨 > 1.5% (1h) | +1 | 短期上涨趋势 |
| 价格上涨 + OI 增加 > 2% | +2 | **强信号**: 多头主导入场 |
| 资金费率 < -0.02% | +1 | 过度做空，有反弹机会 |
| 回调后企稳反弹 | +1 | 24h 跌幅 0-3% 但 1h 上涨 |
| CMC 涨幅榜 | +1 | 全网关注的上涨币种 |

### CMC 数据增强

| 标签 | 加分 | 说明 |
|------|------|------|
| `cmc_trending` | +10 | CMC 热门榜上榜 |
| `cmc_gainer` | +8 | CMC 24h 涨幅榜 |
| `cmc_loser` | +8 | CMC 24h 跌幅榜 |
| 市值前100 | +5 | CMC 市值排名前100 |

**注意**: CMC 数据仅作为辅助参考，只会显示 Binance 合约有的币种。

---

## 缓存策略

### 基础缓存

| 数据类型 | TTL | 说明 |
|----------|-----|------|
| Binance 行情 | 5秒 | 高频更新 |
| Binance OI | 30秒 | 中频更新 |
| Binance 资金费率 | 5分钟 | 低频更新 |
| 恐惧贪婪指数 | 10分钟 | 每日更新一次 |
| CMC 市场数据 | 5分钟 | 受 API 限额限制 |

### 缓存预热机制

为配合 NOFX 策略的 15 分钟扫描周期（每小时 01、16、31、46 分），服务器内置定时缓存预热功能：

**预热时间点**：每小时的 `00:10`、`15:10`、`30:10`、`45:10`（整点后 10 秒）

> 为什么是 10 秒？确保 K 线数据在整点关闭后已完成更新。

**预热接口**：
- `/api/ai500/list` - 智能币种列表（含 short/long 方向，limit ≤ 20 命中缓存）
- `/api/oi/top-ranking` - OI 持仓排行（limit ≤ 20 且 duration=1h 命中缓存）
- `/api/oi/top` - OI Top 20（固定参数，命中缓存）
- `/api/coin/{symbol}` - 单币种数据

**预热币种**：
- AI500 列表前 20 个币种
- 固定列表：BTC, ETH, SOL, BNB, XRP, ADA, LTC, BCH, LINK, ZEC

**缓存 TTL**：30 分钟（可配置）

### OI 流动性过滤

为保证返回的币种具有足够的市场流动性，与 NOFX 后端同步实现了 OI（持仓量）流动性过滤：

**过滤阈值**：15,000,000 USD（15M）

**过滤逻辑**：
- OI 价值 = 持仓量（币） × 当前价格
- 当 OI 价值 < 15M USD 时，该币种会被自动排除
- 确保策略获取的币种不会被 NOFX 后端二次过滤

**返回字段**：
- `oi_value_usd` - 币种的 OI 价值（USD），可用于验证流动性

**配置参数**（config.py）：
```python
min_oi_value_usd: float = 15_000_000  # 最小 OI 价值阈值（USD）
```

**示例**：
```bash
# 返回的币种都满足 OI >= 15M USD
curl "http://localhost:30007/api/ai500/list?auth=xxx&limit=8"
# 响应中每个币种都包含 oi_value_usd 字段
```

**配置参数**（config.py）：
```python
cache_warmup_enabled: bool = True   # 是否启用缓存预热
cache_warmup_ttl: int = 1800        # 预热缓存 TTL（秒）
```

**工作流程**：
```
时间线          预热器                    策略调度
─────────────────────────────────────────────────
00:10          ← 执行预热
01:00                                   ← 策略调用（命中缓存）
15:10          ← 执行预热
16:00                                   ← 策略调用（命中缓存）
30:10          ← 执行预热
31:00                                   ← 策略调用（命中缓存）
45:10          ← 执行预热
46:00                                   ← 策略调用（命中缓存）
```

### 缓存管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/cache/status` | GET | 查看缓存状态、命中率、条目列表 |
| `/api/cache/warmup` | POST | 手动触发缓存预热 |
| `/api/cache/clear` | DELETE | 清空所有缓存 |

**缓存状态示例**：
```bash
curl "http://localhost:30007/api/cache/status?auth=cm_568c67eae410d912c54c"
```

```json
{
  "success": true,
  "data": {
    "enabled": true,
    "ttl": 1800,
    "stats": {
      "hits": 15,
      "misses": 0,
      "hit_rate": "100.0%",
      "entries": {
        "total": 32,
        "ai500_list": 1,
        "oi_top": 1,
        "coins": 30
      }
    },
    "warmer": {
      "running": true,
      "last_warmup": 1767109383.48
    }
  }
}
```

---

## 文件结构

```
local_data_server/
├── main.py              # FastAPI 主程序
├── config.py            # 配置管理
├── binance_collector.py # Binance 数据采集（主）
├── cmc_collector.py     # CMC + 恐惧贪婪采集（辅）
├── coin_analyzer.py     # 币种分析和分类
├── cache.py             # API 缓存模块
├── cache_warmer.py      # 缓存预热器
├── requirements.txt     # 依赖
├── start.sh             # 启动脚本（后台运行）
├── stop.sh              # 停止脚本
├── status.sh            # 状态检查脚本
├── server.pid           # 进程 PID 文件（运行时生成）
├── server.log           # 服务日志（运行时生成）
└── venv/                # Python 虚拟环境
```

---

## 与官方 API 的差异

| 特性 | 官方 API | 本地服务器 |
|------|----------|------------|
| 数据来源 | 多交易所聚合 | Binance（主）+ CMC（辅） |
| 多空分类 | 无 | ✅ direction 参数 |
| CMC 热门整合 | 无 | ✅ 自动加权热门币种 |
| 闪崩风险 | 无 | ✅ 专门接口 |
| 恐惧贪婪指数 | 无 | ✅ 免费接口 |
| 山寨季指数 | 无 | ✅ 自动计算 |
| 资金流向 | 有 | 无（需要额外数据源） |
| 离线使用 | 不支持 | ✅ 本地运行 |

---

## NOFX 策略配置指南

本地数据服务器完全兼容 NOFX 策略的 4 个核心 API 配置。

### 配置示例

在 NOFX 策略编辑器中配置以下 URL（将 `localhost` 替换为服务器实际地址）：

| 配置项 | URL |
|--------|-----|
| **coin_pool_api_url** | `http://localhost:30007/api/ai500/list?auth=cm_568c67eae410d912c54c&limit=50` |
| **oi_top_api_url** | `http://localhost:30007/api/oi/top?auth=cm_568c67eae410d912c54c` |
| **oi_ranking_api_url** | `http://localhost:30007` |
| **quant_data_api_url** | `http://localhost:30007/api/coin/{symbol}?include=netflow,oi,price&auth=cm_568c67eae410d912c54c` |

### 1. coin_pool_api_url (币池 API)

**接口**: `GET /api/ai500/list`

返回智能筛选的币种列表，兼容官方 AI500 格式。

**返回数据结构**:
```json
{
  "success": true,
  "data": {
    "coins": [
      {
        "pair": "BTCUSDT",
        "score": 85.5,
        "start_time": 1766932000,
        "start_price": 87000.0,
        "last_score": 85.5,
        "max_score": 90.0,
        "max_price": 88000.0,
        "increase_percent": 2.5,
        "direction": "long",
        "confidence": 75.0
      }
    ],
    "count": 50
  }
}
```

**增强功能**: 使用 `direction=short` 或 `direction=long` 参数只获取做空/做多候选。

### 2. oi_top_api_url (OI Top API)

**接口**: `GET /api/oi/top` 或 `GET /api/oi/top-ranking`

返回 OI 持仓量增加排行（Top 20）。

**返回数据结构**:
```json
{
  "success": true,
  "code": 0,
  "data": {
    "positions": [
      {
        "symbol": "BTCUSDT",
        "rank": 1,
        "current_oi": 92800.0,
        "oi_delta": 500.0,
        "oi_delta_percent": 0.54,
        "oi_delta_value": 43900000.0,
        "price_delta_percent": 0.8,
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

### 3. oi_ranking_api_url (OI 排行基础 URL)

**基础 URL**: `http://localhost:30007`

NOFX 策略会自动拼接 `/api/oi/top-ranking` 和 `/api/oi/low-ranking` 接口。

**支持参数**:
- `limit`: 返回数量 (1-100)
- `duration`: 时间范围 (1m/5m/15m/30m/1h/4h/8h/12h/24h)
- `auth`: 认证密钥

### 4. quant_data_api_url (单币种量化数据)

**接口**: `GET /api/coin/{symbol}`

返回单个币种的综合数据（价格变化、OI、资金流向）。

**返回数据结构**:
```json
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "price": 87932.4,
    "price_change": {
      "1m": 0, "5m": 0, "15m": 0, "30m": 0,
      "1h": 0.0008, "4h": 0.0009,
      "8h": 0, "12h": 0, "24h": 0.0063,
      "2d": 0, "3d": 0
    },
    "oi": {
      "binance": {
        "current_oi": 92812.628,
        "net_long": 0,
        "net_short": 0,
        "delta": {
          "1h": {
            "oi_delta": 207.6,
            "oi_delta_value": 26926766.2,
            "oi_delta_percent": 0.0022
          },
          "4h": {
            "oi_delta": 509.3,
            "oi_delta_value": 0,
            "oi_delta_percent": 0.0055
          }
        }
      }
    },
    "netflow": {
      "institution": {"future": {}, "spot": {}},
      "personal": {"future": {}, "spot": {}}
    },
    "funding_rate": 0.0001
  }
}
```

**注意**: 资金流向 (netflow) 数据需要额外数据源，当前返回空结构。

### 与官方 API 兼容性

| 字段 | 官方 API | 本地服务器 | 状态 |
|------|----------|------------|------|
| pair/symbol | ✅ | ✅ | 兼容 |
| score | ✅ | ✅ | 兼容 |
| start_time | ✅ | ✅ | 兼容 |
| start_price | ✅ | ✅ | 兼容 |
| last_score | ✅ | ✅ | 兼容 |
| max_score | ✅ | ✅ | 兼容 |
| max_price | ✅ | ✅ | 兼容 |
| increase_percent | ✅ | ✅ | 兼容 |
| current_oi | ✅ | ✅ | 兼容 |
| oi_delta | ✅ | ✅ | 兼容 |
| oi_delta_percent | ✅ | ✅ | 兼容 |
| price_change | ✅ | ✅ | 兼容 |
| direction | ❌ | ✅ | **增强** |
| confidence | ❌ | ✅ | **增强** |
| tags | ❌ | ✅ | **增强** |
| reasons | ❌ | ✅ | **增强** |
| vwap_1h | ❌ | ✅ | **增强** |
| vwap_4h | ❌ | ✅ | **增强** |
| price_vs_vwap_1h | ❌ | ✅ | **增强** |
| price_vs_vwap_4h | ❌ | ✅ | **增强** |
| vwap_signal | ❌ | ✅ | **增强** |

**新增标签说明**:
- `cmc_trending`: CMC 热门榜币种
- `cmc_gainer`: CMC 涨幅榜币种
- `cmc_loser`: CMC 跌幅榜币种
- `extreme_volatility`: 极端波动 (>10%)
- `high_volatility`: 高波动 (>6%)
- `strong_uptrend`: 强上涨趋势 (24h>10%)
- `strong_downtrend`: 强下跌趋势 (24h<-10%)
- `flash_crash_risk`: 闪崩风险
- `extreme_funding`: 极端资金费率

---

## 常见问题

### Q: CMC 接口返回 503 错误？
A: CMC 接口是可选的。如果没有配置 `CMC_PRO_API_KEY`，CMC 接口会返回 503，但不影响 Binance 主接口和恐惧贪婪指数。

### Q: 恐惧贪婪指数无法获取？
A: 检查网络连接，该接口使用 alternative.me 免费 API。

### Q: 如何在生产环境运行？
A: 使用 gunicorn 或 supervisor：
```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:30007
```

---

## 单元测试

本项目包含完整的单元测试套件，覆盖核心模块的主要功能。

### 运行测试

```bash
cd /home/admin/AI/nofx/data/local_data_server
source venv/bin/activate

# 运行所有测试
python -m pytest -v

# 运行带覆盖率的测试
python -m pytest --cov=. --cov-report=term-missing

# 运行单个测试文件
python -m pytest test_coin_analyzer.py -v
python -m pytest test_binance_collector.py -v
python -m pytest test_api.py -v
```

### 测试文件

| 文件 | 覆盖内容 |
|------|----------|
| `test_coin_analyzer.py` | 币种分析器、方向判断、评分计算、入场时机、CMC数据增强 |
| `test_binance_collector.py` | 数据采集、ATR计算、VWAP计算、趋势强度、价格变化 |
| `test_api.py` | API认证、响应模型、端点测试、标签格式 |

### 测试覆盖率

- 核心模块 `coin_analyzer.py`: **83%**
- 数据模块 `binance_collector.py`: **40%**（主要是网络请求部分）
- 配置模块 `config.py`: **100%**
- 总体覆盖率: **57%**

---

## 更新日志

### 2026-01-05

**非 ASCII 字符币种过滤**:
- 自动过滤包含中文、日文等非 ASCII 字符的币种名称
- 例如 `币安人生USDT` 会被自动排除
- 这些币种会导致 LLM 编码失败（输出乱码如 `Ã¥Â¸ÂÃ¥Â®ÂÃ¤ÂºÂº`）
- 同时保留 `SYMBOL_BLACKLIST` 黑名单机制用于手动排除其他问题币种

### 2026-01-04

**市值权重优先排序**:
- 新增市值权重机制，相同条件下优先推荐大市值币种
- 评分公式：`final_score = base_score * (1 + market_cap_weight * 0.3)`
- 分级权重：
  | 排名范围 | 权重 | 代表币种 |
  |----------|------|----------|
  | 1-2 | 1.0 | BTC, ETH |
  | 3-10 | 0.8 | SOL, BNB, XRP |
  | 11-30 | 0.6 | LINK, AVAX |
  | 31-100 | 0.4 | 中型山寨 |
  | 101-200 | 0.2 | 小型山寨 |
  | 201+ | 0.1 | 微型山寨 |
  | 无数据 | 0.5 | 默认 |
- 影响接口：`/api/ai500/list`、`/api/analysis/short`、`/api/analysis/long`
- 排序使用加权后分数，大市值币种会排在更前面
- 新增单元测试：`TestMarketCapWeight`（10 个测试用例）

### 2026-01-03 (v2)

**防追高/追空系统完善（多空双向适配）**:
- 做多防追高：2h涨幅 > 回调要求×0.8 → `TIMING:CHASING`
- 做空防追空：2h跌幅 > 回调要求×0.8 → `TIMING:CHASING`
- 做多最佳入场：从高点回调 ≥ 70%要求 → `TIMING:OPTIMAL`
- 做空最佳入场：从低点反弹 ≥ 70%要求 → `TIMING:OPTIMAL`

**动态止损系统（多空双向适配）**:
- 做多止损：`entry - (ATR × 1.2)`
- 做空止损：`entry + (ATR × 1.2)`
- 波动率分级：高ATR(>5%)用1.2倍ATR，中ATR(3-5%)用1倍，低ATR(<3%)用0.8倍
- 新增字段：`atr_pct`, `suggested_stop_pct`, `suggested_stop_price`

**评分惩罚系统（多空双向适配）**:
- 做多追高惩罚：1h涨幅 > required_pullback×2 → 扣分
- 做空追空惩罚：1h跌幅 > required_pullback×2 → 扣分

**新增返回字段**:
- `entry_timing`: 入场时机状态 (optimal/wait_pullback/chasing/extended)
- `timing_score`: 入场时机评分 (0-100)
- `pullback_pct`: 做多时为回调幅度，做空时为反弹幅度
- `required_pullback`: 建议回调/反弹幅度
- `atr_pct`: ATR占价格百分比
- `suggested_stop_pct`: 建议止损百分比
- `suggested_stop_price`: 建议止损价格
- `volatility_level`: 波动率等级 (high/medium/low)

### 2026-01-03 (v1)

**单元测试**:
- 新增 `test_coin_analyzer.py`：34 个测试用例，覆盖方向判断、评分计算、入场时机等
- 新增 `test_binance_collector.py`：22 个测试用例，覆盖 ATR、VWAP、趋势强度等
- 新增 `test_api.py`：17 个测试用例，覆盖 API 认证、响应模型等
- 核心模块覆盖率达 83%，总体覆盖率 57%

**入场时机分析（反追高核心）**:
- 新增 `entry_timing` 指标：`optimal` / `wait_pullback` / `chasing` / `extended`
- 新增 `timing_score` 评分：0-100 分，用于量化入场时机质量
- 新增动态回调计算：基于 ATR 自动调整建议回调幅度
- 追高检测：刚暴涨的币种自动降低评分（-25分）
- 回调到位检测：达到建议回调幅度的币种自动加分（+20分）
- 新增标签：`TIMING:OPTIMAL`、`TIMING:CHASING`、`ATR:x.x%` 等

### 2026-01-02

**早期信号识别（VWAP 分析）**:
- 新增 `/api/analysis/early-signals` 接口，基于 VWAP 提前发现交易机会
- 支持 4 种 VWAP 信号类型：
  - `early_long`: 价格低于 VWAP 但 OI 增加（资金悄悄进场）
  - `early_short`: 价格高于 VWAP 且资金费率偏高（可能回调）
  - `breakout_long`: 价格刚向上突破 VWAP
  - `breakout_short`: 价格刚向下跌破 VWAP
- AI500 列表响应新增 VWAP 相关字段：`vwap_1h`、`vwap_4h`、`price_vs_vwap_1h`、`price_vs_vwap_4h`、`vwap_signal`

**AI500 多空平衡模式**:
- 新增 `direction=balanced` 参数，返回多空平衡的币种列表
- 默认模式改为 `balanced`（偶数各半，奇数空多一个）
- 调用 `direction=all` 返回所有分析结果不做平衡

**返回数据增强**:
- AI500 响应新增 `long_count` 和 `short_count` 统计字段
- 单币种接口优化缓存命中逻辑

### 2025-12-30

**缓存预热机制**:
- 新增 `cache.py` 模块：内存缓存管理，支持 TTL 过期
- 新增 `cache_warmer.py` 模块：定时缓存预热器
- 预热时间点：每小时的 00:10、15:10、30:10、45:10（整点后 10 秒，确保 K 线数据已更新）
- 预热接口：
  - `/api/ai500/list` - 默认列表、short、long 三个方向全部预热
  - `/api/oi/top` - OI 持仓排行
  - `/api/coin/{symbol}` - 单币种数据
- 预热币种：AI500 前 20 + 固定列表（BTC, ETH, SOL, BNB, XRP, ADA, LTC, BCH, LINK, ZEC）
- 缓存 TTL：30 分钟（可配置）
- limit <= 20 的请求都能命中缓存（从缓存截取）
- 新增配置项：`cache_warmup_enabled`、`cache_warmup_ttl`
- 新增管理接口：
  - `GET /api/cache/status` - 查看缓存状态和命中率
  - `POST /api/cache/warmup` - 手动触发预热
  - `DELETE /api/cache/clear` - 清空缓存

### 2025-12-29

**OI Ranking 数据完善**:
- 新增 `get_oi_ranking_with_history()` 方法，获取带历史变化的 OI 数据
- `/api/oi/top-ranking` 和 `/api/oi/low-ranking` 现在返回真实的 `oi_delta`、`oi_delta_percent`、`oi_delta_value` 数据
- 优化：只对 OI 价值前 100 名的币种获取历史数据，避免 API 限流

**单币种接口增强**:
- 新增 `calculate_all_price_changes()` 方法，计算所有时间周期的价格变化
- `/api/coin/{symbol}` 的 `price_change` 字段现在返回完整的 11 个时间周期数据：
  - 1m, 5m, 15m, 30m, 1h, 4h, 8h, 12h, 24h, 2d, 3d

**AI500 优化**:
- 降低分类阈值，让更多币种被分类为 long/short
- 整合 CMC 热门/涨跌幅数据，自动加权热门币种
- 新增 CMC 相关标签：`cmc_trending`、`cmc_gainer`、`cmc_loser`
- 确保只返回 Binance 合约中存在的币种
