"""上傳紀錄: every upload with its reply, and the original file for download."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, undefer

from bakery.models import Upload
from bakery.web.deps import get_session, templates, xlsx_download

router = APIRouter()


@router.get("/uploads", response_class=HTMLResponse)
def history(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    uploads = session.scalars(
        select(Upload)
        .options(
            joinedload(Upload.uploader), joinedload(Upload.submitted_by), joinedload(Upload.store)
        )
        .order_by(Upload.received_at.desc(), Upload.id.desc())
    ).all()
    return templates.TemplateResponse(request, "uploads.html", {"uploads": uploads})


@router.get("/uploads/{upload_id}", response_class=HTMLResponse)
def detail(
    upload_id: int, request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    """One upload with its full reply: where a LINE reply cut at 5,000 characters links to."""
    upload = session.get(
        Upload, upload_id, options=[joinedload(Upload.uploader), joinedload(Upload.store)]
    )
    if upload is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "upload_detail.html", {"upload": upload})


@router.get("/uploads/{upload_id}/original")
def original(upload_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    upload = session.get(Upload, upload_id, options=[undefer(Upload.content)])
    if upload is None:
        raise HTTPException(status_code=404)
    return xlsx_download(upload.content, upload.filename, f"upload-{upload.id}.xlsx")
