import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, dashboard, events, families, notifications, shopping, tasks, ws
from app.core.config import get_settings
from app.core.exceptions import error_body
from app.realtime.hub import hub
from app.workers.reminders import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    if settings.environment != "test":
        start_scheduler()
    yield
    stop_scheduler()
    hub.bind_loop(None)


app = FastAPI(
    title="FamilyOS Family API",
    version="0.1.0",
    description="Client-agnostic household coordination API for FamilyOS v0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    body = error_body(exc)
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "code": "validation_error"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(families.router)
app.include_router(dashboard.router)
app.include_router(events.router)
app.include_router(tasks.router)
app.include_router(shopping.router)
app.include_router(notifications.router)
app.include_router(ws.router)
