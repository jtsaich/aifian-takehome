"""歷史資料匯入 (總部人員 only): import 範本 files the FDE converted from a 門市's
pre-go-live Excel (`convert-legacy`). Same pipeline as any upload, as 歷史資料."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from bakery.models import Account
from bakery.pipeline import process_upload
from bakery.web.auth import current_account
from bakery.web.deps import get_now, get_session, templates

router = APIRouter()


@router.get("/history/import", response_class=HTMLResponse)
def show(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "history_import.html", {"results": []})


@router.post("/history/import", response_class=HTMLResponse)
def import_files(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    account: Annotated[Account, Depends(current_account)],
    files: list[UploadFile],
) -> HTMLResponse:
    results = [
        (
            file.filename,
            process_upload(
                session,
                uploader_line_id=None,
                filename=file.filename or "historical.xlsx",
                file_bytes=file.file.read(),
                now=now,
                submitted_by_id=account.id,
                historical=True,
            ),
        )
        for file in files
    ]
    return templates.TemplateResponse(request, "history_import.html", {"results": results})
