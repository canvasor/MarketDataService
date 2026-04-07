#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logging helpers for the local data service."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def build_logging_handlers(
    log_dir: str | Path,
    log_filename: str,
    max_bytes: int,
    backup_count: int,
) -> List[logging.Handler]:
    """Build stdout + rotating file handlers."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / log_filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    handlers: List[logging.Handler] = [file_handler]
    if sys.stderr.isatty():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        handlers.insert(0, stream_handler)

    return handlers


def configure_logging(
    log_dir: str | Path,
    log_filename: str,
    max_bytes: int,
    backup_count: int,
    level: int = logging.INFO,
) -> None:
    """Configure root logging for both console and rotating file output."""
    logging.basicConfig(
        level=level,
        handlers=build_logging_handlers(
            log_dir=log_dir,
            log_filename=log_filename,
            max_bytes=max_bytes,
            backup_count=backup_count,
        ),
        force=True,
    )
