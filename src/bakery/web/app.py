"""FastAPI application factory.

Run: `uvicorn --factory bakery.web.app:create_app` (DATABASE_URL from the environment;
SESSION_SECRET and BAKERY_ENV=production when deployed, see bakery.web.auth).
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from bakery.db import make_engine
from bakery.web import auth
from bakery.web.access import Area
from bakery.web.auth import requires
from bakery.web.routes import demo_upload, login, master_list, uploads

# Every page group, with the area of the access matrix (bakery.web.access) it belongs
# to. None means public: only login/logout, and later the LINE webhook, which
# verifies LINE's signature instead of a login.
ROUTERS: tuple[tuple[APIRouter, Area | None], ...] = (
    (login.router, None),
    (master_list.router, Area.MASTER_LIST),
    (uploads.router, Area.OPERATIONS),
    (demo_upload.router, Area.OPERATIONS),
)


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="喜餅訂單匯流", docs_url=None, redoc_url=None, openapi_url=None)
    auth.install(app)
    app.state.sessionmaker = sessionmaker(engine or make_engine())

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/orders")

    for router, area in ROUTERS:
        app.include_router(router, dependencies=[requires(area)] if area else [])
    return app
