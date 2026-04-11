#!/usr/bin/env python3
"""认证模块。"""

import os
from typing import Any, Dict

from fastapi import Query, HTTPException

from core.config import settings, AUTH_ENV_KEYS


def get_auth_source() -> str:
    for env_key in AUTH_ENV_KEYS:
        if os.getenv(env_key):
            return env_key
    return "default"


def build_auth_metadata(required: bool) -> Dict[str, Any]:
    return {
        "required": required,
        "query_param": "auth",
        "env_keys": list(AUTH_ENV_KEYS),
        "source": get_auth_source(),
    }


def verify_auth(auth: str) -> bool:
    """验证认证密钥"""
    return auth == settings.auth_key


def require_auth(auth: str = Query(..., description="认证密钥")) -> str:
    """FastAPI 依赖：验证认证密钥，失败抛 401"""
    if auth != settings.auth_key:
        raise HTTPException(status_code=401, detail="认证失败")
    return auth
