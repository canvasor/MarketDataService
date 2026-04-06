# 实战版升级摘要

本轮升级内容：

1. 新增 OKX 公共行情接入
   - SWAP tickers
   - public funding-rate
   - public open-interest
   - market candles
   - market books

2. 新增固定币池模式
   - `ANALYSIS_UNIVERSE_MODE`
   - `ANALYSIS_FIXED_SYMBOLS`
   - 默认固定为 `BTC, ETH, SOL, BNB, HYPE, ZEC`

3. 新增策略接口
   - `/api/strategy/pair-neutral/template`
   - `/api/strategy/pair-neutral/context`

4. 新增 NoFx 对接辅助接口
   - `/api/system/strategy-universe`
   - `/api/system/nofx-adaptation-checklist`

5. 文档补充
   - `BTC_ETH_PAIR_NEUTRAL_TEMPLATE.md`
   - `NOFX_ADAPTATION_CHECKLIST.md`
   - `IMPLEMENTATION_SUMMARY.md`

测试结果：
- `94 passed`
