"""
PayPal REST API service for Sweet Vine Products.
Uses direct HTTPS calls (no deprecated SDK) — same endpoints PayPal Smart Buttons hit.

Env vars expected:
  PAYPAL_MODE                = "sandbox" | "live"
  PAYPAL_CLIENT_ID_SANDBOX   / PAYPAL_CLIENT_SECRET_SANDBOX
  PAYPAL_CLIENT_ID_LIVE      / PAYPAL_CLIENT_SECRET_LIVE
"""
from __future__ import annotations
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger("sweetvine.paypal")


class PayPalAPIError(Exception):
    """A PayPal REST API call returned a non-2xx response.
    Carries the HTTP status + parsed error body so callers can surface
    a friendly message to the user."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body or {}
        # Try to dig out the most useful message PayPal returned
        details = self.body.get("details") or []
        first = details[0] if details else {}
        self.issue = first.get("issue") or self.body.get("name") or ""
        self.description = (
            first.get("description")
            or self.body.get("message")
            or self.body.get("error_description")
            or "PayPal request failed."
        )
        super().__init__(f"PayPal {status_code} {self.issue}: {self.description}")


async def _request(client: httpx.AsyncClient, method: str, url: str, **kw) -> dict:
    """Wrapper that translates any non-2xx response into PayPalAPIError."""
    r = await client.request(method, url, timeout=kw.pop("timeout", 20.0), **kw)
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = {"message": r.text}
        logger.warning("paypal %s %s -> %s %s", method, url, r.status_code, body)
        raise PayPalAPIError(r.status_code, body)
    return r.json()


def _is_live() -> bool:
    return os.environ.get("PAYPAL_MODE", "sandbox").lower() == "live"


def _client_id() -> str:
    return os.environ.get("PAYPAL_CLIENT_ID_LIVE" if _is_live() else "PAYPAL_CLIENT_ID_SANDBOX", "")


def _client_secret() -> str:
    return os.environ.get("PAYPAL_CLIENT_SECRET_LIVE" if _is_live() else "PAYPAL_CLIENT_SECRET_SANDBOX", "")


def _api_base() -> str:
    return "https://api-m.paypal.com" if _is_live() else "https://api-m.sandbox.paypal.com"


def public_client_id() -> str:
    """Used by the frontend — the Client ID is public, the Secret is not."""
    return _client_id()


def is_configured() -> bool:
    return bool(_client_id() and _client_secret())


async def _access_token(client: httpx.AsyncClient) -> str:
    """Exchange client credentials for an OAuth access token."""
    data = await _request(
        client, "POST", f"{_api_base()}/v1/oauth2/token",
        auth=(_client_id(), _client_secret()),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    return data["access_token"]


async def create_order(amount: float, sweet_vine_order_id: str, return_url: str, cancel_url: str) -> dict:
    """Create a PayPal Order — returns {id, status, links}."""
    if not is_configured():
        raise RuntimeError("PayPal credentials are not configured")
    async with httpx.AsyncClient() as client:
        token = await _access_token(client)
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": sweet_vine_order_id,
                    "amount": {"currency_code": "USD", "value": f"{amount:.2f}"},
                    "description": f"Sweet Vine Products order #{sweet_vine_order_id[:8].upper()}",
                }
            ],
            "application_context": {
                "brand_name": "Sweet Vine Products",
                "shipping_preference": "GET_FROM_FILE",
                "user_action": "PAY_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        data = await _request(
            client, "POST", f"{_api_base()}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
        logger.info("paypal create_order ok id=%s status=%s", data.get("id"), data.get("status"))
        return data


async def capture_order(paypal_order_id: str) -> dict:
    """Capture a previously-created (and buyer-approved) PayPal Order."""
    if not is_configured():
        raise RuntimeError("PayPal credentials are not configured")
    async with httpx.AsyncClient() as client:
        token = await _access_token(client)
        data = await _request(
            client, "POST", f"{_api_base()}/v2/checkout/orders/{paypal_order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=25.0,
        )
        logger.info("paypal capture_order ok id=%s status=%s", data.get("id"), data.get("status"))
        return data


async def verify_webhook(headers: dict, body_bytes: bytes, webhook_id: str) -> bool:
    """Verify a PayPal webhook event using PayPal's verify-webhook-signature API.
    Returns True only if PayPal confirms the signature is valid for the configured webhook_id.
    Returns False on any error / non-VERIFIED response — caller should reject the event.
    """
    if not (is_configured() and webhook_id):
        return False
    try:
        # PayPal needs the raw body as parsed JSON in the verification payload
        import json as _json
        event_body = _json.loads(body_bytes.decode("utf-8") or "{}")
    except Exception:
        logger.warning("paypal webhook verify: malformed body")
        return False

    # Lowercase-keyed access to PayPal's transmission headers
    h = {k.lower(): v for k, v in headers.items()}
    required = [
        "paypal-auth-algo",
        "paypal-cert-url",
        "paypal-transmission-id",
        "paypal-transmission-sig",
        "paypal-transmission-time",
    ]
    if not all(h.get(k) for k in required):
        logger.warning("paypal webhook verify: missing PAYPAL-TRANSMISSION-* headers")
        return False

    payload = {
        "auth_algo": h["paypal-auth-algo"],
        "cert_url": h["paypal-cert-url"],
        "transmission_id": h["paypal-transmission-id"],
        "transmission_sig": h["paypal-transmission-sig"],
        "transmission_time": h["paypal-transmission-time"],
        "webhook_id": webhook_id,
        "webhook_event": event_body,
    }
    try:
        async with httpx.AsyncClient() as client:
            token = await _access_token(client)
            data = await _request(
                client, "POST", f"{_api_base()}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
        verified = data.get("verification_status") == "SUCCESS"
        if not verified:
            logger.warning("paypal webhook verify: status=%s", data.get("verification_status"))
        return verified
    except (PayPalAPIError, Exception) as e:
        logger.warning("paypal webhook verify failed: %s", e)
        return False


async def get_order(paypal_order_id: str) -> dict:
    """Fetch the current state of an order (for webhook reconciliation)."""
    if not is_configured():
        raise RuntimeError("PayPal credentials are not configured")
    async with httpx.AsyncClient() as client:
        token = await _access_token(client)
        return await _request(
            client, "GET", f"{_api_base()}/v2/checkout/orders/{paypal_order_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
