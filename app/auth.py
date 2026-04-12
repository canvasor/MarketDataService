#!/usr/bin/env python3
"""认证模块。"""

import os
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Query

from core.config import AUTH_ENV_KEYS, is_loopback_host, settings


AUTH_HEADER_NAME = "X-API-Key"


def _legacy_query_auth_allowed() -> bool:
    return settings.allow_legacy_public_key and is_loopback_host(settings.host)


def get_auth_source() -> str:
    for env_key in AUTH_ENV_KEYS:
        if os.getenv(env_key):
            return env_key
    return "default"


def build_auth_metadata(required: bool) -> Dict[str, Any]:
    return {
        "required": required,
        "header": AUTH_HEADER_NAME,
        "query_param": "auth" if _legacy_query_auth_allowed() else None,
        "legacy_query_supported": _legacy_query_auth_allowed(),
        "env_keys": list(AUTH_ENV_KEYS),
        "source": get_auth_source(),
    }


def verify_auth(auth: str) -> bool:
    """验证认证密钥"""
    return auth == settings.auth_key


def require_auth(
    x_api_key: Optional[str] = Header(None, alias=AUTH_HEADER_NAME, description="认证密钥"),
    auth: Optional[str] = Query(None, description="认证密钥"),
) -> str:
    """FastAPI 依赖：优先使用请求头认证，本地回环地址兼容 query auth。"""
    candidate = x_api_key
    if candidate is None and _legacy_query_auth_allowed():
        candidate = auth

    if candidate != settings.auth_key:
        raise HTTPException(status_code=401, detail="认证失败")
    return candidate
