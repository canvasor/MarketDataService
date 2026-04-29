#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.cache import APICache


def test_record_warmup_updates_cache_stats():
    cache = APICache()

    cache.record_warmup(123.0)

    stats = cache.get_stats()
    assert stats["warmups"] == 1
    assert stats["last_warmup"] == 123.0


def test_get_with_state_returns_stale_without_deleting():
    cache = APICache(default_ttl=0)
    cache.set("price_1h", {"rows": []}, ttl=0)

    data, state = cache.get_with_state("price_1h")

    assert data == {"rows": []}
    assert state == "stale"

    data, state = cache.get_with_state("price_1h")
    assert data == {"rows": []}
    assert state == "stale"
