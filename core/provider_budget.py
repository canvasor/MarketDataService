#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量级 API 使用量跟踪与预算守门。

目标：
1. 在本地记录 CoinGecko / CMC 的分钟级请求和月度成功调用。
2. 支持持久化，避免服务重启后预算统计丢失。
3. 为 auto provider 模式提供预算感知的回退选择。

说明：
- CoinGecko 官方说明：所有请求都会计入 minute rate，只有成功请求会扣月度 credits。
- CMC 免费额度是 call credits/mo；本地先采用“成功请求 + 保守 minute gate”策略。
- 本地计数并不等于官方后台的精确值，但足够用于个人服务的节流与预算保护。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional


class ProviderBudgetTracker:
    def __init__(self, storage_path: str = "data/provider_usage.json"):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "providers": {},
            "updated_at": int(time.time()),
        }
        self._minute_windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._load()

    # ---------- persistence ----------
    def _load(self) -> None:
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._state.update(data)
        except Exception:
            # budget 统计失败不应阻断主服务
            pass

    def _save(self) -> None:
        if not self.storage_path:
            return
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            self._state["updated_at"] = int(time.time())
            with open(self.storage_path, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- helpers ----------
    @staticmethod
    def _month_key(ts: Optional[float] = None) -> str:
        tm = time.gmtime(ts or time.time())
        return f"{tm.tm_year:04d}-{tm.tm_mon:02d}"

    def _provider_state(self, provider: str) -> Dict[str, Any]:
        providers = self._state.setdefault("providers", {})
        pstate = providers.setdefault(provider, {
            "month": self._month_key(),
            "monthly_success": 0,
            "monthly_attempts": 0,
            "last_request_at": 0,
            "last_success_at": 0,
            "last_error_at": 0,
            "last_error": None,
            "soft_blocked": False,
        })
        current_month = self._month_key()
        if pstate.get("month") != current_month:
            pstate.update({
                "month": current_month,
                "monthly_success": 0,
                "monthly_attempts": 0,
                "soft_blocked": False,
            })
        return pstate

    def _trim_minute_window(self, provider: str, now: Optional[float] = None) -> Deque[float]:
        now = now or time.time()
        window = self._minute_windows[provider]
        while window and (now - window[0]) > 60:
            window.popleft()
        return window

    # ---------- public api ----------
    def can_attempt(self, provider: str, minute_limit: int, monthly_soft_limit: int) -> Dict[str, Any]:
        with self._lock:
            pstate = self._provider_state(provider)
            now = time.time()
            minute_window = self._trim_minute_window(provider, now)
            minute_used = len(minute_window)
            monthly_used = int(pstate.get("monthly_success", 0))
            allowed = minute_used < minute_limit and monthly_used < monthly_soft_limit and not pstate.get("soft_blocked", False)
            return {
                "allowed": allowed,
                "provider": provider,
                "minute_used": minute_used,
                "minute_limit": minute_limit,
                "monthly_used": monthly_used,
                "monthly_soft_limit": monthly_soft_limit,
                "soft_blocked": bool(pstate.get("soft_blocked", False)),
            }

    def record_attempt(self, provider: str, count: int = 1) -> None:
        with self._lock:
            pstate = self._provider_state(provider)
            now = time.time()
            self._trim_minute_window(provider, now).append(now)
            pstate["monthly_attempts"] = int(pstate.get("monthly_attempts", 0)) + count
            pstate["last_request_at"] = int(now)
            self._save()

    def record_result(self, provider: str, success: bool, error: Optional[str] = None, count: int = 1) -> None:
        with self._lock:
            pstate = self._provider_state(provider)
            now = int(time.time())
            if success:
                pstate["monthly_success"] = int(pstate.get("monthly_success", 0)) + count
                pstate["last_success_at"] = now
                pstate["last_error"] = None
            else:
                pstate["last_error_at"] = now
                if error:
                    pstate["last_error"] = error[:500]
            self._save()

    def set_soft_block(self, provider: str, blocked: bool, reason: Optional[str] = None) -> None:
        with self._lock:
            pstate = self._provider_state(provider)
            pstate["soft_blocked"] = blocked
            if reason:
                pstate["last_error"] = reason[:500]
                pstate["last_error_at"] = int(time.time())
            self._save()

    def get_provider_usage(self, provider: str, minute_limit: int, monthly_soft_limit: int) -> Dict[str, Any]:
        with self._lock:
            pstate = self._provider_state(provider)
            minute_window = self._trim_minute_window(provider)
            return {
                "provider": provider,
                "month": pstate.get("month"),
                "monthly_success": int(pstate.get("monthly_success", 0)),
                "monthly_attempts": int(pstate.get("monthly_attempts", 0)),
                "monthly_soft_limit": monthly_soft_limit,
                "monthly_remaining_estimate": max(0, monthly_soft_limit - int(pstate.get("monthly_success", 0))),
                "minute_used": len(minute_window),
                "minute_limit": minute_limit,
                "last_request_at": int(pstate.get("last_request_at", 0)),
                "last_success_at": int(pstate.get("last_success_at", 0)),
                "last_error_at": int(pstate.get("last_error_at", 0)),
                "last_error": pstate.get("last_error"),
                "soft_blocked": bool(pstate.get("soft_blocked", False)),
            }

    def get_all_usage(self, provider_limits: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        with self._lock:
            result = {}
            for provider, limits in provider_limits.items():
                result[provider] = self.get_provider_usage(
                    provider,
                    minute_limit=int(limits.get("minute_limit", 0)),
                    monthly_soft_limit=int(limits.get("monthly_soft_limit", 0)),
                )
            return {
                "providers": result,
                "updated_at": int(time.time()),
            }
