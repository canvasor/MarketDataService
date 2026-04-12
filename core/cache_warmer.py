#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存预热模块

定时预热机制:
- 每 5 分钟调度一次，在每小时的 00、05、10 ... 55 分的第 30 秒触发
- 预热接口: /api/ai500/list, /api/oi/top, /api/coin/{symbol}

预热币种:
- /api/ai500/list 前 20 的币种
- 固定列表: BTC, ETH, SOL, BNB, XRP, ADA, LTC, BCH, LINK, ZEC
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from core.cache import APICache, get_cache

if TYPE_CHECKING:
    from collectors.binance_collector import BinanceCollector
    from collectors.cmc_collector import CMCCollector
    from analysis.coin_analyzer import CoinAnalyzer

logger = logging.getLogger(__name__)


# 固定预热币种列表
FIXED_WARMUP_COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "LTCUSDT", "BCHUSDT", "LINKUSDT", "ZECUSDT"
]

# 预热时间点（分钟）：00, 05, 10 ... 55
# 注意：实际预热在这些分钟的第 30 秒开始，确保 K 线数据已更新
WARMUP_MINUTES = list(range(0, 60, 5))
WARMUP_SECONDS_OFFSET = 30


def get_warmup_schedule() -> dict:
    return {
        "minutes": list(WARMUP_MINUTES),
        "second_offset": WARMUP_SECONDS_OFFSET,
        "description": "every 5 minutes at second 30",
    }


class CacheWarmer:
    """
    缓存预热器

    在策略调用前预热数据:
    1. 每 5 分钟执行一次预热
    2. 预热 ai500/list、oi/top 和指定币种数据
    3. 数据缓存 15-30 分钟
    """

    def __init__(
        self,
        collector: "BinanceCollector",
        analyzer: "CoinAnalyzer",
        cmc_collector: Optional["CMCCollector"] = None,
        vs_collector=None,
        cache: Optional[APICache] = None,
        cache_ttl: float = 600,  # 10 分钟
        ai500_limit: int = 20,
        vs_warmup_interval_minutes: int = 10,
    ):
        """
        初始化预热器

        Args:
            collector: Binance 数据采集器
            analyzer: 币种分析器
            cmc_collector: CMC 采集器（可选）
            vs_collector: ValueScan 采集器（可选，主数据源）
            cache: 缓存实例（可选，默认使用全局实例）
            cache_ttl: 缓存 TTL（秒）
            ai500_limit: ai500/list 返回数量
            vs_warmup_interval_minutes: ValueScan 预热间隔（分钟）
        """
        self.collector = collector
        self.analyzer = analyzer
        self.cmc_collector = cmc_collector
        self.vs_collector = vs_collector
        self.cache = cache or get_cache()
        self.cache_ttl = cache_ttl
        self.ai500_limit = ai500_limit
        self.vs_warmup_interval_minutes = vs_warmup_interval_minutes

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._initial_warmup_task: Optional[asyncio.Task] = None
        self._last_warmup_time: float = 0
        self._last_vs_warmup_time: float = 0

    async def start(self) -> None:
        """启动预热调度"""
        if self._running:
            logger.warning("缓存预热器已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("缓存预热器已启动")

        # 立即触发一次后台预热，但不阻塞服务启动
        self._initial_warmup_task = asyncio.create_task(self.warmup())

    async def stop(self) -> None:
        """停止预热调度"""
        self._running = False
        if self._initial_warmup_task:
            if not self._initial_warmup_task.done():
                self._initial_warmup_task.cancel()
                try:
                    await self._initial_warmup_task
                except asyncio.CancelledError:
                    pass
            self._initial_warmup_task = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("缓存预热器已停止")

    async def _scheduler_loop(self) -> None:
        """调度循环"""
        while self._running:
            try:
                # 计算下一个预热时间点
                now = datetime.now()
                current_minute = now.minute
                current_second = now.second

                # 找到下一个预热时间点
                next_warmup_minute = None
                for m in WARMUP_MINUTES:
                    # 如果当前分钟等于预热分钟，检查是否已过预热秒数
                    if m == current_minute and current_second < WARMUP_SECONDS_OFFSET:
                        next_warmup_minute = m
                        break
                    elif m > current_minute:
                        next_warmup_minute = m
                        break

                if next_warmup_minute is None:
                    # 下一个预热点在下一个小时
                    next_warmup_minute = WARMUP_MINUTES[0]
                    wait_minutes = 60 - current_minute + next_warmup_minute
                    wait_seconds = wait_minutes * 60 - current_second + WARMUP_SECONDS_OFFSET
                elif next_warmup_minute == current_minute:
                    # 当前分钟内的预热点
                    wait_seconds = WARMUP_SECONDS_OFFSET - current_second
                else:
                    wait_minutes = next_warmup_minute - current_minute
                    wait_seconds = wait_minutes * 60 - current_second + WARMUP_SECONDS_OFFSET

                logger.info(
                    f"下一次预热: {wait_seconds}秒后 "
                    f"(约 {now.hour:02d}:{next_warmup_minute:02d}:{WARMUP_SECONDS_OFFSET:02d})"
                )

                # 等待到预热时间
                await asyncio.sleep(wait_seconds)

                if self._running:
                    await self.warmup()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"预热调度异常: {e}")
                await asyncio.sleep(60)  # 出错后等待 1 分钟重试

    async def warmup(self) -> dict:
        """
        执行预热

        Returns:
            预热结果统计
        """
        start_time = time.time()
        logger.info("=" * 50)
        logger.info("开始缓存预热...")

        # 预热开始时清除 collector 的 OI 缓存，确保拉取最新数据
        self.collector._oi_cache.clear()
        # 清除 analyzer 的分析缓存，确保基于最新数据重新分析
        if self.analyzer:
            self.analyzer._analysis_cache = None

        result = {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "ai500_list": False,
            "ai500_short": False,
            "ai500_long": False,
            "oi_top": False,
            "oi_low": False,
            "coins": [],
            "errors": [],
            "duration_ms": 0
        }

        try:
            # 1. 预热 ai500/list、short、long
            # 优先使用 ValueScan（每 vs_warmup_interval_minutes 执行一次）
            vs_ai500_success = False
            all_analyzed_symbols: Set[str] = set()
            now_ts = time.time()
            vs_interval = self.vs_warmup_interval_minutes * 60

            if self.vs_collector and (now_ts - self._last_vs_warmup_time) >= vs_interval:
                vs_result = await self._warmup_ai500_from_valuescan()
                if vs_result:
                    vs_ai500_success = True
                    result["ai500_list"] = True
                    result["ai500_short"] = True
                    result["ai500_long"] = True
                    result["ai500_source"] = "valuescan"
                    coins = vs_result.get("coins", [])
                    logger.info(f"✓ ai500 预热成功 (ValueScan): {len(coins)} coins")

            if not vs_ai500_success:
                # 回退到本地分析
                ai500_data, short_count, long_count, all_analyzed_symbols = await self._warmup_ai500_all()
                if ai500_data:
                    result["ai500_list"] = True
                    result["ai500_short"] = short_count > 0
                    result["ai500_long"] = long_count > 0
                    result["ai500_source"] = "local"
                    logger.info(f"✓ ai500 预热成功 (本地): list={len(ai500_data.get('coins', []))}, short={short_count}, long={long_count}")
                else:
                    result["errors"].append("ai500 预热失败")

            # 2. 预热 oi/top 和 oi/low（合并获取，共享历史数据请求）
            oi_results = await self._warmup_oi_rankings()
            if oi_results.get("top"):
                result["oi_top"] = True
                logger.info(f"✓ oi/top 预热成功，{len(oi_results['top'].get('positions', []))} 个持仓")
            else:
                result["errors"].append("oi/top 预热失败")
            if oi_results.get("low"):
                result["oi_low"] = True
                logger.info(f"✓ oi/low 预热成功，{len(oi_results['low'].get('positions', []))} 个持仓")
            else:
                result["errors"].append("oi/low 预热失败")

            # 3. 预热币种数据（覆盖所有分析通过的币种）
            coins_to_warmup = await self._get_coins_to_warmup(all_analyzed_symbols)
            warmed_coins = await self._warmup_coins(coins_to_warmup)
            result["coins"] = warmed_coins
            logger.info(f"✓ 币种数据预热成功，{len(warmed_coins)}/{len(coins_to_warmup)} 个")

        except Exception as e:
            logger.error(f"预热过程异常: {e}")
            result["success"] = False
            result["errors"].append(str(e))

        duration = (time.time() - start_time) * 1000
        result["duration_ms"] = round(duration, 2)

        self._last_warmup_time = time.time()
        self.cache.record_warmup(self._last_warmup_time)

        logger.info(f"缓存预热完成，耗时 {duration:.0f}ms")
        logger.info("=" * 50)

        return result

    def _analysis_to_coin_dict(self, c) -> dict:
        """将分析结果转换为字典

        注意：为了让 Go 后端能识别方向和入场时机信息，将关键标签编码到 tags 中
        标签顺序：
        1. TIMING:xxx - 入场时机（最重要）
        2. DIRECTION:xxx - 推荐方向
        3. VWAP:xxx - VWAP 信号
        4. 其他标签
        """
        # tags 已经在分析器中处理过了，包含了 TIMING 标签
        tags_with_info = list(c.tags) if c.tags else []

        # 在 TIMING 标签后面插入 DIRECTION 标签
        direction_tag = f"DIRECTION:{c.direction.value.upper()}"
        # 找到 TIMING 标签的位置，在其后插入 DIRECTION
        timing_idx = 0
        for i, tag in enumerate(tags_with_info):
            if tag.startswith("TIMING:"):
                timing_idx = i + 1
                break
        tags_with_info.insert(timing_idx, direction_tag)

        # 如果有 VWAP 信号，在 DIRECTION 后面添加
        if c.vwap_signal:
            tags_with_info.insert(timing_idx + 1, f"VWAP:{c.vwap_signal}")

        return {
            "pair": c.symbol,
            "score": c.score,
            "start_time": int(c.timestamp),
            "start_price": c.price,
            "last_score": c.score,
            "max_score": c.score,
            "max_price": c.price,
            "increase_percent": c.price_change_24h,
            "direction": c.direction.value,
            "confidence": c.confidence,
            "price": c.price,
            "price_change_1h": c.price_change_1h,
            "price_change_24h": c.price_change_24h,
            "volatility_24h": c.volatility_24h,
            "oi_change_1h": c.oi_change_1h,
            "oi_value_usd": c.oi_value,  # OI 价值（USD），用于验证流动性
            "funding_rate": c.funding_rate,
            "volume_24h": c.volume_24h,
            "tags": tags_with_info,
            "reasons": c.reasons,
            # === VWAP 相关字段 ===
            "vwap_1h": c.vwap_1h,
            "vwap_4h": c.vwap_4h,
            "price_vs_vwap_1h": c.price_vs_vwap_1h,
            "price_vs_vwap_4h": c.price_vs_vwap_4h,
            "vwap_signal": c.vwap_signal if c.vwap_signal else None,
            # === 入场时机相关字段（反追高核心）===
            "entry_timing": c.entry_timing,
            "timing_score": c.timing_score,
            "pullback_pct": c.pullback_pct,
            "required_pullback": c.required_pullback,
            "atr_pct": c.atr_pct,
            "support_distance": c.support_distance,
            "resistance_distance": c.resistance_distance,
            # === 动态止损建议 ===
            "suggested_stop_pct": c.suggested_stop_pct,
            "suggested_stop_price": c.suggested_stop_price,
            "volatility_level": c.volatility_level,
        }

    async def _warmup_ai500_from_valuescan(self) -> Optional[dict]:
        """从 ValueScan 预热 AI500 数据（机会+风险币种列表）。"""
        if not self.vs_collector or not self.vs_collector.is_available:
            return None
        if not self.vs_collector.can_afford(6):
            logger.warning("ValueScan 预算不足（需 6 积分），跳过 AI500 预热")
            return None

        try:
            chance_coins, risk_coins = await asyncio.gather(
                self.vs_collector.get_chance_coins(),
                self.vs_collector.get_risk_coins(),
            )
            if not chance_coins and not risk_coins:
                logger.warning("ValueScan 机会/风险币种均为空")
                return None

            from app.converters import valuescan_to_ai500_list

            data_balanced = valuescan_to_ai500_list(chance_coins or [], risk_coins or [], "balanced", self.ai500_limit)
            data_long = valuescan_to_ai500_list(chance_coins or [], risk_coins or [], "long", self.ai500_limit)
            data_short = valuescan_to_ai500_list(chance_coins or [], risk_coins or [], "short", self.ai500_limit)

            self.cache.set(APICache.KEY_AI500_LIST, data_balanced, self.cache_ttl)
            self.cache.set(APICache.KEY_AI500_LONG, data_long, self.cache_ttl)
            self.cache.set(APICache.KEY_AI500_SHORT, data_short, self.cache_ttl)

            self._last_vs_warmup_time = time.time()
            return data_balanced

        except Exception as e:
            logger.error(f"ValueScan AI500 预热失败: {e}")
            return None

    async def _warmup_ai500_all(self) -> tuple:
        """预热 ai500 所有方向的数据（list、short、long）"""
        try:
            # 加载 CMC 数据增强分析
            if self.cmc_collector:
                await self._load_cmc_data()

            # 获取分析结果
            all_analysis = await self.analyzer.analyze_all()

            # 导入所需类型
            from analysis.coin_analyzer import Direction

            # 1. 预热 ai500/list（默认排序）
            coins_all = sorted(
                all_analysis.values(),
                key=lambda x: (x.direction != Direction.NEUTRAL, x.score),
                reverse=True
            )[:self.ai500_limit]

            data_list = {
                "coins": [self._analysis_to_coin_dict(c) for c in coins_all],
                "count": len(coins_all),
                "direction": "all",
                "timestamp": int(time.time())
            }
            self.cache.set(APICache.KEY_AI500_LIST, data_list, self.cache_ttl)

            # 2. 预热 ai500/short
            short_candidates = await self.analyzer.get_short_candidates(self.ai500_limit)
            data_short = {
                "coins": [self._analysis_to_coin_dict(c) for c in short_candidates],
                "count": len(short_candidates),
                "direction": "short",
                "timestamp": int(time.time())
            }
            self.cache.set(APICache.KEY_AI500_SHORT, data_short, self.cache_ttl)

            # 3. 预热 ai500/long
            long_candidates = await self.analyzer.get_long_candidates(self.ai500_limit)
            data_long = {
                "coins": [self._analysis_to_coin_dict(c) for c in long_candidates],
                "count": len(long_candidates),
                "direction": "long",
                "timestamp": int(time.time())
            }
            self.cache.set(APICache.KEY_AI500_LONG, data_long, self.cache_ttl)

            # 返回所有分析通过的币种符号，用于扩大预热范围
            all_symbols = set(all_analysis.keys())
            return data_list, len(short_candidates), len(long_candidates), all_symbols

        except Exception as e:
            logger.error(f"预热 ai500 失败: {e}")
            return None, 0, 0, set()

    async def _warmup_ai500_list(self) -> Optional[dict]:
        """预热 ai500/list 数据（保留兼容）"""
        result = await self._warmup_ai500_all()
        return result[0] if result else None

    async def _warmup_oi_top(self) -> Optional[dict]:
        """预热 oi/top 数据"""
        return await self._warmup_oi_ranking("top")

    async def _warmup_oi_low(self) -> Optional[dict]:
        """预热 oi/low 数据"""
        return await self._warmup_oi_ranking("low")

    async def _warmup_oi_rankings(self) -> Dict[str, Optional[dict]]:
        """一次性预热 oi/top 和 oi/low，共享历史数据获取"""
        results = {"top": None, "low": None}
        try:
            rankings = await self.collector.warmup_oi_rankings(limit=20)
            tickers = await self.collector.get_all_tickers()

            for rank_type in ("top", "low"):
                oi_list = rankings.get(rank_type, [])
                cache_key = APICache.KEY_OI_TOP if rank_type == "top" else APICache.KEY_OI_LOW

                positions = []
                for i, oi in enumerate(oi_list):
                    ticker = tickers.get(oi.symbol)
                    price_change = ticker.price_change_24h if ticker else 0
                    positions.append({
                        "rank": i + 1,
                        "symbol": oi.symbol,
                        "current_oi": oi.oi_coins,
                        "oi_delta": oi.oi_coins * (oi.oi_change_1h / 100) if oi.oi_change_1h else 0,
                        "oi_delta_percent": oi.oi_change_1h,
                        "oi_delta_value": oi.oi_delta_value_1h,
                        "price_delta_percent": price_change,
                        "net_long": 0,
                        "net_short": 0
                    })

                data = {
                    "positions": positions,
                    "count": len(positions),
                    "exchange": "binance",
                    "rank_type": rank_type,
                    "time_range": "1小时",
                    "time_range_param": "1h",
                    "limit": 20
                }
                self.cache.set(cache_key, data, self.cache_ttl)
                results[rank_type] = data

        except Exception as e:
            logger.error(f"预热 oi rankings 失败: {e}")

        return results

    async def _warmup_oi_ranking(self, rank_type: str) -> Optional[dict]:
        """预热 OI 排行数据"""
        cache_key = APICache.KEY_OI_TOP if rank_type == "top" else APICache.KEY_OI_LOW
        try:
            oi_list = await self.collector.get_oi_ranking_with_history(rank_type=rank_type, limit=20)
            tickers = await self.collector.get_all_tickers()

            positions = []
            for i, oi in enumerate(oi_list):
                ticker = tickers.get(oi.symbol)
                price_change = ticker.price_change_24h if ticker else 0

                positions.append({
                    "rank": i + 1,
                    "symbol": oi.symbol,
                    "current_oi": oi.oi_coins,
                    "oi_delta": oi.oi_coins * (oi.oi_change_1h / 100) if oi.oi_change_1h else 0,
                    "oi_delta_percent": oi.oi_change_1h,
                    "oi_delta_value": oi.oi_delta_value_1h,
                    "price_delta_percent": price_change,
                    "net_long": 0,
                    "net_short": 0
                })

            data = {
                "positions": positions,
                "count": len(positions),
                "exchange": "binance",
                "rank_type": rank_type,
                "time_range": "1小时",
                "time_range_param": "1h",
                "limit": 20
            }

            self.cache.set(cache_key, data, self.cache_ttl)
            return data

        except Exception as e:
            logger.error(f"预热 oi/{rank_type} 失败: {e}")
            return None

    async def _get_coins_to_warmup(self, analyzed_symbols: Set[str] = None) -> Set[str]:
        """获取需要预热的币种列表（覆盖所有分析通过的币种）"""
        coins = set(FIXED_WARMUP_COINS)

        # 添加所有分析通过的币种
        if analyzed_symbols:
            coins.update(analyzed_symbols)

        return coins

    async def _warmup_coins(self, symbols: Set[str]) -> List[str]:
        """预热币种数据"""
        warmed = []

        # 一次性获取共享数据，避免每个币种重复请求
        tickers = await self.collector.get_all_tickers()
        funding_data = await self.collector.get_all_funding_rates()

        # 并发预热，分批处理避免限流
        batch_size = 10
        symbol_list = list(symbols)

        for i in range(0, len(symbol_list), batch_size):
            batch = symbol_list[i:i + batch_size]
            tasks = [self._warmup_single_coin(s, tickers, funding_data) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for symbol, result in zip(batch, results):
                if result is True:
                    warmed.append(symbol)

            # 避免限流
            if i + batch_size < len(symbol_list):
                await asyncio.sleep(0.1)

        return warmed

    async def _warmup_single_coin(self, symbol: str, tickers: dict = None, funding_data: dict = None) -> bool:
        """预热单个币种数据"""
        try:
            if tickers is None:
                tickers = await self.collector.get_all_tickers()
            ticker = tickers.get(symbol)

            if not ticker:
                return False

            # 获取 OI 数据
            oi_data = await self.collector.get_oi_with_history(symbol)

            # 获取资金费率
            if funding_data is None:
                funding_data = await self.collector.get_all_funding_rates()
            funding = funding_data.get(symbol)

            # 获取所有时间周期价格变化
            price_changes = await self.collector.calculate_all_price_changes(symbol, ticker.price)

            # 构建响应数据
            data = {
                "symbol": symbol,
                "price": ticker.price,
                "price_change": {k: v / 100 for k, v in price_changes.items()}
            }

            if oi_data:
                data["oi"] = {
                    "binance": {
                        "current_oi": oi_data.oi_coins,
                        "net_long": 0,
                        "net_short": 0,
                        "delta": {
                            "1h": {
                                "oi_delta": oi_data.oi_coins * (oi_data.oi_change_1h / 100),
                                "oi_delta_value": oi_data.oi_delta_value_1h,
                                "oi_delta_percent": oi_data.oi_change_1h / 100
                            },
                            "4h": {
                                "oi_delta": oi_data.oi_coins * (oi_data.oi_change_4h / 100),
                                "oi_delta_value": 0,
                                "oi_delta_percent": oi_data.oi_change_4h / 100
                            }
                        }
                    }
                }

            # 资金流向（空数据）
            data["netflow"] = {
                "institution": {"future": {}, "spot": {}},
                "personal": {"future": {}, "spot": {}}
            }

            if funding:
                data["funding_rate"] = funding.funding_rate

            # 缓存（使用与 fetch_coin_detail 一致的缓存键格式）
            default_include = "netflow,oi,price"
            cache_key = self.cache.get_coin_key(f"{symbol}:{default_include}")
            self.cache.set(cache_key, data, self.cache_ttl)

            return True

        except Exception as e:
            logger.debug(f"预热币种 {symbol} 失败: {e}")
            return False

    async def _load_cmc_data(self) -> None:
        """加载 CMC 数据到分析器（包含市值排名数据）"""
        if not self.cmc_collector or not self.analyzer:
            return

        try:
            # 并行获取 CMC 数据（新增 listings 用于市值排名）
            trending_result, gainers_losers_result, listings_result = await asyncio.gather(
                self.cmc_collector.get_trending(limit=50),
                self.cmc_collector.get_gainers_losers(limit=50),
                self.cmc_collector.get_latest_listings(limit=200),
                return_exceptions=True
            )

            trending_list = []
            gainers_list = []
            losers_list = []
            listings_dict = {}

            if isinstance(trending_result, list):
                trending_list = [
                    {"symbol": t.symbol, "trending_score": t.trending_score, "rank": t.cmc_rank}
                    for t in trending_result
                ]

            if isinstance(gainers_losers_result, tuple) and len(gainers_losers_result) == 2:
                gainers, losers = gainers_losers_result
                gainers_list = [
                    {"symbol": g.symbol, "percent_change_24h": g.percent_change_24h, "rank": g.cmc_rank}
                    for g in gainers
                ]
                losers_list = [
                    {"symbol": l.symbol, "percent_change_24h": l.percent_change_24h, "rank": l.cmc_rank}
                    for l in losers
                ]

            # 处理 listings 数据（用于市值权重计算）
            if isinstance(listings_result, dict):
                for symbol, coin_data in listings_result.items():
                    listings_dict[symbol] = {
                        "cmc_rank": coin_data.cmc_rank,
                        "market_cap": coin_data.market_cap,
                    }

            if trending_list or gainers_list or losers_list or listings_dict:
                self.analyzer.set_cmc_data(
                    trending=trending_list,
                    gainers=gainers_list,
                    losers=losers_list,
                    listings=listings_dict
                )

        except Exception as e:
            logger.warning(f"加载 CMC 数据失败: {e}")

    def get_last_warmup_time(self) -> float:
        """获取上次预热时间"""
        return self._last_warmup_time

    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running
