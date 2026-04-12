#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

from collectors.valuescan_collector import ValueScanCollector
from core.provider_budget import ProviderBudgetTracker


def test_valuescan_can_afford_respects_requested_points(tmp_path: Path):
    tracker = ProviderBudgetTracker(storage_path=str(tmp_path / "usage.json"))
    collector = ValueScanCollector(
        base_url="https://example.com/api",
        api_key="key",
        secret_key="secret",
        budget_tracker=tracker,
        monthly_point_limit=10,
        minute_point_limit=5,
    )

    assert collector.can_afford(6) is False
    assert collector.can_afford(5) is True


def test_valuescan_can_afford_accounts_for_existing_usage(tmp_path: Path):
    tracker = ProviderBudgetTracker(storage_path=str(tmp_path / "usage.json"))
    tracker.record_attempt("valuescan", count=3)

    collector = ValueScanCollector(
        base_url="https://example.com/api",
        api_key="key",
        secret_key="secret",
        budget_tracker=tracker,
        monthly_point_limit=10,
        minute_point_limit=5,
    )

    assert collector.can_afford(3) is False
    assert collector.can_afford(2) is True
