"""
Resend email service for Sweet Vine Products.
Sends welcome letters + order confirmations as non-blocking async tasks.
"""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional

import resend

logger = logging.getLogger("sweetvine.email")

resend.api_key = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
SENDER_NAME = os.environ.get("SENDER_NAME", "Sweet Vine Products")
REPLY_TO = os.environ.get("REPLY_TO_EMAIL", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "").rstrip("/")
FROM_HEADER = f"{SENDER_NAME} <{SENDER_EMAIL}>"

BURGUNDY = "#5C1A2B"
CREAM = "#F9F6F0"
AMBER = "#C97941"


async def _send(to: str, subject: str, html: str) -> Optional[str]:
    """Internal: dispatch a single email; logs and swallows errors so the
    triggering API never fails because of email problems."""
    if not resend.api_key:
        logger.warning("RESEND_API_KEY missing — skipping send to %s (subject=%s)", to, subject)
        return None
    params = {
        "from": FROM_HEADER,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if REPLY_TO:
        params["reply_to"] = [REPLY_TO]
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        eid = result.get("id") if isinstance(result, dict) else None
        logger.info("resend sent ok — to=%s id=%s subject=%s", to, eid, subject)
        return eid
    except Exception as e:
        logger.exception("resend send failed to %s subject=%s: %s", to, subject, e)
        return None


def _layout(body_html: str, preheader: str = "") -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:{CREAM};font-family:Georgia,'Times New Roman',serif;color:#2A2426;">
  <span style="display:none!important;opacity:0;color:transparent;height:0;width:0;overflow:hidden;">{preheader}</span>
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CREAM};padding:32px 12px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border:1px solid #e9e1d4;border-radius:14px;overflow:hidden;">
        <tr><td style="background:{BURGUNDY};padding:28px 32px;text-align:center;">
          <div style="font-family:Georgia,serif;color:#ffffff;font-size:30px;letter-spacing:.5px;">Sweet Vine Products<sup style="font-size:11px;opacity:.7;">&trade;</sup></div>
          <div style="font-family:Georgia,serif;font-style:italic;color:#f6e7d6;font-size:14px;margin-top:6px;">A Healthy Body ~ From The Vine</div>
        </td></tr>
        <tr><td style="padding:36px 36px 24px 36px;font-size:16px;line-height:1.65;color:#2A2426;">
          {body_html}
        </td></tr>
        <tr><td style="padding:20px 32px 28px 32px;border-top:1px solid #e9e1d4;font-size:12px;color:#6b6260;text-align:center;">
          Sweet Vine Products &middot; 100% Juice &middot; No Alcohol &middot; No Sugar &middot; No Additives<br>
          You're receiving this because you ordered from or subscribed to Sweet Vine Products.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


# --------- Public helpers --------------------------------------------------

async def send_welcome_letter(email: str, first_name: str = "") -> Optional[str]:
    greeting = f"Welcome, {first_name.strip()}!" if first_name and first_name.strip() else "Welcome to the family!"
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:28px;color:{BURGUNDY};margin:0 0 14px 0;">{greeting}</h1>
      <p style="margin:0 0 14px 0;">I'm so glad you found your way to our little corner of the vineyard. I'm <strong>Delgrita &mdash; Lil Leo</strong>, and Sweet Vine Products is more than a brand to me. It's a story of healing, faith, and the road God walked us down.</p>
      <p style="margin:0 0 14px 0;">Over the next few days you'll get the rest of Lil Leo's <em>3-part welcome series</em> &mdash; the founder's healing story, the legacy of the muscadine, and a behind-the-scenes look at how every bottle is cold-pressed in small batches.</p>
      <div style="margin:22px 0 22px 0;padding:18px 22px;border:2px dashed {BURGUNDY};border-radius:12px;text-align:center;background:#fbf6ec;">
        <div style="font-family:Georgia,serif;font-size:13px;color:{BURGUNDY};letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">A little gift to start</div>
        <div style="font-family:Georgia,serif;font-size:30px;color:{BURGUNDY};font-weight:bold;letter-spacing:3px;">WELCOME10</div>
        <div style="font-size:13px;color:#5b5b5b;margin-top:6px;">Save 10% on your first order. Tap below and it applies automatically.</div>
      </div>
      <p style="text-align:center;margin:24px 0;">
        <a href="{FRONTEND_URL}/shop?promo=WELCOME10"
           style="background:{BURGUNDY};color:#ffffff;text-decoration:none;font-family:Georgia,serif;font-size:16px;padding:14px 28px;border-radius:999px;display:inline-block;">Claim 10% off &rarr;</a>
      </p>
      <p style="margin:24px 0 0 0;font-family:Georgia,serif;font-style:italic;color:{AMBER};">With grace,<br>Lil Leo</p>
    """
    return await _send(email, "Welcome to Sweet Vine — 10% off inside", _layout(body, preheader="A healthy body, from the vine. Your WELCOME10 code awaits."))


def _format_order_items_table(items: list[dict], subtotal: float) -> str:
    rows = []
    for it in items:
        name = it.get("name", "")
        qty = it.get("quantity", it.get("qty", 1))
        line_total = float(it.get("subtotal", it.get("price", 0) * qty))
        rows.append(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid #f0eadf;">'
            f'<strong>{name}</strong><br><span style="color:#6b6260;font-size:13px;">Qty {qty}</span></td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #f0eadf;text-align:right;font-variant-numeric:tabular-nums;">${line_total:.2f}</td></tr>'
        )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:18px 0;font-size:15px;">'
        + "".join(rows)
        + f'<tr><td style="padding:14px 0 0 0;font-family:Georgia,serif;font-size:18px;">Total</td>'
          f'<td style="padding:14px 0 0 0;font-family:Georgia,serif;font-size:18px;text-align:right;color:{BURGUNDY};font-variant-numeric:tabular-nums;"><strong>${subtotal:.2f}</strong></td></tr>'
        '</table>'
    )


async def send_order_confirmation(order: dict) -> Optional[str]:
    email = order.get("customer_email")
    if not email:
        return None
    name = (order.get("customer_name") or "").split(" ")[0] or "friend"
    order_id = order.get("id", "")
    subtotal = float(order.get("subtotal", 0))
    items = order.get("items", [])

    items_table = _format_order_items_table(items, subtotal)
    shipping = order.get("shipping_address")
    address_html = ""
    if isinstance(shipping, dict) and shipping:
        parts = [shipping.get("line1"), shipping.get("line2"), f"{shipping.get('city', '')}, {shipping.get('state', '')} {shipping.get('postal_code', '')}".strip(", "), shipping.get("country")]
        parts = [p for p in parts if p]
        address_html = (
            '<p style="margin:6px 0 0 0;color:#6b6260;font-size:14px;line-height:1.55;">'
            + "<br>".join(parts) + "</p>"
        )
    elif isinstance(shipping, str) and shipping.strip():
        # OrderIn.shipping_address is a free-form string today — render as-is, line-wrap on commas
        safe = shipping.replace(", ", "<br>")
        address_html = (
            '<p style="margin:6px 0 0 0;color:#6b6260;font-size:14px;line-height:1.55;">'
            + safe + "</p>"
        )

    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:26px;color:{BURGUNDY};margin:0 0 8px 0;">Thank you, {name}!</h1>
      <p style="margin:0 0 14px 0;color:#6b6260;font-size:14px;">Order <strong style="color:#2A2426;">#{order_id[:8].upper()}</strong> &middot; placed on {order.get('created_at', '')[:10]}</p>
      <p style="margin:0 0 14px 0;">We've received your order and are getting it ready for you. You'll get another note from us as soon as it ships.</p>
      {items_table}
      <h3 style="font-family:Georgia,serif;font-size:18px;color:{BURGUNDY};margin:22px 0 4px 0;">Ship to</h3>
      <p style="margin:0;"><strong>{order.get('customer_name', '')}</strong></p>
      {address_html}
      <p style="margin:22px 0 0 0;font-family:Georgia,serif;font-style:italic;color:{AMBER};">From our family to yours,<br>Lil Leo &amp; the Sweet Vine team</p>
    """
    return await _send(email, f"Your Sweet Vine order #{order_id[:8].upper()} is confirmed", _layout(body, preheader=f"Order total ${subtotal:.2f}"))


# ---------------------------------------------------------------------------
# Wedding & Events
# ---------------------------------------------------------------------------
def _event_summary_html(inq: dict) -> str:
    rows = [
        ("Name", inq.get("name", "")),
        ("Email", inq.get("email", "")),
        ("Phone", inq.get("phone") or "—"),
        ("Event type", inq.get("event_type", "")),
        ("Date", inq.get("event_date") or "—"),
        ("Guest count", str(inq.get("guest_count") or "—")),
        ("Location", inq.get("location") or "—"),
    ]
    cells = "".join(
        f'<tr><td style="padding:6px 14px 6px 0;color:#6b6260;font-size:13px;width:140px;vertical-align:top;">{k}</td>'
        f'<td style="padding:6px 0;color:#2A2426;font-size:14px;">{v}</td></tr>'
        for k, v in rows
    )
    note = inq.get("message") or ""
    note_html = (
        f'<h3 style="font-family:Georgia,serif;color:{BURGUNDY};font-size:16px;margin:18px 0 4px 0;">Their note</h3>'
        f'<p style="margin:0;color:#2A2426;font-size:14px;line-height:1.6;white-space:pre-wrap;">{note}</p>'
        if note else ""
    )
    return f'<table cellpadding="0" cellspacing="0" border="0" style="margin:14px 0;">{cells}</table>{note_html}'


async def send_event_inquiry_confirmation(inq: dict) -> Optional[str]:
    """Confirmation to the customer that we received their event inquiry."""
    email = inq.get("email")
    if not email:
        return None
    name = (inq.get("name") or "").split(" ")[0] or "friend"
    ev = inq.get("event_type", "celebration")
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:26px;color:{BURGUNDY};margin:0 0 12px 0;">Thank you, {name}!</h1>
      <p style="margin:0 0 14px 0;">We received your {ev.lower()} inquiry and I'll be in touch personally within 48 hours with case pricing and any questions about your day.</p>
      <p style="margin:0 0 14px 0;">In the meantime, take a peek at our cases and gift options — every bottle is 100% juice, alcohol-free, and bottled in small batches the old-fashioned way.</p>
      <p style="text-align:center;margin:24px 0;">
        <a href="{FRONTEND_URL}/shop?category=Muscadine%20Juices"
           style="background:{BURGUNDY};color:#ffffff;text-decoration:none;font-family:Georgia,serif;font-size:16px;padding:14px 28px;border-radius:999px;display:inline-block;">Browse cases &rarr;</a>
      </p>
      <p style="margin:18px 0 0 0;font-family:Georgia,serif;font-style:italic;color:{AMBER};">With grace,<br>Lil Leo &amp; the Sweet Vine team</p>
    """
    return await _send(email, "We received your event inquiry — Sweet Vine Products", _layout(body, preheader="Thank you — Lil Leo will be in touch within 48 hours."))


async def send_event_inquiry_notification(inq: dict) -> Optional[str]:
    """Internal notification to Lil Leo's reply-to address."""
    notify_to = REPLY_TO or os.environ.get("REPLY_TO_EMAIL", "")
    if not notify_to:
        return None
    ev = inq.get("event_type", "Event")
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:24px;color:{BURGUNDY};margin:0 0 6px 0;">New {ev} inquiry</h1>
      <p style="margin:0 0 6px 0;color:#6b6260;font-size:13px;">Received {inq.get('created_at','')[:16].replace('T',' ')}</p>
      {_event_summary_html(inq)}
      <p style="margin:18px 0 0 0;font-size:13px;color:#6b6260;">Reply directly to <a href="mailto:{inq.get('email','')}">{inq.get('email','')}</a> or update the status in the Sweet Vine admin dashboard.</p>
    """
    return await _send(notify_to, f"New {ev} inquiry from {inq.get('name','')}", _layout(body, preheader=f"{inq.get('name','')} · {inq.get('event_date') or 'date TBD'}"))



async def send_campaign_email(to: str, subject: str, body_html: str, preheader: str = "") -> Optional[str]:
    """Send a one-off marketing campaign email to a single recipient.
    Body is plain text or basic HTML — wrapped in the standard Sweet Vine layout.
    Errors are swallowed so a single failure doesn't stop the batch."""
    return await _send(to, subject, _layout(body_html, preheader=preheader))
