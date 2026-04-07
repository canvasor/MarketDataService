from logging.handlers import RotatingFileHandler
from pathlib import Path

from logging_utils import build_logging_handlers


def test_build_logging_handlers_uses_rotating_file_handler(tmp_path):
    log_dir = tmp_path / "logs"
    handlers = build_logging_handlers(
        log_dir=log_dir,
        log_filename="market_data_service.log",
        max_bytes=4096,
        backup_count=4,
    )

    try:
        file_handlers = [handler for handler in handlers if isinstance(handler, RotatingFileHandler)]
        assert len(file_handlers) == 1

        file_handler = file_handlers[0]
        assert Path(file_handler.baseFilename) == log_dir / "market_data_service.log"
        assert file_handler.maxBytes == 4096
        assert file_handler.backupCount == 4
        assert log_dir.exists()
    finally:
        for handler in handlers:
            handler.close()
