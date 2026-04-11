#!/usr/bin/env python3
"""统一异常处理。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ServiceError(Exception):
    """业务异常基类"""
    def __init__(self, code: int, msg: str, data=None):
        self.code = code
        self.msg = msg
        self.data = data


class CollectorNotReady(ServiceError):
    def __init__(self):
        super().__init__(503, "采集器未就绪")


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.code,
            content={"code": exc.code, "msg": exc.msg, "data": exc.data}
        )
