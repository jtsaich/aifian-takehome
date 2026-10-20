"""模擬群組上傳 (demo only): pick a demo 傳檔者, upload a file, see the LINE reply."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.models import Account, Uploader
from bakery.pipeline import process_upload
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates

router = APIRouter()


def _page(request: Request, session: Session, **context) -> HTMLResponse:
    uploaders = session.scalars(
        select(Uploader).where(Uploader.is_demo).order_by(Uploader.line_user_id)
    ).all()
    return templates.TemplateResponse(
        request, "demo_upload.html", {"uploaders": uploaders, **context}
    )


@router.get("/demo/upload", response_class=HTMLResponse)
def show(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    return _page(request, session)


@router.post("/demo/upload", response_class=HTMLResponse)
def upload(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    account: Annotated[Account, Depends(current_account)],
    uploader_line_id: Annotated[str, Form()],
    file: UploadFile,
) -> HTMLResponse:
    result = process_upload(
        session,
        uploader_line_id=uploader_line_id,
        filename=file.filename or "upload.xlsx",
        file_bytes=file.file.read(),
        now=now,
        submitted_by_id=account.id,
    )
    return _page(
        request,
        session,
        result=result,
        selected=uploader_line_id,
        filename=file.filename,
    )
