#!/usr/bin/env python3
"""NOFX 本地数据服务器入口"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    from core.config import settings
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
