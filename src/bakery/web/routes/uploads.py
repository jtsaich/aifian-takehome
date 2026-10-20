"""上傳紀錄: every upload with its reply, and the original file for download."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, undefer

from bakery.models import Upload
from bakery.web.deps import get_session, templates

router = APIRouter()

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/uploads", response_class=HTMLResponse)
def history(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    uploads = session.scalars(
        select(Upload)
        .options(joinedload(Upload.uploader), joinedload(Upload.store))
        .order_by(Upload.received_at.desc(), Upload.id.desc())
    ).all()
    return templates.TemplateResponse(request, "uploads.html", {"uploads": uploads})


@router.get("/uploads/{upload_id}/original")
def original(upload_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    upload = session.get(Upload, upload_id, options=[undefer(Upload.content)])
    if upload is None:
        raise HTTPException(status_code=404)
    disposition = (
        f'attachment; filename="upload-{upload.id}.xlsx"; '
        f"filename*=UTF-8''{quote(upload.filename)}"
    )
    return Response(
        upload.content, media_type=XLSX_MEDIA_TYPE, headers={"Content-Disposition": disposition}
    )
