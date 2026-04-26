"""
Official Instagram Graph API client.

This client covers the supported professional-account flow:
  - list recent media for the dashboard
  - send a private reply to a comment
  - verify webhook challenge requests
  - validate webhook signatures when an app secret is configured
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any
from urllib import parse, request

from app.config import settings


class InstagramAPIService:
    @property
    def configured(self) -> bool:
        return bool(
            settings.instagram_page_id
            and settings.instagram_page_access_token
            and settings.instagram_webhook_verify_token
        )

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{settings.instagram_graph_api_version}"

    def verify_webhook(
        self,
        mode: str | None,
        token: str | None,
        challenge: str | None,
    ) -> str | None:
        if mode == "subscribe" and token and token == settings.instagram_webhook_verify_token:
            return challenge
        return None

    def verify_signature(self, body: bytes, signature_header: str | None) -> bool:
        if not settings.instagram_app_secret:
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False

        expected = hmac.new(
            settings.instagram_app_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        received = signature_header.removeprefix("sha256=")
        return hmac.compare_digest(expected, received)

    async def list_recent_media(self, limit: int = 20) -> list[dict[str, Any]]:
        if not settings.instagram_ig_user_id or not settings.instagram_page_access_token:
            return []

        url = f"{self.graph_base_url}/{settings.instagram_ig_user_id}/media"
        params = {
            "fields": "id,caption,media_type,media_product_type,permalink,timestamp",
            "limit": limit,
            "access_token": settings.instagram_page_access_token,
        }

        def _fetch() -> dict[str, Any]:
            query = parse.urlencode(params)
            with request.urlopen(f"{url}?{query}", timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))

        data = await asyncio.to_thread(_fetch)

        posts: list[dict[str, Any]] = []
        for item in data.get("data", []):
            posts.append(
                {
                    "media_id": item.get("id", ""),
                    "shortcode": item.get("id", ""),
                    "caption": item.get("caption", ""),
                    "timestamp": item.get("timestamp", ""),
                    "media_type": item.get("media_type", ""),
                    "media_product_type": item.get("media_product_type", ""),
                    "permalink": item.get("permalink", ""),
                }
            )
        return posts

    async def send_private_reply(self, comment_id: str, message: str) -> dict[str, Any]:
        if not settings.instagram_page_id or not settings.instagram_page_access_token:
            raise RuntimeError("Instagram API is not configured for private replies.")

        url = f"{self.graph_base_url}/{settings.instagram_page_id}/messages"
        payload = {
            "recipient": json.dumps({"comment_id": comment_id}),
            "message": json.dumps({"text": message}),
            "access_token": settings.instagram_page_access_token,
        }

        def _send() -> dict[str, Any]:
            encoded = parse.urlencode(payload).encode("utf-8")
            req = request.Request(url, data=encoded, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

            with request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))

        return await asyncio.to_thread(_send)


instagram_api_service = InstagramAPIService()