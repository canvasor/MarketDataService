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


def test_okx_credentials_prefer_readonly_env_keys(monkeypatch):
    monkeypatch.setenv("OKX_API_KEY_READONLY", "okx-readonly-key")
    monkeypatch.setenv("OKX_API_SECRET_READONLY", "okx-readonly-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE_READONLY", "okx-readonly-passphrase")
    monkeypatch.setenv("OKX_API_KEY", "okx-old-key")
    monkeypatch.setenv("OKX_API_SECRET", "okx-old-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "okx-old-passphrase")

    settings = load_settings()

    assert settings.okx_api_key == "okx-readonly-key"
    assert settings.okx_api_secret == "okx-readonly-secret"
    assert settings.okx_api_passphrase == "okx-readonly-passphrase"


def test_okx_credentials_fall_back_to_legacy_env_keys(monkeypatch):
    monkeypatch.delenv("OKX_API_KEY_READONLY", raising=False)
    monkeypatch.delenv("OKX_API_SECRET_READONLY", raising=False)
    monkeypatch.delenv("OKX_API_PASSPHRASE_READONLY", raising=False)
    monkeypatch.setenv("OKX_API_KEY", "okx-old-key")
    monkeypatch.setenv("OKX_API_SECRET", "okx-old-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "okx-old-passphrase")

    settings = load_settings()

    assert settings.okx_api_key == "okx-old-key"
    assert settings.okx_api_secret == "okx-old-secret"
    assert settings.okx_api_passphrase == "okx-old-passphrase"
