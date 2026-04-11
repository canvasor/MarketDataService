#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币种分析和分类模块

根据市场数据分析币种，分类为:
- 适合做多（bullish）
- 适合做空（bearish）
- 高波动/闪崩风险（flash_crash）

支持整合 CMC 热门数据，提升热门币种权重
"""

import logging
import re
import time
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collectors.binance_collector import BinanceCollector, TickerData, OIData
from core.config import settings

logger = logging.getLogger(__name__)


def contains_non_ascii(s: str) -> bool:
    """
    检测字符串是否包含非 ASCII 字符（如中文、日文、韩文等）

    用于过滤掉带有中文名称的币种，这些币种可能导致 LLM 分析失败
    例如：币安人生USDT
    """
    return bool(re.search(r'[^\x00-\x7F]', s))


class Direction(str, Enum):
    """交易方向"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class CoinAnalysis:
    """币种分析结果"""
    symbol: str
    direction: Direction
    score: float  # 0-100
    confidence: float  # 0-100

    # 价格指标
    price: float = 0.0
    price_change_1h: float = 0.0
    price_change_4h: float = 0.0
    price_change_24h: float = 0.0
    volatility_24h: float = 0.0

    # 持仓量指标
    oi_value: float = 0.0
    oi_change_1h: float = 0.0
    oi_delta_value_1h: float = 0.0

    # 资金费率
    funding_rate: float = 0.0

    # 交易量
    volume_24h: float = 0.0

    # VWAP 指标
    vwap_1h: float = 0.0           # 1小时 VWAP
    vwap_4h: float = 0.0           # 4小时 VWAP
    price_vs_vwap_1h: float = 0.0  # 价格相对于1h VWAP的偏离度 (%)
    price_vs_vwap_4h: float = 0.0  # 价格相对于4h VWAP的偏离度 (%)
    vwap_signal: str = ""          # "early_long" / "early_short" / "breakout_long" / "breakout_short" / ""

    # === 入场时机指标（反追高核心）===
    entry_timing: str = "neutral"      # "optimal" | "wait_pullback" | "chasing" | "extended" | "neutral"
    timing_score: float = 50.0         # 入场时机评分 0-100
    pullback_pct: float = 0.0          # 实际回调/反弹幅度
    required_pullback: float = 2.0     # 建议回调幅度（基于 ATR 动态计算）
    atr_pct: float = 0.0               # ATR 占价格百分比（波动性）
    support_distance: float = 0.0      # 距支撑位距离 (%)
    resistance_distance: float = 0.0   # 距阻力位距离 (%)
    swing_high: float = 0.0            # 近期高点
    swing_low: float = 0.0             # 近期低点

    # === 动态止损建议 ===
    suggested_stop_pct: float = 2.0    # 建议止损幅度 (%)，基于 ATR 动态计算
    suggested_stop_price: float = 0.0  # 建议止损价格
    volatility_level: str = "medium"   # 波动性级别: "low" / "medium" / "high" / "extreme"

    # 标签
    tags: List[str] = field(default_factory=list)

    # 分析原因
    reasons: List[str] = field(default_factory=list)

    # CMC 数据增强
    cmc_trending: bool = False  # 是否在 CMC 热门榜
    cmc_trending_score: float = 0.0  # CMC 热门分数
    cmc_rank: int = 0  # CMC 市值排名

    # === 市值权重（用于优先推荐大市值币种）===
    market_cap: float = 0.0           # 市值 (USD)
    market_cap_rank: int = 0          # 市值排名（同 cmc_rank，为了语义清晰单独保留）
    market_cap_weight: float = 0.5    # 市值权重 (0.1-1.0)，默认 0.5

    # 时间戳
    timestamp: float = field(default_factory=time.time)


class CoinAnalyzer:
    """币种分析器"""

    # === 市值权重配置（用于优先推荐大市值币种）===
    MARKET_CAP_WEIGHT_CONFIG = {
        # 分级权重：按 CMC 排名分级
        "tier_1_max_rank": 2,      # BTC, ETH
        "tier_1_weight": 1.0,
        "tier_2_max_rank": 10,     # SOL, BNB, XRP 等
        "tier_2_weight": 0.8,
        "tier_3_max_rank": 30,     # 中大型山寨
        "tier_3_weight": 0.6,
        "tier_4_max_rank": 100,    # 中型山寨
        "tier_4_weight": 0.4,
        "tier_5_max_rank": 200,    # 小型山寨
        "tier_5_weight": 0.2,
        "default_weight": 0.1,     # 200名之后
        "unknown_weight": 0.5,     # 无排名数据时的默认权重
        # 权重影响系数
        "weight_factor": 0.3,      # k 值：控制市值对最终分数的影响程度
    }

    # 币种黑名单（这些币种没有有效的市场数据，会导致 LLM 分析失败）
    SYMBOL_BLACKLIST: Set[str] = {
        "币安人生USDT",  # 中文名称币种：CMC 无数据，LLM 编码失败
        # 可在此添加其他需要排除的币种
    }

    def __init__(self, collector: BinanceCollector):
        self.collector = collector

        # CMC 数据缓存
        self._cmc_trending: Dict[str, dict] = {}
        self._cmc_gainers: Dict[str, dict] = {}
        self._cmc_losers: Dict[str, dict] = {}
        self._cmc_listings: Dict[str, dict] = {}  # 新增：CMC 市值排名缓存
        self._binance_symbols: Set[str] = set()

        # 阈值配置 - 降低阈值，让更多币种被分类
        self.config = {
            # 做空信号阈值（降低）
            "short_price_drop_1h": -1.5,  # 1h跌幅（原-2.0）
            "short_oi_surge": 3.0,  # OI增加（原5.0）
            "short_high_funding": 0.0003,  # 高费率（原0.0005）

            # 做多信号阈值（降低）
            "long_price_rise_1h": 1.5,  # 1h涨幅（原2.0）
            "long_oi_rise": 2.0,  # OI增加（原3.0）
            "long_low_funding": -0.0002,  # 负费率（原-0.0003）

            # 闪崩风险阈值
            "flash_crash_volatility": 8.0,  # 高波动
            "flash_crash_oi_surge": 15.0,  # OI急增
            "flash_crash_funding_extreme": 0.001,  # 极端费率

            # 过滤条件
            "min_volume_24h": 3_000_000,  # 最小交易量（降低）
            "min_oi_value": 2_000_000,  # 最小OI（降低）

            # CMC 权重加成
            "cmc_trending_bonus": 10,  # CMC 热门加分
            "cmc_top100_bonus": 5,  # CMC 市值前100加分
            "cmc_gainer_bonus": 8,  # CMC 涨幅榜加分
            "cmc_loser_bonus": 8,  # CMC 跌幅榜加分（做空信号）
        }

    @classmethod
    def calculate_market_cap_weight(cls, cmc_rank: int) -> float:
        """
        根据 CMC 市值排名计算权重

        分级权重（方案一）:
        - rank 1-2 (BTC/ETH): 1.0
        - rank 3-10: 0.8
        - rank 11-30: 0.6
        - rank 31-100: 0.4
        - rank 101-200: 0.2
        - rank 201+: 0.1
        - 无排名: 0.5

        Args:
            cmc_rank: CMC 市值排名，0 表示无排名数据

        Returns:
            权重值 (0.1 - 1.0)
        """
        cfg = cls.MARKET_CAP_WEIGHT_CONFIG

        if cmc_rank <= 0:
            return cfg["unknown_weight"]
        elif cmc_rank <= cfg["tier_1_max_rank"]:
            return cfg["tier_1_weight"]
        elif cmc_rank <= cfg["tier_2_max_rank"]:
            return cfg["tier_2_weight"]
        elif cmc_rank <= cfg["tier_3_max_rank"]:
            return cfg["tier_3_weight"]
        elif cmc_rank <= cfg["tier_4_max_rank"]:
            return cfg["tier_4_weight"]
        elif cmc_rank <= cfg["tier_5_max_rank"]:
            return cfg["tier_5_weight"]
        else:
            return cfg["default_weight"]

    @classmethod
    def apply_market_cap_weight(cls, base_score: float, market_cap_weight: float) -> float:
        """
        应用市值权重到基础分数

        公式: final_score = base_score * (1 + market_cap_weight * k)
        其中 k = 0.3 (可配置)

        Args:
            base_score: 原始分数
            market_cap_weight: 市值权重 (0.1 - 1.0)

        Returns:
            加权后的分数
        """
        k = cls.MARKET_CAP_WEIGHT_CONFIG["weight_factor"]
        return base_score * (1 + market_cap_weight * k)

    def set_cmc_data(
        self,
        trending: List[dict] = None,
        gainers: List[dict] = None,
        losers: List[dict] = None,
        listings: Dict[str, dict] = None
    ):
        """
        设置 CMC 数据用于增强分析

        Args:
            trending: CMC 热门榜数据
            gainers: CMC 涨幅榜数据
            losers: CMC 跌幅榜数据
            listings: CMC 市值排名数据 (symbol -> {rank, market_cap, ...})
        """
        if trending:
            self._cmc_trending = {
                self._normalize_symbol(c.get("symbol", "")): c
                for c in trending
            }
            logger.info(f"CMC trending 数据已加载: {len(self._cmc_trending)} 个")

        if gainers:
            self._cmc_gainers = {
                self._normalize_symbol(c.get("symbol", "")): c
                for c in gainers
            }
            logger.info(f"CMC gainers 数据已加载: {len(self._cmc_gainers)} 个")

        if losers:
            self._cmc_losers = {
                self._normalize_symbol(c.get("symbol", "")): c
                for c in losers
            }
            logger.info(f"CMC losers 数据已加载: {len(self._cmc_losers)} 个")

        if listings:
            self._cmc_listings = {
                self._normalize_symbol(symbol): data
                for symbol, data in listings.items()
            }
            logger.info(f"CMC listings 数据已加载: {len(self._cmc_listings)} 个")

    def _normalize_symbol(self, symbol: str) -> str:
        """标准化币种符号为 Binance 格式"""
        symbol = symbol.upper().strip()
        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"
        return symbol

    async def analyze_all(self, include_neutral: bool = True, filter_low_oi: bool = True) -> Dict[str, CoinAnalysis]:
        """
        分析所有币种

        Args:
            include_neutral: 是否包含中性币种
            filter_low_oi: 是否过滤低 OI 流动性币种（与 nofx 后端同步，阈值 15M USD）
        """
        logger.info("开始分析所有币种...")

        # 获取数据
        tickers = await self.collector.get_all_tickers()
        oi_data = await self.collector.get_all_oi()
        funding_data = await self.collector.get_all_funding_rates()

        # 缓存 Binance 币种列表
        self._binance_symbols = set(tickers.keys())

        # OI 流动性阈值（与 nofx 后端同步：15M USD）
        min_oi_value_usd = settings.min_oi_value_usd if filter_low_oi else 0

        results = {}
        filtered_count = 0
        blacklist_count = 0
        non_ascii_count = 0

        for symbol, ticker in tickers.items():
            # 过滤非 ASCII 字符币种（如中文名称：币安人生USDT）
            # 这些币种会导致 LLM 编码失败
            if contains_non_ascii(symbol):
                non_ascii_count += 1
                logger.debug(f"⚠️ {symbol} 包含非ASCII字符，已跳过")
                continue

            # 黑名单过滤（这些币种缺少有效数据，会导致 LLM 分析失败）
            if symbol in self.SYMBOL_BLACKLIST:
                blacklist_count += 1
                logger.debug(f"⚠️ {symbol} 在黑名单中，已跳过")
                continue

            # 过滤低交易量（但 CMC 热门币种放宽限制）
            is_cmc_hot = symbol in self._cmc_trending or symbol in self._cmc_gainers or symbol in self._cmc_losers
            min_volume = self.config["min_volume_24h"] / 2 if is_cmc_hot else self.config["min_volume_24h"]

            if ticker.volume_24h < min_volume:
                continue

            oi = oi_data.get(symbol)
            funding = funding_data.get(symbol)

            # OI 流动性过滤（与 nofx 后端同步）
            # oi.oi_value 已经是 USDT 价值
            if filter_low_oi and oi:
                if oi.oi_value < min_oi_value_usd:
                    filtered_count += 1
                    logger.debug(f"⚠️ {symbol} OI 流动性不足 ({oi.oi_value/1_000_000:.2f}M < {min_oi_value_usd/1_000_000:.0f}M USD)，已过滤")
                    continue

            analysis = await self._analyze_coin(ticker, oi, funding)
            if analysis:
                # 只返回有方向的，除非 include_neutral=True
                if include_neutral or analysis.direction != Direction.NEUTRAL:
                    results[symbol] = analysis

        if non_ascii_count > 0:
            logger.info(f"非ASCII字符过滤: {non_ascii_count} 个币种被排除（如中文名称）")
        if blacklist_count > 0:
            logger.info(f"黑名单过滤: {blacklist_count} 个币种被排除")
        if filtered_count > 0:
            logger.info(f"OI 流动性过滤: {filtered_count} 个币种被排除（阈值 {min_oi_value_usd/1_000_000:.0f}M USD）")
        logger.info(f"分析完成，共 {len(results)} 个币种")
        return results

    def is_binance_symbol(self, symbol: str) -> bool:
        """检查币种是否在 Binance 合约存在"""
        normalized = self._normalize_symbol(symbol)
        return normalized in self._binance_symbols

    async def _analyze_coin(
        self,
        ticker: TickerData,
        oi: Optional[OIData],
        funding: Optional['FundingData']
    ) -> Optional[CoinAnalysis]:
        """分析单个币种"""
        symbol = ticker.symbol

        # 计算 1h 和 4h 价格变化
        price_change_1h, price_change_4h = await self.collector.calculate_price_changes(
            symbol, ticker.price
        )

        # 更新 ticker
        ticker.price_change_1h = price_change_1h
        ticker.price_change_4h = price_change_4h

        # 初始化分析结果
        analysis = CoinAnalysis(
            symbol=symbol,
            direction=Direction.NEUTRAL,
            score=50.0,
            confidence=50.0,
            price=ticker.price,
            price_change_1h=price_change_1h,
            price_change_4h=price_change_4h,
            price_change_24h=ticker.price_change_24h,
            volatility_24h=ticker.volatility_24h,
            volume_24h=ticker.volume_24h
        )

        # OI 数据
        if oi:
            analysis.oi_value = oi.oi_value
            analysis.oi_change_1h = oi.oi_change_1h
            analysis.oi_delta_value_1h = oi.oi_delta_value_1h

        # 资金费率
        if funding:
            analysis.funding_rate = funding.funding_rate

        # VWAP 数据
        await self._calculate_vwap_signals(analysis)

        # CMC 数据增强
        self._enhance_with_cmc(analysis)

        # 计算方向
        self._calculate_direction(analysis)

        # === 核心：计算入场时机（反追高逻辑）===
        await self._calculate_entry_timing(analysis)

        # === 计算动态止损建议 ===
        self._calculate_suggested_stop(analysis)

        # 计算评分（现在会根据入场时机调整分数）
        self._calculate_score(analysis)
        self._add_tags(analysis)

        return analysis

    def _calculate_suggested_stop(self, analysis: CoinAnalysis):
        """
        计算动态止损建议

        根据 ATR 和币种类型计算建议止损幅度：
        - BTC/ETH (低波动): 0.8-1.0x ATR
        - 中等波动山寨: 1.0-1.2x ATR
        - 高波动山寨: 1.2-1.5x ATR
        - 极端波动: 1.5-2.0x ATR（并建议降低仓位）
        """
        atr_pct = analysis.atr_pct
        symbol = analysis.symbol
        price = analysis.price

        # 确定波动性级别
        if atr_pct <= 2.0:
            volatility_level = "low"
            stop_multiplier = 0.8
        elif atr_pct <= 4.0:
            volatility_level = "medium"
            stop_multiplier = 1.0
        elif atr_pct <= 6.0:
            volatility_level = "high"
            stop_multiplier = 1.2
        else:
            volatility_level = "extreme"
            stop_multiplier = 1.5

        # BTC/ETH 特殊处理：它们通常更稳定
        if symbol in ["BTCUSDT", "ETHUSDT"]:
            # 即使 ATR 显示高，也不应设太宽止损
            stop_multiplier = min(stop_multiplier, 1.0)
            if volatility_level == "extreme":
                volatility_level = "high"

        # 计算建议止损幅度
        suggested_stop_pct = atr_pct * stop_multiplier

        # 设置最小和最大止损限制
        # 最小止损：1% (避免被小波动扫掉)
        # 最大止损：8% (避免单笔亏损过大)
        suggested_stop_pct = max(1.0, min(8.0, suggested_stop_pct))

        # 计算止损价格
        if analysis.direction == Direction.LONG:
            suggested_stop_price = price * (1 - suggested_stop_pct / 100)
        elif analysis.direction == Direction.SHORT:
            suggested_stop_price = price * (1 + suggested_stop_pct / 100)
        else:
            suggested_stop_price = 0.0

        # 写入分析结果
        analysis.suggested_stop_pct = round(suggested_stop_pct, 2)
        analysis.suggested_stop_price = round(suggested_stop_price, 4)
        analysis.volatility_level = volatility_level

        # 添加止损相关的原因说明
        if volatility_level == "extreme":
            analysis.reasons.append(f"⚠️ 极端波动(ATR:{atr_pct:.1f}%)，建议止损{suggested_stop_pct:.1f}%，降低仓位")
        elif volatility_level == "high":
            analysis.reasons.append(f"高波动(ATR:{atr_pct:.1f}%)，建议止损{suggested_stop_pct:.1f}%")
        elif volatility_level == "low" and symbol not in ["BTCUSDT", "ETHUSDT"]:
            analysis.reasons.append(f"低波动(ATR:{atr_pct:.1f}%)，可用较紧止损{suggested_stop_pct:.1f}%")

    async def _calculate_entry_timing(self, analysis: CoinAnalysis):
        """
        计算入场时机指标（反追高核心逻辑）

        根据价格走势判断当前是否适合入场：
        - optimal: 回调到位，最佳入场点
        - wait_pullback: 等待回调
        - chasing: 追高/追空风险
        - extended: 过度延伸
        """
        try:
            # 根据方向调用底层计算
            direction = "long" if analysis.direction == Direction.LONG else "short"
            timing_data = await self.collector.calculate_entry_timing(analysis.symbol, direction)

            # 填充分析结果
            analysis.entry_timing = timing_data.get("timing", "neutral")
            analysis.timing_score = timing_data.get("timing_score", 50)
            analysis.pullback_pct = timing_data.get("pullback_pct", 0.0)
            analysis.required_pullback = timing_data.get("required_pullback", 2.0)
            analysis.atr_pct = timing_data.get("atr_pct", 0.0)
            analysis.support_distance = timing_data.get("support_distance", 0.0)
            analysis.resistance_distance = timing_data.get("resistance_distance", 0.0)
            analysis.swing_high = timing_data.get("swing_high", 0.0)
            analysis.swing_low = timing_data.get("swing_low", 0.0)

            # 添加入场时机相关的原因
            timing_reasons = timing_data.get("reasons", [])
            for reason in timing_reasons:
                analysis.reasons.append(f"[时机] {reason}")

        except Exception as e:
            logger.debug(f"Calculate entry timing error for {analysis.symbol}: {e}")

    async def _calculate_vwap_signals(self, analysis: CoinAnalysis):
        """计算 VWAP 相关指标和早期信号"""
        try:
            vwap_data = await self.collector.calculate_multi_period_vwap(analysis.symbol)

            # 设置 VWAP 值
            analysis.vwap_1h = vwap_data["1h"].get("vwap", 0.0)
            analysis.vwap_4h = vwap_data["4h"].get("vwap", 0.0)
            analysis.price_vs_vwap_1h = vwap_data["1h"].get("price_vs_vwap", 0.0)
            analysis.price_vs_vwap_4h = vwap_data["4h"].get("price_vs_vwap", 0.0)

            # 计算 VWAP 早期信号
            price_vs_vwap = analysis.price_vs_vwap_4h
            oi_change = analysis.oi_change_1h
            funding = analysis.funding_rate

            # 早期做多信号：价格在 VWAP 下方，但 OI 在增加（资金悄悄进场）
            if price_vs_vwap < -0.3 and oi_change > 0.5 and funding < 0.0001:
                analysis.vwap_signal = "early_long"
                analysis.reasons.append(f"VWAP早期做多: 价格低于VWAP {abs(price_vs_vwap):.2f}% + OI增加")

            # 早期做空信号：价格在 VWAP 上方较多，资金费率偏高（可能回调）
            elif price_vs_vwap > 0.5 and funding > 0.0003:
                analysis.vwap_signal = "early_short"
                analysis.reasons.append(f"VWAP早期做空: 价格高于VWAP {price_vs_vwap:.2f}% + 高费率")

            # 突破做多信号：价格刚从下方突破 VWAP
            elif -0.2 < price_vs_vwap < 0.3 and analysis.price_change_1h > 0.5:
                analysis.vwap_signal = "breakout_long"
                analysis.reasons.append("VWAP突破做多: 价格向上突破VWAP")

            # 突破做空信号：价格刚从上方跌破 VWAP
            elif -0.3 < price_vs_vwap < 0.2 and analysis.price_change_1h < -0.5:
                analysis.vwap_signal = "breakout_short"
                analysis.reasons.append("VWAP突破做空: 价格向下跌破VWAP")

        except Exception as e:
            logger.debug(f"Calculate VWAP signals error for {analysis.symbol}: {e}")

    def _enhance_with_cmc(self, analysis: CoinAnalysis):
        """用 CMC 数据增强分析"""
        symbol = analysis.symbol

        # CMC 热门榜
        if symbol in self._cmc_trending:
            cmc_data = self._cmc_trending[symbol]
            analysis.cmc_trending = True
            analysis.cmc_trending_score = cmc_data.get("trending_score", 0)
            analysis.cmc_rank = cmc_data.get("rank", 0)
            analysis.tags.append("cmc_trending")
            analysis.reasons.append(f"CMC热门榜 (热度:{analysis.cmc_trending_score:.1f})")

        # CMC 涨幅榜
        if symbol in self._cmc_gainers:
            cmc_data = self._cmc_gainers[symbol]
            analysis.tags.append("cmc_gainer")
            pct = cmc_data.get("percent_change_24h", 0)
            analysis.reasons.append(f"CMC涨幅榜 ({pct:+.2f}%)")

        # CMC 跌幅榜
        if symbol in self._cmc_losers:
            cmc_data = self._cmc_losers[symbol]
            analysis.tags.append("cmc_loser")
            pct = cmc_data.get("percent_change_24h", 0)
            analysis.reasons.append(f"CMC跌幅榜 ({pct:.2f}%)")

        # 设置市值排名（优先从 listings 获取，其次从其他数据源）
        if not analysis.cmc_rank:
            for data in [self._cmc_gainers.get(symbol), self._cmc_losers.get(symbol)]:
                if data and data.get("rank"):
                    analysis.cmc_rank = data.get("rank", 0)
                    break

        # === 从 CMC listings 获取市值数据 ===
        if symbol in self._cmc_listings:
            listing_data = self._cmc_listings[symbol]
            analysis.market_cap = listing_data.get("market_cap", 0)
            analysis.market_cap_rank = listing_data.get("cmc_rank", 0)
            # 如果之前没有设置 cmc_rank，从 listings 获取
            if not analysis.cmc_rank:
                analysis.cmc_rank = analysis.market_cap_rank

        # 确保 market_cap_rank 与 cmc_rank 同步
        if analysis.cmc_rank and not analysis.market_cap_rank:
            analysis.market_cap_rank = analysis.cmc_rank

        # 计算市值权重
        analysis.market_cap_weight = self.calculate_market_cap_weight(analysis.market_cap_rank)

    def _calculate_direction(self, analysis: CoinAnalysis):
        """计算交易方向"""
        short_signals = 0
        long_signals = 0

        # === 做空信号 ===

        # 1. 价格下跌 + OI 增加 = 空头进场（统一OI门槛为2%，与做多一致）
        if analysis.price_change_1h < self.config["short_price_drop_1h"]:
            short_signals += 1
            analysis.reasons.append(f"1h跌幅 {analysis.price_change_1h:.2f}%")

            # 统一使用 2% OI 门槛（原来做空是3%，做多是2%，现在统一为2%）
            if analysis.oi_change_1h > self.config["long_oi_rise"]:  # 使用做多的门槛2%
                short_signals += 2  # 强信号
                analysis.reasons.append(f"空头主导: OI增 {analysis.oi_change_1h:.2f}% + 价格下跌")

        # 2. 高资金费率 = 过度做多，可能回调
        if analysis.funding_rate > self.config["short_high_funding"]:
            short_signals += 1
            analysis.reasons.append(f"高费率 {analysis.funding_rate*100:.4f}%")

        # 3. 高波动 + 下跌趋势
        if analysis.volatility_24h > 6 and analysis.price_change_24h < -3:
            short_signals += 1
            analysis.reasons.append("高波动下跌趋势")

        # 4. CMC 跌幅榜（做空信号）
        if "cmc_loser" in analysis.tags:
            short_signals += 1

        # 5. VWAP 做空信号
        if analysis.vwap_signal in ["early_short", "breakout_short"]:
            short_signals += 1

        # === 做多信号 ===

        # 1. 价格上涨 + OI 增加 = 多头进场
        if analysis.price_change_1h > self.config["long_price_rise_1h"]:
            long_signals += 1
            analysis.reasons.append(f"1h涨幅 {analysis.price_change_1h:.2f}%")

            if analysis.oi_change_1h > self.config["long_oi_rise"]:
                long_signals += 2  # 强信号
                analysis.reasons.append(f"多头主导: OI增 {analysis.oi_change_1h:.2f}% + 价格上涨")

        # 2. 负资金费率 = 过度做空，可能反弹
        if analysis.funding_rate < self.config["long_low_funding"]:
            long_signals += 1
            analysis.reasons.append(f"负费率 {analysis.funding_rate*100:.4f}%")

        # 3. 价格回调后企稳
        if -3 < analysis.price_change_24h < 0 and analysis.price_change_1h > 0:
            long_signals += 1
            analysis.reasons.append("回调后企稳反弹")

        # 4. CMC 涨幅榜（做多信号）
        if "cmc_gainer" in analysis.tags:
            long_signals += 1

        # 5. CMC 热门榜加成（跟随趋势方向）
        if analysis.cmc_trending:
            if analysis.price_change_24h > 3:
                long_signals += 1
            elif analysis.price_change_24h < -3:
                short_signals += 1

        # 6. VWAP 做多信号
        if analysis.vwap_signal in ["early_long", "breakout_long"]:
            long_signals += 1

        # 判定方向（降低阈值：1个信号即可触发，但需要明确优势）
        if short_signals > long_signals and short_signals >= 1:
            analysis.direction = Direction.SHORT
        elif long_signals > short_signals and long_signals >= 1:
            analysis.direction = Direction.LONG
        else:
            analysis.direction = Direction.NEUTRAL

    def _calculate_score(self, analysis: CoinAnalysis):
        """
        计算评分（0-100）

        评分逻辑升级：
        1. 基础分数根据方向信号强度
        2. 入场时机调整（核心反追高逻辑）：
           - optimal: +20分 (回调到位，最佳入场)
           - wait_pullback: 0分 (等待中)
           - chasing: -25分 (追高风险，大幅扣分)
           - extended: -15分 (过度延伸)
        3. 置信度同步调整
        """
        score = 50.0  # 基础分
        confidence = 50.0

        if analysis.direction == Direction.SHORT:
            # 做空评分
            # 价格下跌幅度
            score += min(abs(analysis.price_change_1h) * 3, 15)
            # OI 增加幅度
            score += min(analysis.oi_change_1h * 2, 15)
            # 高费率
            score += min(analysis.funding_rate * 5000, 10)
            # 波动率
            score += min(analysis.volatility_24h * 0.5, 10)

            # 置信度
            if analysis.oi_change_1h > 5 and analysis.price_change_1h < -2:
                confidence += 20  # OI+价格共振
            if analysis.funding_rate > 0.0005:
                confidence += 10
            if abs(analysis.price_change_1h) > 3:
                confidence += 10

            # CMC 跌幅榜加分
            if "cmc_loser" in analysis.tags:
                score += self.config["cmc_loser_bonus"]
                confidence += 5

        elif analysis.direction == Direction.LONG:
            # 做多评分
            score += min(analysis.price_change_1h * 3, 15)
            score += min(analysis.oi_change_1h * 2, 15)
            score += min(abs(analysis.funding_rate) * 3000 if analysis.funding_rate < 0 else 0, 10)

            # 置信度
            if analysis.oi_change_1h > 3 and analysis.price_change_1h > 2:
                confidence += 20
            if analysis.funding_rate < -0.0003:
                confidence += 10

            # CMC 涨幅榜加分
            if "cmc_gainer" in analysis.tags:
                score += self.config["cmc_gainer_bonus"]
                confidence += 5

        # CMC 通用加分（热门榜、市值前100）
        if analysis.cmc_trending:
            score += self.config["cmc_trending_bonus"]
            confidence += 5
        if 0 < analysis.cmc_rank <= 100:
            score += self.config["cmc_top100_bonus"]
            confidence += 3

        # ============================================================
        # 核心：入场时机评分调整（反追高逻辑）
        # ============================================================
        timing = analysis.entry_timing

        if timing == "optimal":
            # 最佳入场时机：回调到位，大幅加分
            score += 20
            confidence += 15
            analysis.reasons.append(f"✅ 最佳入场时机 (回调{analysis.pullback_pct:.1f}%)")

        elif timing == "wait_pullback":
            # 等待回调：轻微减分，提示等待
            score -= 5
            confidence -= 5
            analysis.reasons.append(f"⏳ 建议等待回调 (需{analysis.required_pullback:.1f}%)")

        elif timing == "chasing":
            # 追高/追空风险：大幅扣分！这是反追高的核心
            score -= 25
            confidence -= 20
            analysis.reasons.append(f"⚠️ 追高风险! 刚暴涨/暴跌，等待回调")

        elif timing == "extended":
            # 过度延伸：显著扣分
            score -= 15
            confidence -= 10
            analysis.reasons.append(f"⚠️ 过度延伸，空间有限")

        # 额外惩罚：如果价格涨幅超过建议回调幅度的2倍，直接腰斩分数
        if analysis.direction == Direction.LONG:
            if analysis.price_change_1h > analysis.required_pullback * 2:
                penalty = min(15, analysis.price_change_1h - analysis.required_pullback * 2) * 2
                score -= penalty
                confidence -= penalty * 0.5
                analysis.reasons.append(f"🚫 1h涨幅{analysis.price_change_1h:.1f}%过大，严重追高")
        elif analysis.direction == Direction.SHORT:
            if analysis.price_change_1h < -analysis.required_pullback * 2:
                penalty = min(15, abs(analysis.price_change_1h) - analysis.required_pullback * 2) * 2
                score -= penalty
                confidence -= penalty * 0.5
                analysis.reasons.append(f"🚫 1h跌幅{abs(analysis.price_change_1h):.1f}%过大，严重追空")

        # 限制范围
        analysis.score = max(0, min(100, score))
        analysis.confidence = max(0, min(100, confidence))

    def _add_tags(self, analysis: CoinAnalysis):
        """添加标签"""
        # 保留已有的标签（如 CMC 标签）
        tags = analysis.tags.copy() if analysis.tags else []

        # === 入场时机标签（最重要，放在最前面）===
        timing = analysis.entry_timing
        if timing == "optimal":
            tags.insert(0, "TIMING:OPTIMAL")  # 最佳入场
        elif timing == "wait_pullback":
            tags.insert(0, "TIMING:WAIT_PULLBACK")  # 等待回调
        elif timing == "chasing":
            tags.insert(0, "TIMING:CHASING")  # 追高风险
        elif timing == "extended":
            tags.insert(0, "TIMING:EXTENDED")  # 过度延伸
        else:
            tags.insert(0, "TIMING:NEUTRAL")

        # ATR/波动性标签（用于止损参考）
        if analysis.atr_pct > 5:
            tags.append(f"ATR:{analysis.atr_pct:.1f}%")
            tags.append("high_atr")
        elif analysis.atr_pct > 3:
            tags.append(f"ATR:{analysis.atr_pct:.1f}%")

        # 回调幅度标签
        if analysis.pullback_pct > 0:
            if analysis.direction == Direction.LONG:
                tags.append(f"PULLBACK:{analysis.pullback_pct:.1f}%")
            else:
                tags.append(f"BOUNCE:{analysis.pullback_pct:.1f}%")

        # 波动性标签
        if analysis.volatility_24h > 10:
            tags.append("extreme_volatility")
        elif analysis.volatility_24h > 6:
            tags.append("high_volatility")

        # 交易量标签
        if analysis.volume_24h > 500_000_000:
            tags.append("high_volume")

        # OI 标签
        if analysis.oi_change_1h > 10:
            tags.append("oi_surge")
        elif analysis.oi_change_1h < -10:
            tags.append("oi_drop")

        # 趋势标签
        if analysis.price_change_24h > 10:
            tags.append("strong_uptrend")
        elif analysis.price_change_24h < -10:
            tags.append("strong_downtrend")

        # 闪崩风险标签
        if self._check_flash_crash_risk(analysis):
            tags.append("flash_crash_risk")

        # 费率极端
        if abs(analysis.funding_rate) > 0.001:
            tags.append("extreme_funding")

        analysis.tags = tags

    def _check_flash_crash_risk(self, analysis: CoinAnalysis) -> bool:
        """检查闪崩风险"""
        risk_score = 0

        # 高波动 + 下跌
        if analysis.volatility_24h > self.config["flash_crash_volatility"]:
            risk_score += 1
        if analysis.price_change_24h < -5:
            risk_score += 1

        # OI 急剧变化
        if abs(analysis.oi_change_1h) > self.config["flash_crash_oi_surge"]:
            risk_score += 1

        # 极端费率
        if abs(analysis.funding_rate) > self.config["flash_crash_funding_extreme"]:
            risk_score += 1

        # OI 增加 + 价格下跌 = 空头在砸
        if analysis.oi_change_1h > 10 and analysis.price_change_1h < -3:
            risk_score += 2

        return risk_score >= 3

    def _get_weighted_score(self, analysis: CoinAnalysis) -> float:
        """
        获取市值加权后的分数，用于排序

        公式: weighted_score = base_score * (1 + market_cap_weight * k)
        """
        return self.apply_market_cap_weight(analysis.score, analysis.market_cap_weight)

    async def get_short_candidates(self, limit: int = 20) -> List[CoinAnalysis]:
        """获取做空候选币种（市值加权排序）"""
        all_analysis = await self.analyze_all()

        # 筛选做空方向
        short_coins = [
            a for a in all_analysis.values()
            if a.direction == Direction.SHORT
        ]

        # 按市值加权分数排序（大市值币种优先）
        short_coins.sort(key=lambda x: (self._get_weighted_score(x), x.confidence), reverse=True)

        return short_coins[:limit]

    async def get_long_candidates(self, limit: int = 20) -> List[CoinAnalysis]:
        """获取做多候选币种（市值加权排序）"""
        all_analysis = await self.analyze_all()

        # 筛选做多方向
        long_coins = [
            a for a in all_analysis.values()
            if a.direction == Direction.LONG
        ]

        # 按市值加权分数排序（大市值币种优先）
        long_coins.sort(key=lambda x: (self._get_weighted_score(x), x.confidence), reverse=True)

        return long_coins[:limit]

    async def get_flash_crash_candidates(self, limit: int = 20) -> List[CoinAnalysis]:
        """获取闪崩风险币种（适合做空埋伏）"""
        all_analysis = await self.analyze_all()

        # 筛选有闪崩风险的
        flash_crash_coins = [
            a for a in all_analysis.values()
            if "flash_crash_risk" in a.tags
        ]

        # 按波动率和 OI 变化排序
        flash_crash_coins.sort(
            key=lambda x: (x.volatility_24h + abs(x.oi_change_1h)),
            reverse=True
        )

        return flash_crash_coins[:limit]

    async def get_high_volatility_coins(self, limit: int = 20) -> List[CoinAnalysis]:
        """获取高波动币种"""
        all_analysis = await self.analyze_all()

        # 筛选高波动
        high_vol = [
            a for a in all_analysis.values()
            if a.volatility_24h > 5
        ]

        # 按波动率排序
        high_vol.sort(key=lambda x: x.volatility_24h, reverse=True)

        return high_vol[:limit]

    async def get_balanced_candidates(self, limit: int = 9) -> List[CoinAnalysis]:
        """
        获取多空平衡的候选币种（市值加权排序）

        平衡逻辑：
        - 如果 limit 为偶数：返回一半做多信号，一半做空信号
        - 如果 limit 为奇数：做空信号比做多信号多一个（优先做空以对抗追高）
        - 排序使用市值加权分数，优先推荐大市值币种

        Args:
            limit: 返回的总数量

        Returns:
            平衡后的候选币种列表
        """
        all_analysis = await self.analyze_all()

        # 分离多空信号
        longs = [
            a for a in all_analysis.values()
            if a.direction == Direction.LONG
        ]
        shorts = [
            a for a in all_analysis.values()
            if a.direction == Direction.SHORT
        ]

        # 按市值加权分数排序（大市值币种优先）
        longs.sort(key=lambda x: (self._get_weighted_score(x), x.confidence), reverse=True)
        shorts.sort(key=lambda x: (self._get_weighted_score(x), x.confidence), reverse=True)

        # 计算多空数量
        if limit % 2 == 0:
            # 偶数：各一半
            long_count = limit // 2
            short_count = limit // 2
        else:
            # 奇数：做空多一个
            long_count = limit // 2
            short_count = limit // 2 + 1

        # 截取
        selected_longs = longs[:long_count]
        selected_shorts = shorts[:short_count]

        # 如果某一方不足，用另一方补充
        if len(selected_shorts) < short_count and len(longs) > long_count:
            # 空头不足，用更多多头补充
            extra_needed = short_count - len(selected_shorts)
            selected_longs = longs[:long_count + extra_needed]
        elif len(selected_longs) < long_count and len(shorts) > short_count:
            # 多头不足，用更多空头补充
            extra_needed = long_count - len(selected_longs)
            selected_shorts = shorts[:short_count + extra_needed]

        # 合并并按市值加权分数排序
        result = selected_longs + selected_shorts
        result.sort(key=lambda x: (self._get_weighted_score(x), x.confidence), reverse=True)

        logger.info(f"多空平衡: 做多 {len(selected_longs)} 个, 做空 {len(selected_shorts)} 个, 总计 {len(result)} 个")

        return result[:limit]

    async def get_early_signal_candidates(self, limit: int = 20) -> List[CoinAnalysis]:
        """
        获取早期信号候选币种（基于VWAP）

        返回有早期信号的币种，用于提前布局
        """
        all_analysis = await self.analyze_all()

        # 筛选有 VWAP 早期信号的币种
        early_signals = [
            a for a in all_analysis.values()
            if a.vwap_signal in ["early_long", "early_short", "breakout_long", "breakout_short"]
        ]

        # 按评分排序
        early_signals.sort(key=lambda x: (x.score, x.confidence), reverse=True)

        return early_signals[:limit]
