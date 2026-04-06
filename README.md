# MarketDataService v2

一个面向 **NoFx 自托管替代数据层** 的本地市场数据服务。

这次重构后的目标不是伪造官方 `nofxos.ai` 的全量商业数据，而是提供一个 **可独立运行、免费优先、可扩展** 的核心兼容层：

- **Binance Futures**：主行情、K线、OI、Funding、深度热力图、VWAP、入场时机
- **Hyperliquid**：补充未在 Binance 覆盖的永续合约、Funding、OI、L2 深度
- **CoinGecko Demo（优先） / CMC（可选）**：全市场市值、BTC/ETH Dominance、Trending、Gainers/Losers
- **Alternative.me**：Fear & Greed 免费情绪数据

## 重构后能力边界

### 已兼容 / 已增强

- `GET /api/ai500/list`
- `GET /api/ai500/{symbol}`（通过 `/api/coin/{symbol}` 的组合数据实现近似兼容）
- `GET /api/oi/top-ranking`
- `GET /api/oi/low-ranking`
- `GET /api/oi-cap/ranking`
- `GET /api/price/ranking`
- `GET /api/funding-rate/top`
- `GET /api/funding-rate/low`
- `GET /api/funding-rate/{symbol}`
- `GET /api/heatmap/future/{symbol}`
- `GET /api/heatmap/spot/{symbol}`
- `GET /api/heatmap/list`
- `GET /api/coin/{symbol}`
- `GET /api/netflow/top-ranking`（**代理模式**：基于 taker buy/sell imbalance）
- `GET /api/netflow/low-ranking`（**代理模式**）
- `GET /api/sentiment/fear-greed`
- `GET /api/sentiment/market`
- `GET /api/system/status`
- `GET /api/system/capabilities`

### 当前明确不做“硬伪装”的能力

以下能力没有免费、稳定、统一的公共数据源，当前不会伪装成“和官方完全一样”：

- institution / personal **真实**资金流拆分
- Upbit 专项热币/净流入净流出
- 官方 query rank / 社区搜索热度
- 官方 AI300 专有模型信号

这些能力在本项目里会通过：

- `mode=proxy_taker_imbalance`
- `system/capabilities`
- `not_fully_supported`

明确暴露出来，避免误导策略层。

## 为什么这样设计

对 NoFx 来说，真正“刚需”的不是所有商业化接口，而是：

1. **交易所级实时行情与 K 线**
2. **可落地的 OI / Funding / Heatmap**
3. **一个稳定的候选池（AI500/long/short）**
4. **基本宏观情绪与市值层过滤**

这 4 点用 Binance + Hyperliquid + CoinGecko Demo 就能搭起一个足够强的个人版替代层。

## 环境变量

### 必填（至少建议设置 auth）

```bash
NOFX_LOCAL_AUTH_KEY=cm_568c67eae410d912c54c
```

### Binance（可选，提升限额）

```bash
BINANCE_API_KEY_READONLY=...
BINANCE_API_SECRET_READONLY=...
```

### Hyperliquid（行情接口无需私钥，预留账户态功能）

```bash
HYPERLIQUID_ADDRESS=0x...
HYPERLIQUID_PRIVATE_KEY=...
```

### CoinGecko Demo（推荐，免费）

```bash
COINGECKO_API_KEY=...
```

### CoinMarketCap Pro（可选）

```bash
CMC_PRO_API_KEY=...
CMC_PRO_API_ENDPOINT=https://pro-api.coinmarketcap.com
```

### 其他

```bash
CACHE_WARMUP_ENABLED=true
MARKET_DATA_PROVIDER=auto
```

## 安装与运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 30007
```

## 测试

```bash
pytest -q
```

## 监控建议

生产环境建议定时监控：

- `/health`
- `/api/system/status`
- `/api/cache/status?auth=...`

同时建议将 `CACHE_WARMUP_ENABLED=true` 跑在常驻服务里，这样 Hyperliquid OI 的本地时间序列快照可以逐渐稳定，代理层质量会明显好于刚启动时。

## 最佳实践

- **交易所执行在哪，就以哪个交易所为主数据源。** 如果策略主要跑 Binance，仍以 Binance 行情/OI/Funding 为主。
- **Hyperliquid 用来补 coverage，不要盲目和 Binance 混成单一真值。**
- **Netflow 一律视为代理信号，不要当成真实机构/散户分流。**
- **AI500 更适合做候选池，不适合直接裸下单。**
- **回测和实盘应共享同一数据口径。**

## 文件结构

```text
.
├── main.py                    # FastAPI 服务
├── market_data_collector.py   # 多源聚合核心（Binance + Hyperliquid）
├── binance_collector.py       # Binance 主数据源
├── hyperliquid_collector.py   # Hyperliquid 补充数据源
├── cmc_collector.py           # CoinGecko Demo / CMC / Fear & Greed
├── coin_analyzer.py           # 选币、评分、VWAP、时机分析
├── cache.py                   # API 缓存
├── cache_warmer.py            # 预热任务
└── tests                      # 单元测试（平铺）
```
