#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

from provider_budget import ProviderBudgetTracker


def test_budget_tracker_attempt_and_success(tmp_path: Path):
    tracker = ProviderBudgetTracker(storage_path=str(tmp_path / "usage.json"))
    gate = tracker.can_attempt("coingecko", minute_limit=2, monthly_soft_limit=3)
    assert gate["allowed"] is True

    tracker.record_attempt("coingecko")
    tracker.record_result("coingecko", True)
    usage = tracker.get_provider_usage("coingecko", minute_limit=2, monthly_soft_limit=3)
    assert usage["monthly_success"] == 1
    assert usage["monthly_attempts"] == 1
    assert usage["minute_used"] == 1


def test_budget_tracker_soft_block(tmp_path: Path):
    tracker = ProviderBudgetTracker(storage_path=str(tmp_path / "usage.json"))
    tracker.set_soft_block("cmc", True, reason="manual block")
    gate = tracker.can_attempt("cmc", minute_limit=5, monthly_soft_limit=10)
    assert gate["allowed"] is False
    usage = tracker.get_provider_usage("cmc", minute_limit=5, monthly_soft_limit=10)
    assert usage["soft_blocked"] is True
    assert usage["last_error"] == "manual block"
