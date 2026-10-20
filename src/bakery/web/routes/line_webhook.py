"""LINE webhook: public, authenticated by LINE's signature instead of a login."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from bakery.line import LineChannel, verify_signature
from bakery.line_webhook import handle_events
from bakery.web.deps import get_now, get_session

router = APIRouter()

WEBHOOK_PATH = "/line/webhook"


def get_line(request: Request) -> LineChannel | None:
    """The configured channel (bakery.line.LineChannel.from_env); tests override this."""
    return request.app.state.line


async def _raw_body(request: Request) -> bytes:
    return await request.body()


@router.post(WEBHOOK_PATH)
def webhook(
    body: Annotated[bytes, Depends(_raw_body)],
    line: Annotated[LineChannel | None, Depends(get_line)],
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    x_line_signature: Annotated[str | None, Header()] = None,
) -> Response:
    # A sync handler (threadpool): everything, reply included, finishes before the
    # response, because Cloud Run throttles the CPU once it is sent.
    if line is None:
        return Response("LINE channel not configured", status_code=503)
    if not verify_signature(line.secret, body, x_line_signature):
        return Response("bad signature", status_code=400)
    try:
        events = json.loads(body)["events"]
    except (ValueError, KeyError, TypeError):
        events = None
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        return Response("bad payload", status_code=400)
    # 500 makes LINE redeliver (when redelivery is on): only for a file not yet downloaded.
    return Response(status_code=200 if handle_events(session, line.api, events, now) else 500)
