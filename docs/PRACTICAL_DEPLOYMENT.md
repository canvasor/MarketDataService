# Practical Deployment

## 推荐环境变量

```bash
NOFXOS_API_KEY=change_me_local_auth_key
NOFX_LOCAL_AUTH_KEY=change_me_local_auth_key
COINGECKO_API_KEY=...
CMC_PRO_API_KEY=...
HYPERLIQUID_ADDRESS=0x...
HYPERLIQUID_PRIVATE_KEY=0x...
OKX_API_KEY=...
OKX_API_SECRET=...
OKX_API_PASSPHRASE=...
ANALYSIS_UNIVERSE_MODE=fixed
ANALYSIS_FIXED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,HYPEUSDT,ZECUSDT
```

说明：
- 业务接口使用查询参数 `auth=...`
- 服务优先读取 `NOFXOS_API_KEY`，其次读取 `NOFX_LOCAL_AUTH_KEY`
- 缓存预热默认在每小时 `00/05/10/15/20/25/30/35/40/45/50/55` 分的 `30` 秒执行

## 关于固定币池

当前默认实战模式就是固定币池：
- `BTCUSDT`
- `ETHUSDT`
- `SOLUSDT`
- `BNBUSDT`
- `HYPEUSDT`
- `ZECUSDT`

更稳的建议是分两层：
- 核心池：`BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT`
- 事件池：`HYPEUSDT, ZECUSDT`

## 关于 OKX

当前 MarketDataService 主要使用 OKX 公共行情接口；私钥信息只为你后续做执行层或私有读接口预留。

## 关于 Hyperliquid 6 个月问题

行情读取本身不依赖 agent wallet。
真正会过期/被 prune 的是 API wallet / agent wallet。
建议把：
- 只读数据服务
- 交易执行服务

拆成两个进程，不要让数据服务依赖会过期的 agent。
