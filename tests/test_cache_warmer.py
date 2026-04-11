#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.cache_warmer import get_warmup_schedule


def test_warmup_schedule_uses_every_five_minutes_at_30_seconds():
    schedule = get_warmup_schedule()

    assert schedule["minutes"] == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    assert schedule["second_offset"] == 30
