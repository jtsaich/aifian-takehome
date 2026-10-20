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
from bakery.line import LineChannel
from bakery.web import auth
from bakery.web.access import Area
from bakery.web.auth import requires
from bakery.web.routes import (
    bindings,
    customers,
    demo_upload,
    line_webhook,
    login,
    master_list,
    orders,
    uploads,
)

# Every page group, with the area of the access matrix (bakery.web.access) it belongs
# to. None means public: only login/logout and the LINE webhook, which verifies
# LINE's signature instead of a login.
ROUTERS: tuple[tuple[APIRouter, Area | None], ...] = (
    (login.router, None),
    (line_webhook.router, None),
    (master_list.router, Area.MASTER_LIST),
    (orders.router, Area.OPERATIONS),
    (uploads.router, Area.OPERATIONS),
    (demo_upload.router, Area.OPERATIONS),
    (bindings.router, Area.OPERATIONS),
    (bindings.confirm_router, Area.CONFIRMATIONS),
    (customers.router, Area.CUSTOMERS),
)


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="喜餅訂單匯流", docs_url=None, redoc_url=None, openapi_url=None)
    auth.install(app)
    app.state.sessionmaker = sessionmaker(engine or make_engine())
    # LINE_CHANNEL_SECRET + LINE_CHANNEL_ACCESS_TOKEN; None until the channel exists.
    app.state.line = LineChannel.from_env()

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/orders")

    for router, area in ROUTERS:
        app.include_router(router, dependencies=[requires(area)] if area else [])
    return app
