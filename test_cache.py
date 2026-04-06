#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from cache import APICache


def test_record_warmup_updates_cache_stats():
    cache = APICache()

    cache.record_warmup(123.0)

    stats = cache.get_stats()
    assert stats["warmups"] == 1
    assert stats["last_warmup"] == 123.0
