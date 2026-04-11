#!/usr/bin/env python3
"""通用工具函数。"""


def normalize_symbol(symbol: str) -> str:
    """标准化交易对名称：大写 + 确保以 USDT 结尾"""
    symbol = symbol.upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    return symbol
