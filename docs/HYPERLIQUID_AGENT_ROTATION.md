# Hyperliquid Agent Wallet 续期 / 轮换建议

## 先说结论

### 1. 仅做市场数据：
**不需要 `HYPERLIQUID_PRIVATE_KEY`。**

Hyperliquid 的 `Info` 市场数据接口是公开可读的：
- mids
- metadata / universe
- funding / asset contexts
- candles
- l2 book

所以如果你的 MarketDataService 只是拉市场行情、OI、funding、深度，
**就算 agent wallet 过期，也不会影响市场数据读取。**

### 2. 做交易执行：
如果你后面把 Hyperliquid 也接进实盘执行，那用到的是 **agent wallet / API wallet**。
官方文档明确写了：
- API wallet 可能会被 prune / expire
- 不建议重复复用旧 agent 地址
- 更建议重新生成新 agent wallet 继续使用

## 是否能“自动续期而不重新申请”？

### 保守答案：
**不建议把“续期”理解成对同一个 agent wallet 做无感延寿。**

更安全、也更符合官方说明的做法是：

1. **生成新的 agent wallet**
2. 用主账户执行 `approveAgent`
3. 切换服务端使用的新 agent key
4. 停用旧 agent wallet

也就是说，推荐模式其实是：

> **自动轮换（rotation）**

而不是：

> 自动续期（renew same wallet）

## 为什么不建议在在线服务器里自动 approveAgent

因为这通常意味着：
- 主账户私钥常驻在线环境
- 一旦服务器被入侵，风险比 agent key 泄漏严重得多

### 更好的实战方式

#### 方案 A（推荐）
- 市场数据服务不依赖私钥
- 交易执行服务单独维护 agent wallet
- 主账户私钥不放在常驻交易服务器
- 到期前手动执行一次 agent 轮换

#### 方案 B（中间方案）
- 使用专门的签名服务/HSM/密钥管理服务
- 由安全边界更高的 signer 去完成 `approveAgent`
- 交易节点仅拉取新的 agent key / signer reference

#### 方案 C（不推荐）
- 服务器持有主账户私钥
- 定时自动创建和批准新 agent

这对个人开发者来说太危险。

## 建议的轮换策略

### 如果只是备用执行通道
- 每 90~150 天轮换一次
- 不等“真正到期”再换

### 如果是核心实盘执行
- 每个 bot / subaccount 独立 agent wallet
- 每个 agent 只服务一个执行进程
- 提前 14 天告警
- 提前 7 天完成轮换

## 当前项目里的建议

### 市场数据服务层
- 继续保留：
  - `HYPERLIQUID_ADDRESS`
  - `HYPERLIQUID_PRIVATE_KEY`
- 但当前版本 **市场行情采集并不依赖它们**
- 这两个变量主要是为后续账户态/执行态预留

### 生产建议
- 不要让数据服务因为 agent wallet 轮换而重启失败
- 数据读取和交易签名应当解耦

## 推荐动作

1. 把 Hyperliquid **市场数据**与**交易签名**分成两个模块
2. MarketDataService 保持只读
3. 未来如果上 Hyperliquid 执行，再单独实现 `hyperliquid_execution_service`
4. 该执行服务使用独立 agent wallet 轮换流程
