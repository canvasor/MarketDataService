# BTC/ETH 配对中性策略模板

## 目标

在不追求高收益的前提下，做 **BTC/ETH 相对价值回归**：
- 信号周期：15m
- 执行周期：3m~5m
- 开仓方式：双腿同时开仓
- 对冲方式：**按滚动 beta**，不是 1:1 等金额

## 参数模板

- 交易对：`BTCUSDT` vs `ETHUSDT`
- lookback：`288 x 15m`（约 3 天）
- 入场阈值：`|z| >= 2.0`
- 平仓阈值：`|z| <= 0.5`
- 风险止损：`|z| >= 3.2`
- 最低相关性：`corr >= 0.65`
- 最长持仓：`12h`
- 单次 NAV 风险：`0.25% ~ 0.5%`
- 总杠杆：`<= 1.8x`
- 单腿名义仓位上限：`<= 20% NAV`

## 开仓逻辑

1. 拉取两腿 15m K 线。
2. 计算 log returns。
3. 用 OLS 估计滚动 beta：`ret_a ~ beta * ret_b`。
4. 构造 spread：`log(P_a) - beta * log(P_b)`。
5. 计算 spread 的 z-score。
6. 若 `z >= 2.0`：
   - 空 A / 多 B
7. 若 `z <= -2.0`：
   - 多 A / 空 B
8. 只有在以下过滤同时通过时才允许下单：
   - `corr >= 0.65`
   - funding divergence 未极端扩大
   - 深度热力图 delta 未明显失衡
   - OI 没有单腿异常跳变

## 平仓逻辑

- `|z| <= 0.5`
- 或达到最长持仓时间
- 或 funding / OI / depth 出现 regime break

## 风控建议

- 不用 `1:1` 等金额对冲。
- 不在高冲击、低深度时段开仓。
- 不把 `netflow` 代理值当真实机构流。
- AI 只做 regime filter，不要直接决定方向。

## 回测字段清单

- `timestamp`
- `symbol`
- `close`
- `quote_volume`
- `oi.current`
- `oi.delta_1h`
- `funding_rate`
- `heatmap.delta`
- `future_flow_proxy`
- `spot_flow_proxy`

## 对应本地服务接口

- 模板：`GET /api/strategy/pair-neutral/template`
- 实时上下文：`GET /api/strategy/pair-neutral/context`
- 单币详情：`GET /api/coin/{symbol}`
- OI：`GET /api/oi/top-ranking`
- Funding：`GET /api/funding-rate/{symbol}`
- Heatmap：`GET /api/heatmap/future/{symbol}`
