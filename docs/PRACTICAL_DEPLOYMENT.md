# 最终实战版部署建议

## 推荐架构

### 层 1：MarketDataService
负责：
- Binance Futures 主行情
- Hyperliquid 辅助行情
- CoinGecko / CMC 宏观数据
- OI / Funding / Heatmap / Proxy Netflow

### 层 2：Strategy Engine
负责：
- AI500 候选池使用
- 配对交易 / delta-neutral / mean reversion
- 资金费率过滤
- regime filter（risk-on / risk-off）

### 层 3：Execution Adapter
负责：
- Binance 下单
- Hyperliquid（如需）下单
- 重试、限流、风控、断线恢复

## 免费额度最优使用方法

### CoinGecko / CMC 不要直连前端
都应只由 MarketDataService 后端统一访问。

### 高缓存接口
建议 TTL：
- listings / market overview：300s
- trending：180s
- fear & greed：600s
- provider usage：120s

### 高频接口不要用宏观源
高频接口只用交易所市场数据：
- tickers
- funding
- oi
- depth
- klines

### 宏观源只做低频刷新
适合 3~10 分钟刷新一次，不需要秒级。

## 监控建议

重点监控：
- `/health`
- `/api/system/status`
- `/api/system/provider-usage`
- `/api/system/nofx-compatibility`
- `/api/cache/status`

## 推荐回测/实盘使用方式

### 推荐
- AI500 作为候选池
- OI + funding + vwap + timing_score 作为二次过滤
- netflow 只作为辅助过滤

### 不推荐
- 把 proxy netflow 直接当“真实机构流”
- 用 CoinGecko/CMC 做 3m 高频主信号
- 直接让 AI500 分数决定开仓

## 下一阶段优先级

1. 补 Bybit OI / funding
2. 补 OKX OI / funding
3. 增加 long-short ratio
4. 增加本地 query telemetry
5. 自研 local alpha300
