from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import engine
from app.dependencies import SessionDep
from app.routes import auth, catalog, company, orders, payments


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await engine.dispose()

    application = FastAPI(
        title=settings.app_name,
        description=(
            "A FastAPI backend for Infinity's clients, employees, branches, departments, "
            "hardware and software catalog, inventory, orders, and payments."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def add_response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.get("/", tags=["System"])
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "docs": "/docs", "health": "/health/ready"}

    @application.get("/health/live", tags=["System"])
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/health/ready", tags=["System"])
    async def readiness(session: SessionDep) -> dict[str, str]:
        try:
            await session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Database is unavailable") from None
        return {"status": "ready", "database": "connected"}

    application.include_router(auth.router, prefix=settings.api_v1_prefix)
    application.include_router(company.router)
    application.include_router(catalog.router)
    application.include_router(orders.router)
    application.include_router(payments.router)
    return application


app = create_app()
