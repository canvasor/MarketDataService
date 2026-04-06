# NoFx 实际调用字段对照表 + MarketDataService 字段映射 + 缺口清单

## 目标

这份文档不是为了伪装成官方 NoFx 商业数据，而是为了把：

1. **NoFx 官方文档里实际暴露的接口/字段**
2. **当前 MarketDataService 已能返回的结构**
3. **仍未补齐的缺口**

做成一张可执行的兼容表，便于你后续继续补 OKX / Bybit / Upbit 等源。

---

## 总体结论

- **原生兼容较好**：AI500 候选池、OI ranking、funding、heatmap、price ranking、coin 聚合、macro/sentiment。
- **代理兼容**：netflow。
- **明确缺口**：AI300、真实 institution/personal 拆分、Upbit 专项、Query Rank、Long/Short ratio。

推荐优先级：

1. 先把 **NoFx Core** 跑稳：Binance + Hyperliquid + CoinGecko/CMC
2. 二阶段补 **Bybit / OKX OI & Funding**
3. 三阶段再考虑 **Upbit / query telemetry / 自研 AI300**

---

## 1. AI500

### 官方
- `GET /api/ai500/list`
- `GET /api/ai500/{symbol}`
- `GET /api/ai500/stats`

### 本地映射

#### `/api/ai500/list`
- 官方 `pair` -> 本地 `pair`
- 官方 `score` -> 本地 `score`
- 官方 `start_time` -> 本地 `start_time`
- 官方 `start_price` -> 本地 `start_price`
- 官方 `increase_percent` -> 本地 `increase_percent`

本地额外字段：
- `direction`
- `confidence`
- `entry_timing`
- `timing_score`
- `vwap_signal`
- `suggested_stop_pct`

#### `/api/ai500/{symbol}`
本地新增兼容端点：
- `data.ai500.score`
- `data.ai500.is_active`
- `data.coin`
- `data.analysis`

说明：
- 本地是 **rule-based + macro enhanced** 分数，不是官方专有 AI500 模型。

#### `/api/ai500/stats`
本地新增兼容端点：
- `active_count`
- `score_stats`
- `direction_distribution`

说明：
- 统计口径是本地候选池，不等于官方全市场专有评分宇宙。

---

## 2. OI / OI Ranking

### 官方
- `GET /api/oi/top-ranking`
- `GET /api/oi/low-ranking`
- `GET /api/oi-cap/ranking`

### 本地映射

#### `/api/oi/top-ranking` & `/api/oi/low-ranking`
- `symbol` -> `symbol`
- `current_oi` -> `current_oi`
- `oi_delta` -> `oi_delta`
- `oi_delta_percent` -> `oi_delta_percent`
- `oi_delta_value` -> `oi_delta_value`
- `price_delta_percent` -> `price_delta_percent`

数据来源：
- Binance 主
- Hyperliquid 辅

#### `/api/oi-cap/ranking`
- `oi` -> `oi`
- `oi_value` -> `oi_value`
- `net_long` -> `net_long`
- `net_short` -> `net_short`
- `market_cap` -> 由 CoinGecko / CMC 提供

---

## 3. Price Ranking

### 官方
- `GET /api/price/ranking`

### 本地映射
- `price_delta` -> `price_delta`
- `price` -> `price`
- `future_flow` -> `future_flow`
- `spot_flow` -> `spot_flow`
- `oi` -> `oi`
- `oi_delta` -> `oi_delta`
- `oi_delta_value` -> `oi_delta_value`

说明：
- `price / oi` 为原生市场数据
- `future_flow / spot_flow` 为 **proxy_taker_imbalance** 代理流量

---

## 4. Coin Detail

### 官方
- `GET /api/coin/{symbol}`

### 官方关键字段
- `price_change.{duration}`
- `netflow.institution.{duration}`
- `netflow.personal.{duration}`
- `oi.binance / oi.bybit`
- `oi.*.oi_delta_percent`
- `oi.*.oi_delta_value`
- `ai500.score`
- `ai500.is_active`

### 本地映射

#### 已支持
- `data.price_change.{duration}`
- `data.oi.binance`
- `data.oi.hyperliquid`
- `data.ai500.score`
- `data.ai500.is_active`

#### 代理兼容
- `data.netflow.institution.1h`
- `data.netflow.personal.1h`
- `data.netflow.breakdown.future_flow`
- `data.netflow.breakdown.spot_flow`
- `data.netflow.mode=proxy_taker_imbalance`

说明：
- 本地为了兼容官方顶层字段，同时额外保留 `breakdown` 和 `mode`，让策略层知道这不是“真实机构/散户净流”。

---

## 5. Funding Rate

### 官方
- `GET /api/funding-rate/top`
- `GET /api/funding-rate/low`
- `GET /api/funding-rate/{symbol}`

### 本地映射
- `funding_rate` -> `funding_rate`
- `mark_price` -> `mark_price`
- `next_funding_time` -> `next_funding_time`

来源：
- Binance 主
- Hyperliquid 可补

---

## 6. Heatmap

### 官方
- `GET /api/heatmap/future/{symbol}`
- `GET /api/heatmap/spot/{symbol}`
- `GET /api/heatmap/list`

### 本地映射
- `bid_volume` -> `bid_volume`
- `ask_volume` -> `ask_volume`
- `delta` -> `delta`
- `delta_history` -> `delta_history`
- `large_asks` -> `large_asks`
- `large_bids` -> `large_bids`

来源：
- Future：Binance futures depth 优先，缺失时 Hyperliquid L2
- Spot：Binance spot depth

---

## 7. Macro / Sentiment

### 本地宏观数据
- `GET /api/cmc/listings`
- `GET /api/cmc/trending`
- `GET /api/cmc/gainers-losers`
- `GET /api/cmc/market-overview`
- `GET /api/sentiment/fear-greed`
- `GET /api/sentiment/market`

说明：
- 接口名保留 `cmc`，但内部会根据配置和预算，自动选择 **CoinGecko Demo 或 CMC Free**。
- 适合做：市值层过滤、宏观风险开关、候选池增强。

---

## 8. 明确缺口清单

### Gap A：真实 institution / personal 资金流拆分
- 当前状态：**不可免费稳定获得**
- 本地方案：`proxy_taker_imbalance`
- 实战建议：
  - 可以用作过滤器
  - 不要直接作为主开仓信号

### Gap B：AI300 专有模型
- 当前状态：**未实现**
- 建议：
  - 单独做 `local_alpha300` 模型
  - 以 flow + OI + funding + VWAP + volatility regime 组合实现

### Gap C：Long-Short Ratio
- 当前状态：**未实现**
- 建议：
  - 二阶段接入 Binance/Bybit 的 long-short / top trader ratio

### Gap D：Upbit 专项数据
- 当前状态：**缺源**
- 建议：
  - 二阶段加 Upbit public market endpoints

### Gap E：Query Rank
- 当前状态：**缺本地 telemetry**
- 建议：
  - 在 UI / 策略网关增加 symbol query 统计

### Gap F：Bybit / OKX 横向 OI 与 funding
- 当前状态：**推荐二阶段补齐**
- 建议：
  - 先补 Bybit，再补 OKX
  - 重点不是全量覆盖，而是给 `coin/{symbol}` 增加多交易所 OI 对照

---

## 9. 当前版本建议定位

建议把当前服务定位为：

> **NoFx Core Compatible Data Layer**

而不是：

> 官方商业数据 1:1 替身

这样会让架构边界更清晰，也更利于后续持续迭代。
