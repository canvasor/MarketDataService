# NoFx 前端 / 策略层适配清单

## 已对齐

### 1. 候选池
- `/api/ai500/list`
- `/api/ai500/{symbol}`
- `/api/ai500/stats`

### 2. 单币综合详情
- `/api/coin/{symbol}`
- 已覆盖：
  - `price_change.{duration}`
  - `oi.binance`
  - `oi.hyperliquid`
  - `oi.okx`
  - `netflow.institution.*`（代理模式）
  - `netflow.personal.*`（固定 0，占位）
  - `ai500.score`
  - `ai500.is_active`

### 3. 榜单
- `/api/oi/top-ranking`
- `/api/oi-cap/ranking`
- `/api/funding-rate/top`
- `/api/funding-rate/low`
- `/api/price/ranking`
- `/api/heatmap/list`

### 4. 系统与兼容性
- `/api/system/status`
- `/api/system/capabilities`
- `/api/system/provider-usage`
- `/api/system/nofx-compatibility`
- `/api/system/nofx-adaptation-checklist`
- `/api/system/strategy-universe`

## 本地扩展（NoFx 官方无同名接口）

- `/api/strategy/pair-neutral/template`
- `/api/strategy/pair-neutral/context`

## 仍是缺口

- `/api/ai300/*`
- `/api/long-short/*`
- `/api/query-rank/list`
- 真实 institution / personal split
- Upbit 专项榜单

## 适配建议

1. 前端展示层只把 `netflow` 当辅助色带，不当硬信号。
2. 策略层优先消费 `/api/coin/{symbol}` + `/api/strategy/pair-neutral/context`。
3. 固定币池模式下，NoFx UI 的“全市场”概念建议改成“策略宇宙”。
4. 预算敏感接口优先本地缓存，不要让 NoFx 前端高频直刷 CoinGecko/CMC 类宏观端点。
