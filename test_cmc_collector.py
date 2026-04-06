#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from cmc_collector import CMCCollector


def test_coingecko_endpoint_adds_v3_when_base_is_api():
    collector = CMCCollector(
        coingecko_api_endpoint="https://api.coingecko.com/api",
        coingecko_api_key="demo-key",
    )

    assert collector.coingecko_api_endpoint == "https://api.coingecko.com/api/v3"
