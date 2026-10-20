"""模擬群組上傳 (demo only): pick a demo 傳檔者, upload a file, see the LINE reply."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from bakery.models import Account, Uploader
from bakery.parsing import is_template_file
from bakery.pipeline import process_upload
from bakery.reply import NOT_A_TEMPLATE_NOTICE
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates

router = APIRouter()


def _page(request: Request, session: Session, *, status_code: int = 200, **context) -> HTMLResponse:
    uploaders = session.scalars(
        select(Uploader).where(Uploader.is_demo).order_by(Uploader.line_user_id)
    ).all()
    return templates.TemplateResponse(
        request, "demo_upload.html", {"uploaders": uploaders, **context}, status_code=status_code
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
    # Only the seeded demo 傳檔者: a real LINE account must never appear to have sent this.
    is_demo = session.scalar(select(Uploader.is_demo).where(Uploader.line_user_id == uploader_line_id))
    if not is_demo:
        return _page(
            request, session, status_code=422, error="只能選 demo 傳檔者：這一頁不能用真的 LINE 帳號的名義傳檔。"
        )
    content = file.file.read()
    context = {"selected": uploader_line_id, "filename": file.filename}
    # The same rule as the LINE webhook: a file that is not a 範本 gets no reply there and is not kept.
    if not is_template_file(content):
        return _page(request, session, no_reply=NOT_A_TEMPLATE_NOTICE, **context)
    result = process_upload(
        session,
        uploader_line_id=uploader_line_id,
        filename=file.filename or "upload.xlsx",
        file_bytes=content,
        now=now,
        submitted_by_id=account.id,
    )
    return _page(request, session, result=result, **context)
