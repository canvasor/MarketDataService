#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio

import pytest

from core.cache_warmer import get_warmup_schedule
from core.cache_warmer import CacheWarmer


def test_warmup_schedule_uses_every_five_minutes_at_30_seconds():
    schedule = get_warmup_schedule()

    assert schedule["minutes"] == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    assert schedule["second_offset"] == 30


@pytest.mark.asyncio
async def test_cache_warmer_start_does_not_block_on_initial_warmup(monkeypatch):
    warmer = CacheWarmer(collector=object(), analyzer=object())
    started = asyncio.Event()
    finished = asyncio.Event()

    async def fake_scheduler_loop():
        await asyncio.Event().wait()

    async def fake_warmup():
        started.set()
        await asyncio.sleep(0.05)
        finished.set()
        return {"success": True}

    monkeypatch.setattr(warmer, "_scheduler_loop", fake_scheduler_loop)
    monkeypatch.setattr(warmer, "warmup", fake_warmup)

    await warmer.start()
    await asyncio.sleep(0)

    assert warmer._running is True
    assert started.is_set()
    assert not finished.is_set()

    await warmer.stop()
