"""The one place that turns an UploadOutcome into the 繁中 reply the 傳檔者 reads.

The same text goes to the LINE group and to the 模擬群組上傳 page.
"""

from __future__ import annotations

from bakery.outcome import UploadOutcome


def render_reply(outcome: UploadOutcome) -> str:
    return (
        f"{outcome.store_name}（{outcome.store_code}）："
        f"收到 {outcome.order_count} 張喜餅訂單、{outcome.line_count} 筆訂單明細。"
    )
