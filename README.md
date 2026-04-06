# MarketDataService v2.1 Practical

一个面向 **NoFx 自托管替代数据层** 的本地市场数据服务。

这版不是为了伪造官方 `nofxos.ai` 的全量商业数据，而是提供一个：

- **免费优先**
- **可独立部署**
- **适合个人长期维护**
- **尽量兼容 NoFx Core 数据依赖**

的实战版市场数据底座。

---

## 核心能力

### 主数据源
- **Binance Futures**：主行情、K线、OI、Funding、深度热力图、VWAP、候选池分析
- **Hyperliquid**：补充永续覆盖、Funding、OI、L2 depth、candles
- **OKX**：补充 SWAP ticker、OI、funding、candles、orderbook depth
- **CoinGecko Demo / CMC Free**：市值、dominance、trending、gainers/losers、global market
- **Alternative.me**：Fear & Greed

### 已支持的 NoFx Core 风格接口
- `GET /api/ai500/list`
- `GET /api/ai500/{symbol}`
- `GET /api/ai500/stats`
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
- `GET /api/netflow/top-ranking`（代理模式）
- `GET /api/netflow/low-ranking`（代理模式）
- `GET /api/sentiment/fear-greed`
- `GET /api/sentiment/market`
- `GET /api/system/status`
- `GET /api/system/capabilities`
- `GET /api/system/provider-usage`
- `GET /api/system/nofx-compatibility`
- `GET /api/system/strategy-universe`
- `GET /api/system/nofx-adaptation-checklist`
- `GET /api/strategy/pair-neutral/template`
- `GET /api/strategy/pair-neutral/context`

---

## 已知边界

### 原生支持较好
- OI / funding / heatmap / price ranking
- AI500 候选池
- 单币聚合
- 宏观风险过滤

### 代理支持
- netflow（通过 taker imbalance 近似）

### 当前不做硬伪装
- AI300 专有模型
- 真实 institution / personal 资金流拆分
- Upbit 专项榜单
- Query Rank
- 官方 long-short ratio

---

## 环境变量

参考 `.env.example`

### 最少建议设置
```bash
NOFXOS_API_KEY=change_me_local_auth_key
COINGECKO_API_ENDPOINT=https://api.coingecko.com/api/v3
COINGECKO_API_KEY=...
```

兼容旧变量：

```bash
NOFX_LOCAL_AUTH_KEY=change_me_local_auth_key
```

业务接口通过查询参数 `auth=...` 鉴权；服务会优先从 `NOFXOS_API_KEY` 读取认证密钥，其次回退到 `NOFX_LOCAL_AUTH_KEY`。

### 可选
```bash
CMC_PRO_API_KEY=...
HYPERLIQUID_ADDRESS=0x...
HYPERLIQUID_PRIVATE_KEY=...
OKX_API_KEY=...
OKX_API_SECRET=...
OKX_API_PASSPHRASE=...
BINANCE_API_KEY_READONLY=...
BINANCE_API_SECRET_READONLY=...
ANALYSIS_UNIVERSE_MODE=fixed
ANALYSIS_FIXED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,HYPEUSDT,ZECUSDT
```

---

## 免费额度保护

CoinGecko Demo 和 CMC Free 都很适合做低频宏观层，但不适合被秒级乱打。

本版本新增：
- 本地 `provider usage` 持久化统计
- 月度 soft limit
- 分钟级 soft limit
- `auto` 模式下预算感知回退（CoinGecko -> CMC）

接口：
- `GET /api/system/provider-usage`

---

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

缓存预热默认每 5 分钟执行一次，触发时刻为每小时 `00/05/10/15/20/25/30/35/40/45/50/55` 分的 `30` 秒。

也可以直接使用 `./start.sh`，脚本会优先复用 `.venv`，其次回退到 `venv`。

---

## 测试

```bash
pytest -q
```

---

## 推荐监控

- `/health`
- `/api/system/status`
- `/api/system/provider-usage`
- `/api/system/nofx-compatibility`
- `/api/cache/status`

其中：
- `/health` 无鉴权，返回基础健康状态；当 collector 未初始化或 provider 只有错误没有成功时会返回 `degraded`
- `/api/system/status` 需要 `auth`，返回数据覆盖情况，并附带同样的认证与预热说明；该接口会走一个短 TTL 内存缓存，适合低频监控

---

## 文档

- `docs/NOFX_FIELD_MAPPING.md`
- `docs/HYPERLIQUID_AGENT_ROTATION.md`
- `docs/PRACTICAL_DEPLOYMENT.md`
- `docs/NOFX_ADAPTATION_CHECKLIST.md`
- `docs/BTC_ETH_PAIR_NEUTRAL_TEMPLATE.md`

---

## 实战建议

- **交易所执行在哪，就以哪个交易所为主数据源。**
- **Hyperliquid 用于补 coverage，不要和 Binance 盲目混成单一真值。**
- **Netflow 一律视为代理信号。**
- **CoinGecko / CMC 只做低频宏观过滤。**
- **AI500 更适合做候选池，不适合直接裸下单。**
