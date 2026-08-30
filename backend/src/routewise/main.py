from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routewise.api import api_router, health_router
from routewise.cache import RouteCache
from routewise.config import Settings, get_settings
from routewise.db import create_engine, create_session_factory
from routewise.models import Base
from routewise.seed import METROVALE_NETWORK, SCENARIOS
from routewise.service import RouteService, ServiceError


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()
    engine = create_engine(configured)
    session_factory = create_session_factory(engine)
    route_service = RouteService(
        network=METROVALE_NETWORK,
        scenarios=SCENARIOS,
        cache=RouteCache(configured.route_cache_entries),
        max_route_runs=configured.max_route_runs,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if configured.auto_create_schema:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        yield
        await engine.dispose()

    application = FastAPI(
        title="RouteWise API",
        version="0.1.0",
        description=(
            "Deterministic disruption-aware routing over the fictional Metrovale network."
        ),
        lifespan=lifespan,
    )
    application.state.settings = configured
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.route_service = route_service
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    application.include_router(health_router)
    application.include_router(api_router)

    @application.exception_handler(ServiceError)
    async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return application


app = create_app()


def run() -> None:
    uvicorn.run("routewise.main:app", host="0.0.0.0", port=8000, proxy_headers=True)


if __name__ == "__main__":
    run()
