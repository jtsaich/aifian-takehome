"""The LINE Messaging API, as far as this app uses it: signature check, file download,
reply, and a sender's display name. Plain httpx; the official SDK would add little.

Configuration (both from the LINE Developers Console, Messaging API channel):
LINE_CHANNEL_SECRET signs webhook requests; LINE_CHANNEL_ACCESS_TOKEN (long-lived)
authorizes API calls. Without both, the webhook answers 503.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.line.me"
DATA_API = "https://api-data.line.me"  # message content lives on its own host
# The reply token is good for one minute; leave room for processing.
TIMEOUT = httpx.Timeout(15.0)


def sign(channel_secret: str, body: bytes) -> str:
    """X-Line-Signature: base64(HMAC-SHA256(channel secret, raw request body))."""
    return base64.b64encode(hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()).decode()


def verify_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(channel_secret, body).encode(), signature.encode())


class LineApi:
    def __init__(self, access_token: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT, transport=transport
        )

    def get_content(self, message_id: str) -> bytes:
        """The file a message carries. LINE keeps it only for a while: fetch it right away."""
        resp = self._client.get(f"{DATA_API}/v2/bot/message/{message_id}/content")
        resp.raise_for_status()
        return resp.content

    def reply_text(self, reply_token: str, text: str) -> None:
        """Reply (free; push would count against the monthly quota). One use per token."""
        resp = self._client.post(
            f"{API}/v2/bot/message/reply",
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
        )
        resp.raise_for_status()

    def display_name(self, source: Mapping[str, Any]) -> str | None:
        """The sender's LINE display name, for 總部 to recognise them; None if unavailable."""
        user_id = source.get("userId")
        match source.get("type"):
            case "group":
                url = f"{API}/v2/bot/group/{source.get('groupId')}/member/{user_id}"
            case "room":
                url = f"{API}/v2/bot/room/{source.get('roomId')}/member/{user_id}"
            case _:
                url = f"{API}/v2/bot/profile/{user_id}"
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.json().get("displayName") or None
        except (httpx.HTTPError, ValueError):
            return None


@dataclass(frozen=True)
class LineChannel:
    secret: str
    api: LineApi

    @classmethod
    def from_env(cls) -> LineChannel | None:
        secret = os.environ.get("LINE_CHANNEL_SECRET")
        token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        if not (secret and token):
            return None
        return cls(secret, LineApi(token))
