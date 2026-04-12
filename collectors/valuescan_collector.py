#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ValueScan 数据采集器。

提供 AI 机会/风险币种列表和链上资金流数据，作为 MarketDataService 的主数据源。
当预算不足或接口异常时，上层可平滑回退到 Binance + OKX 本地数据源。

接口参考（路径相对于 base_url，如 https://api.valuescan.io/api/open/v1）:
- POST /ai/getChanceCoinList  (3 积分)
- POST /ai/getRiskCoinList     (3 积分)
- POST /trade/getCoinTrade     (3 积分)
- POST /vs-token/list          (1 积分)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp
from cachetools import TTLCache

from core.provider_budget import ProviderBudgetTracker

logger = logging.getLogger(__name__)

PROVIDER_NAME = "valuescan"


class ValueScanCollector:
    """ValueScan 数据采集器 — AI 机会/风险币种 + 资金流数据。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        secret_key: str,
        budget_tracker: ProviderBudgetTracker,
        monthly_point_limit: int = 50000,
        minute_point_limit: int = 20,
        coin_trade_cache_ttl: int = 600,
        token_list_cache_ttl: int = 86400,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.secret_key = secret_key
        self.budget_tracker = budget_tracker
        self.monthly_point_limit = monthly_point_limit
        self.minute_point_limit = minute_point_limit

        # 缓存
        self._token_map_cache: TTLCache = TTLCache(maxsize=1, ttl=token_list_cache_ttl)
        self._chance_cache: TTLCache = TTLCache(maxsize=1, ttl=300)
        self._risk_cache: TTLCache = TTLCache(maxsize=1, ttl=300)
        self._coin_trade_cache: TTLCache = TTLCache(maxsize=500, ttl=coin_trade_cache_ttl)

        # symbol → vsTokenId 映射
        self._symbol_to_token_id: Dict[str, int] = {}

        # HTTP 会话（延迟创建）
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """ValueScan 是否已配置且可用。"""
        return bool(self.api_key and self.secret_key and self.base_url)

    def can_afford(self, points: int = 3) -> bool:
        """检查是否有足够的预算余量。"""
        gate = self.budget_tracker.can_attempt(
            PROVIDER_NAME,
            minute_limit=self.minute_point_limit,
            monthly_soft_limit=self.monthly_point_limit,
            count=points,
        )
        return gate["allowed"]

    # ------------------------------------------------------------------
    # HTTP 基础设施
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    def _get_sign_headers(self, raw_body: str) -> Dict[str, str]:
        """生成 HMAC-SHA256 签名请求头。"""
        timestamp = str(int(time.time() * 1000))
        sign_content = timestamp + raw_body
        sign = hmac.new(
            self.secret_key.encode("utf-8"),
            sign_content.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-KEY": self.api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGN": sign,
            "Content-Type": "application/json; charset=utf-8",
        }

    async def _post(
        self,
        path: str,
        body: dict,
        points_cost: int = 3,
    ) -> Optional[Any]:
        """发送带签名和预算保护的 POST 请求。

        返回 data 字段，或 None（预算不足/请求失败时）。
        """
        # 预算检查
        gate = self.budget_tracker.can_attempt(
            PROVIDER_NAME,
            minute_limit=self.minute_point_limit,
            monthly_soft_limit=self.monthly_point_limit,
            count=points_cost,
        )
        if not gate["allowed"]:
            logger.warning(
                f"ValueScan 预算受限: minute={gate['minute_used']}/{gate['minute_limit']}, "
                f"monthly={gate['monthly_used']}/{gate['monthly_soft_limit']}, "
                f"requested={gate['requested']}"
            )
            return None

        # 签名
        raw_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        headers = self._get_sign_headers(raw_body)
        url = f"{self.base_url}/{path.lstrip('/')}"

        # 记录请求
        self.budget_tracker.record_attempt(PROVIDER_NAME, count=points_cost)

        try:
            session = await self._get_session()
            async with session.post(url, headers=headers, data=raw_body) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    self.budget_tracker.record_result(
                        PROVIDER_NAME, False,
                        error=f"HTTP {resp.status}: {error_text[:200]}",
                        count=points_cost,
                    )
                    logger.error(f"ValueScan {path} HTTP {resp.status}: {error_text[:200]}")
                    return None

                result = await resp.json()
                code = result.get("code")
                if code == 200:
                    self.budget_tracker.record_result(PROVIDER_NAME, True, count=points_cost)
                    return result.get("data")
                else:
                    msg = result.get("message", "unknown")
                    self.budget_tracker.record_result(
                        PROVIDER_NAME, False,
                        error=f"code={code}: {msg}",
                        count=points_cost,
                    )
                    logger.error(f"ValueScan {path} 业务错误 code={code}: {msg}")
                    return None

        except Exception as e:
            self.budget_tracker.record_result(
                PROVIDER_NAME, False, error=str(e)[:300], count=points_cost,
            )
            logger.error(f"ValueScan {path} 请求异常: {e}")
            return None

    # ------------------------------------------------------------------
    # Token 映射
    # ------------------------------------------------------------------

    async def refresh_token_map(self) -> int:
        """刷新 symbol → vsTokenId 映射，返回映射数量。"""
        data = await self._post("/vs-token/list", {"search": ""}, points_cost=1)
        if not data or not isinstance(data, list):
            logger.warning("ValueScan token list 为空或格式异常")
            return len(self._symbol_to_token_id)

        new_map: Dict[str, int] = {}
        for item in data:
            symbol = str(item.get("symbol", "")).upper()
            token_id = item.get("id")
            if symbol and token_id is not None:
                new_map[symbol] = int(token_id)

        self._symbol_to_token_id = new_map
        self._token_map_cache["map"] = True  # 标记已加载
        logger.info(f"ValueScan token 映射已刷新: {len(new_map)} 个币种")
        return len(new_map)

    async def _ensure_token_map(self) -> None:
        """确保 token 映射已加载（延迟加载，24h 刷新）。"""
        if "map" not in self._token_map_cache or not self._symbol_to_token_id:
            await self.refresh_token_map()

    async def get_vs_token_id(self, symbol: str) -> Optional[int]:
        """将 BTCUSDT → vsTokenId。"""
        await self._ensure_token_map()
        # 去掉常见后缀
        bare = symbol.upper()
        for suffix in ("USDT", "USD", "BUSD"):
            if bare.endswith(suffix):
                bare = bare[: -len(suffix)]
                break
        return self._symbol_to_token_id.get(bare)

    # ------------------------------------------------------------------
    # AI 信号接口
    # ------------------------------------------------------------------

    async def get_chance_coins(self) -> Optional[List[dict]]:
        """获取 AI 机会币种列表（做多方向）。"""
        cache_key = "chance"
        if cache_key in self._chance_cache:
            logger.debug("ValueScan getChanceCoinList 命中缓存")
            return self._chance_cache[cache_key]

        data = await self._post("/ai/getChanceCoinList", {}, points_cost=3)
        if data is not None:
            # 接口返回的可能是列表或包含列表的 dict
            coins = data if isinstance(data, list) else data.get("list", data.get("coins", []))
            self._chance_cache[cache_key] = coins
            logger.info(f"ValueScan 机会币种获取成功: {len(coins)} 个")
            return coins
        return None

    async def get_risk_coins(self) -> Optional[List[dict]]:
        """获取 AI 风险币种列表（做空方向）。"""
        cache_key = "risk"
        if cache_key in self._risk_cache:
            logger.debug("ValueScan getRiskCoinList 命中缓存")
            return self._risk_cache[cache_key]

        data = await self._post("/ai/getRiskCoinList", {}, points_cost=3)
        if data is not None:
            coins = data if isinstance(data, list) else data.get("list", data.get("coins", []))
            self._risk_cache[cache_key] = coins
            logger.info(f"ValueScan 风险币种获取成功: {len(coins)} 个")
            return coins
        return None

    # ------------------------------------------------------------------
    # 资金流接口
    # ------------------------------------------------------------------

    async def get_coin_trade(self, symbol: str) -> Optional[dict]:
        """获取单币实时资金积累数据。

        Args:
            symbol: 交易对（如 BTCUSDT）或裸符号（如 BTC）
        """
        cache_key = symbol.upper()
        if cache_key in self._coin_trade_cache:
            logger.debug(f"ValueScan getCoinTrade {symbol} 命中缓存")
            return self._coin_trade_cache[cache_key]

        token_id = await self.get_vs_token_id(symbol)
        if token_id is None:
            logger.warning(f"ValueScan 未找到 {symbol} 的 vsTokenId")
            return None

        data = await self._post(
            "/trade/getCoinTrade",
            {"vsTokenId": token_id},
            points_cost=3,
        )
        if data and isinstance(data, dict):
            self._coin_trade_cache[cache_key] = data
            return data
        return None

    # ------------------------------------------------------------------
    # 额度查询
    # ------------------------------------------------------------------

    def get_usage(self) -> Dict[str, Any]:
        """获取当前积分使用情况。"""
        return self.budget_tracker.get_provider_usage(
            PROVIDER_NAME,
            minute_limit=self.minute_point_limit,
            monthly_soft_limit=self.monthly_point_limit,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """关闭 HTTP 会话。"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
