#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 缓存模块

内存缓存，用于存储 API 响应数据：
- /api/ai500/list
- /api/oi/top
- /api/coin/{symbol}

支持定时预热和 TTL 过期。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    data: Any
    created_at: float = field(default_factory=time.time)
    ttl: float = 1800  # 默认 30 分钟

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.created_at > self.ttl

    def age_seconds(self) -> float:
        """返回缓存年龄（秒）"""
        return time.time() - self.created_at


class APICache:
    """
    API 缓存管理器

    特点:
    1. 内存缓存，支持 TTL 过期
    2. 优先从缓存读取，缓存未命中时调用原始接口
    3. 支持定时预热
    4. 线程安全
    """

    # 缓存键常量
    KEY_AI500_LIST = "ai500_list"
    KEY_AI500_SHORT = "ai500_short"
    KEY_AI500_LONG = "ai500_long"
    KEY_OI_TOP = "oi_top"
    KEY_SYSTEM_STATUS = "system_status"
    KEY_COIN_PREFIX = "coin_"

    def __init__(self, default_ttl: float = 1800):
        """
        初始化缓存管理器

        Args:
            default_ttl: 默认 TTL（秒），默认 30 分钟
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._default_ttl = default_ttl

        # 预热配置
        self._warmup_enabled = False
        self._warmup_interval = 900  # 15 分钟
        self._warmup_task: Optional[asyncio.Task] = None

        # 统计信息
        self._stats = {
            "hits": 0,
            "misses": 0,
            "warmups": 0,
            "last_warmup": 0,
        }

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据

        Args:
            key: 缓存键

        Returns:
            缓存数据，不存在或已过期返回 None
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            return entry.data

    def set(self, key: str, data: Any, ttl: Optional[float] = None) -> None:
        """
        设置缓存数据

        Args:
            key: 缓存键
            data: 缓存数据
            ttl: 可选的 TTL（秒）
        """
        with self._lock:
            self._cache[key] = CacheEntry(
                data=data,
                ttl=ttl if ttl is not None else self._default_ttl
            )

    def delete(self, key: str) -> bool:
        """删除缓存"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()

    def record_warmup(self, timestamp: Optional[float] = None) -> None:
        """记录一次缓存预热。"""
        with self._lock:
            self._stats["warmups"] += 1
            self._stats["last_warmup"] = timestamp if timestamp is not None else time.time()

    def get_coin_key(self, symbol: str) -> str:
        """获取币种缓存键"""
        return f"{self.KEY_COIN_PREFIX}{symbol.upper()}"

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0

            # 统计各类缓存条目
            ai500_count = sum(1 for k in self._cache if k.startswith("ai500"))
            oi_count = 1 if self.KEY_OI_TOP in self._cache else 0
            coin_count = sum(1 for k in self._cache if k.startswith(self.KEY_COIN_PREFIX))

            return {
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": f"{hit_rate:.1f}%",
                "warmups": self._stats["warmups"],
                "last_warmup": self._stats["last_warmup"],
                "entries": {
                    "total": len(self._cache),
                    "ai500": ai500_count,
                    "oi_top": oi_count,
                    "coins": coin_count
                }
            }

    def list_entries(self) -> Dict[str, Dict]:
        """列出所有缓存条目信息"""
        with self._lock:
            entries = {}
            for key, entry in self._cache.items():
                entries[key] = {
                    "age_seconds": round(entry.age_seconds(), 1),
                    "ttl": entry.ttl,
                    "expired": entry.is_expired()
                }
            return entries


# 全局缓存实例
_cache_instance: Optional[APICache] = None


def get_cache() -> APICache:
    """获取全局缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = APICache()
    return _cache_instance


def init_cache(default_ttl: float = 1800) -> APICache:
    """初始化全局缓存实例"""
    global _cache_instance
    _cache_instance = APICache(default_ttl=default_ttl)
    return _cache_instance
