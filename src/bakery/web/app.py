"""FastAPI application factory.

Run: `uvicorn --factory bakery.web.app:create_app` (DATABASE_URL from the environment).
Every page group is an APIRouter registered here, in one place, so access control
can be attached per router at registration.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from bakery.db import make_engine
from bakery.web.routes import demo_upload, master_list, uploads


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="喜餅訂單匯流", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessionmaker = sessionmaker(engine or make_engine())

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/orders")

    app.include_router(demo_upload.router)
    app.include_router(master_list.router)
    app.include_router(uploads.router)
    return app
