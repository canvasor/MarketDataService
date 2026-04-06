#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from config import load_settings


def test_auth_key_prefers_nofxos_api_key(monkeypatch):
    monkeypatch.setenv("NOFXOS_API_KEY", "from-nofxos")
    monkeypatch.setenv("NOFX_LOCAL_AUTH_KEY", "from-local")

    settings = load_settings()

    assert settings.auth_key == "from-nofxos"


def test_auth_key_falls_back_to_nofx_local_auth_key(monkeypatch):
    monkeypatch.delenv("NOFXOS_API_KEY", raising=False)
    monkeypatch.setenv("NOFX_LOCAL_AUTH_KEY", "from-local")

    settings = load_settings()

    assert settings.auth_key == "from-local"
