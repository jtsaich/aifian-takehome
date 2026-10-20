"""Structured result of processing one 上傳: what reply text is rendered from."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadOutcome:
    store_code: str
    store_name: str
    order_count: int  # 喜餅訂單 received in this file
    line_count: int  # 訂單明細 received in this file


@dataclass(frozen=True)
class ProcessResult:
    upload_id: int
    reply_text: str  # exactly what the LINE reply says
    outcome: UploadOutcome
