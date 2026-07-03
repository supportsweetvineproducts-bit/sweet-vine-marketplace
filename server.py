from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import uuid
import asyncio
import logging
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Header
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict

from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout,
    CheckoutSessionRequest,
)

from email_service import (
    send_welcome_letter,
    send_order_confirmation,
    send_event_inquiry_confirmation,
    send_event_inquiry_notification,
    send_campaign_email,
)
from paypal_service import (
    create_order as paypal_create_order,
    capture_order as paypal_capture_order,
    public_client_id as paypal_public_client_id,
    is_configured as paypal_is_configured,
    verify_webhook as paypal_verify_webhook,
    PayPalAPIError,
)


def _fire_and_log(coro, label: str = "email"):
    """Run an async email task and log any uncaught exception."""
    task = asyncio.create_task(coro)
    def _done(t):
        exc = t.exception()
        if exc is not None:
            logger.error("%s task failed: %r", label, exc)
    task.add_done_callback(_done)
    return task

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("sweetvine")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
ACCESS_TTL_DAYS = 7

app = FastAPI(title="Sweet Vine Products API")
api = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str = "customer"
    created_at: datetime


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AuthOut(BaseModel):
    token: str
    user: UserPublic


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    slug: str
    category: str
    price: float
    description: str
    image_url: str
    images: List[str] = Field(default_factory=list)
    stock: int = 100
    featured: bool = False
    coming_soon: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProductIn(BaseModel):
    name: str
    slug: str
    category: str
    price: float
    description: str
    image_url: str
    images: List[str] = Field(default_factory=list)
    stock: int = 100
    featured: bool = False
    coming_soon: bool = False


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    images: Optional[List[str]] = None
    stock: Optional[int] = None
    featured: Optional[bool] = None
    coming_soon: Optional[bool] = None


class CartItemIn(BaseModel):
    product_id: str
    quantity: int = Field(ge=1)


class OrderIn(BaseModel):
    items: List[CartItemIn]
    customer_name: str
    customer_email: EmailStr
    shipping_address: str
    payment_method: Literal["stripe", "paypal", "zelle", "venmo"]
    origin_url: str
    discount_code: Optional[str] = None


class OrderItem(BaseModel):
    product_id: str
    name: str
    price: float
    quantity: int
    image_url: str


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: Optional[str] = None
    customer_name: str
    customer_email: EmailStr
    shipping_address: str
    items: List[OrderItem]
    subtotal: float
    items_subtotal: Optional[float] = None
    discount: Optional[dict] = None
    payment_method: str
    payment_status: str  # pending, paid, awaiting_verification, failed
    order_status: str  # placed, processing, shipped, delivered, cancelled
    stripe_session_id: Optional[str] = None
    created_at: datetime


class OrderStatusUpdate(BaseModel):
    payment_status: Optional[str] = None
    order_status: Optional[str] = None


class BlogPostIn(BaseModel):
    title: str
    slug: str
    excerpt: str
    body: str
    cover_image: str
    author: str = "Sweet Vine Team"


class BlogPost(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    title: str
    slug: str
    excerpt: str
    body: str
    cover_image: str
    author: str
    created_at: datetime


class NewsletterIn(BaseModel):
    email: EmailStr


class ContactIn(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str


class EventInquiryIn(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = ""
    event_type: str  # Wedding / Anniversary / Reunion / Corporate / Other
    event_date: Optional[str] = ""  # ISO date string
    guest_count: Optional[int] = None
    location: Optional[str] = ""
    message: Optional[str] = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=ACCESS_TTL_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def user_to_public(doc: dict) -> UserPublic:
    return UserPublic(
        id=doc["id"],
        email=doc["email"],
        name=doc["name"],
        role=doc.get("role", "customer"),
        created_at=datetime.fromisoformat(doc["created_at"]) if isinstance(doc["created_at"], str) else doc["created_at"],
    )


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------
@api.post("/auth/register", response_model=AuthOut)
async def register(payload: RegisterIn):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": payload.name,
        "password_hash": hash_password(payload.password),
        "role": "customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    public = user_to_public(doc)
    return AuthOut(token=create_token(public.id, public.email, public.role), user=public)


@api.post("/auth/login", response_model=AuthOut)
async def login(payload: LoginIn):
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    public = user_to_public(user)
    return AuthOut(token=create_token(public.id, public.email, public.role), user=public)


@api.get("/auth/me", response_model=UserPublic)
async def me(user: dict = Depends(get_current_user)):
    return user_to_public(user)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@api.get("/products", response_model=List[Product])
async def list_products(category: Optional[str] = None, featured: Optional[bool] = None):
    q: dict = {}
    if category:
        q["category"] = category
    if featured is not None:
        q["featured"] = featured
    docs = await db.products.find(q, {"_id": 0}).sort([("sort_order", 1), ("created_at", -1)]).to_list(500)
    return [Product(**d) for d in docs]


@api.get("/products/{slug}", response_model=Product)
async def get_product(slug: str):
    doc = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Product not found")
    return Product(**doc)


@api.post("/products", response_model=Product)
async def create_product(payload: ProductIn, _: dict = Depends(require_admin)):
    if await db.products.find_one({"slug": payload.slug}):
        raise HTTPException(400, "Slug already in use")
    product = Product(**payload.model_dump())
    doc = product.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.products.insert_one(doc)
    return product


@api.put("/products/{product_id}", response_model=Product)
async def update_product(product_id: str, payload: ProductUpdate, _: dict = Depends(require_admin)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    result = await db.products.update_one({"id": product_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Product not found")
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    return Product(**doc)


@api.delete("/products/{product_id}")
async def delete_product(product_id: str, _: dict = Depends(require_admin)):
    result = await db.products.delete_one({"id": product_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Orders + Payments
# ---------------------------------------------------------------------------
async def _build_order_items(items: List[CartItemIn]) -> tuple[List[OrderItem], float]:
    order_items: List[OrderItem] = []
    subtotal = 0.0
    if not items:
        return order_items, 0.0
    # Batch fetch products in a single query (avoids N+1)
    product_ids = [it.product_id for it in items]
    products = await db.products.find({"id": {"$in": product_ids}}, {"_id": 0}).to_list(len(product_ids))
    product_map = {p["id"]: p for p in products}
    for it in items:
        prod = product_map.get(it.product_id)
        if not prod:
            raise HTTPException(400, f"Product {it.product_id} not found")
        if prod.get("coming_soon"):
            raise HTTPException(400, f"'{prod['name']}' is coming soon and not yet available for purchase")
        order_items.append(
            OrderItem(
                product_id=prod["id"],
                name=prod["name"],
                price=float(prod["price"]),
                quantity=it.quantity,
                image_url=prod["image_url"],
            )
        )
        subtotal += float(prod["price"]) * it.quantity
    return order_items, round(subtotal, 2)


def _user_id_from_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        decoded = jwt.decode(authorization[7:], JWT_SECRET, algorithms=[JWT_ALG])
        return decoded.get("sub")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Discounts — first-time customer welcome promo
# ---------------------------------------------------------------------------
DISCOUNTS = {
    "WELCOME10": {"percent": 10, "label": "Welcome — 10% off your first order"},
    "AMERICA250": {"percent": 15, "label": "Father's Day + America's 250th — 15% off"},
}


def _resolve_discount(code: Optional[str]) -> Optional[dict]:
    if not code:
        return None
    return DISCOUNTS.get(code.strip().upper())


def _apply_discount(subtotal: float, code: Optional[str]) -> tuple[float, Optional[dict]]:
    rule = _resolve_discount(code)
    if not rule:
        return round(subtotal, 2), None
    discount_amount = round(subtotal * rule["percent"] / 100.0, 2)
    new_total = round(subtotal - discount_amount, 2)
    return new_total, {
        "code": code.strip().upper(),
        "percent": rule["percent"],
        "amount": discount_amount,
        "label": rule["label"],
    }


class DiscountCheckIn(BaseModel):
    code: str


@api.post("/discounts/validate")
async def validate_discount(payload: DiscountCheckIn):
    rule = _resolve_discount(payload.code)
    if not rule:
        raise HTTPException(404, "That code isn't valid")
    return {"code": payload.code.strip().upper(), "percent": rule["percent"], "label": rule["label"]}


def _build_order_doc(
    payload: OrderIn,
    items: List[OrderItem],
    subtotal: float,
    user_id: Optional[str],
    now: datetime,
) -> dict:
    payment_status = "pending" if payload.payment_method == "stripe" else "awaiting_verification"
    final_total, discount_info = _apply_discount(subtotal, payload.discount_code)
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "customer_name": payload.customer_name,
        "customer_email": payload.customer_email.lower(),
        "shipping_address": payload.shipping_address,
        "items": [it.model_dump() for it in items],
        "subtotal": final_total,
        "items_subtotal": subtotal,
        "discount": discount_info,
        "payment_method": payload.payment_method,
        "payment_status": payment_status,
        "order_status": "placed",
        "stripe_session_id": None,
        "created_at": now.isoformat(),
    }


async def _start_stripe_checkout(order_doc: dict, payload: OrderIn) -> dict:
    """Create a Stripe Checkout session for the order and persist the transaction.
    Returns the response fragment to merge into the API response.
    Side-effect: mutates `order_doc["stripe_session_id"]`."""
    order_id = order_doc["id"]
    subtotal = order_doc["subtotal"]
    origin = payload.origin_url.rstrip("/")
    stripe_checkout = StripeCheckout(
        api_key=os.environ["STRIPE_API_KEY"],
        webhook_url=f"{origin}/api/webhook/stripe",
    )
    session = await stripe_checkout.create_checkout_session(
        CheckoutSessionRequest(
            amount=float(subtotal),
            currency="usd",
            success_url=f"{origin}/order/{order_id}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/checkout?cancelled=1",
            metadata={"order_id": order_id, "source": "sweet_vine_checkout"},
        )
    )
    order_doc["stripe_session_id"] = session.session_id
    await db.payment_transactions.insert_one(
        {
            "order_id": order_id,
            "session_id": session.session_id,
            "amount": float(subtotal),
            "currency": "usd",
            "metadata": {"order_id": order_id},
            "payment_status": "initiated",
            "created_at": order_doc["created_at"],
        }
    )
    return {"checkout_url": session.url, "session_id": session.session_id}


def _manual_payment_response(order_id: str, subtotal: float, method: str) -> dict:
    handles = {
        "paypal": os.environ.get("PAYPAL_HANDLE", ""),
        "zelle": os.environ.get("ZELLE_HANDLE", ""),
        "venmo": os.environ.get("VENMO_HANDLE", ""),
    }
    handle = handles.get(method, "")
    return {
        "payment_handle": handle,
        "instructions": (
            f"Send ${subtotal:.2f} to {handle} "
            f"and include order ID {order_id} in the note. Your order will ship once payment is verified."
        ),
    }


@api.post("/orders")
async def create_order(payload: OrderIn, authorization: Optional[str] = Header(default=None)):
    items, subtotal = await _build_order_items(payload.items)
    if subtotal <= 0:
        raise HTTPException(400, "Cart is empty")

    user_id = _user_id_from_bearer(authorization)
    now = datetime.now(timezone.utc)
    order_doc = _build_order_doc(payload, items, subtotal, user_id, now)
    response: dict = {"order_id": order_doc["id"], "payment_status": order_doc["payment_status"]}

    if payload.payment_method == "stripe":
        response.update(await _start_stripe_checkout(order_doc, payload))
    else:
        response.update(_manual_payment_response(order_doc["id"], subtotal, payload.payment_method))

    await db.orders.insert_one(order_doc)

    # Stripe orders get the confirmation email after payment_status flips to "paid".
    if payload.payment_method != "stripe":
        _fire_and_log(send_order_confirmation(order_doc), label="order-confirmation")

    return response


@api.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str):
    doc = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Order not found")
    return Order(**doc)


@api.get("/orders/mine/all", response_model=List[Order])
async def my_orders(user: dict = Depends(get_current_user)):
    docs = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Order(**d) for d in docs]


@api.get("/admin/orders", response_model=List[Order])
async def admin_orders(_: dict = Depends(require_admin)):
    docs = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [Order(**d) for d in docs]


@api.put("/admin/orders/{order_id}", response_model=Order)
async def admin_update_order(order_id: str, payload: OrderStatusUpdate, _: dict = Depends(require_admin)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    result = await db.orders.update_one({"id": order_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Order not found")
    doc = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return Order(**doc)


# Stripe status polling
@api.get("/payments/checkout/status/{session_id}")
async def checkout_status(session_id: str):
    txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not txn:
        raise HTTPException(404, "Transaction not found")
    order = await db.orders.find_one({"stripe_session_id": session_id}, {"_id": 0})
    origin = "http://localhost"  # not used for status; webhook_url required by constructor
    stripe_checkout = StripeCheckout(
        api_key=os.environ["STRIPE_API_KEY"], webhook_url=f"{origin}/api/webhook/stripe"
    )
    status = await stripe_checkout.get_checkout_status(session_id)

    # idempotent update — only mark paid once
    if status.payment_status == "paid" and txn.get("payment_status") != "paid":
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "paid", "status": status.status}},
        )
        if order:
            await db.orders.update_one(
                {"id": order["id"]}, {"$set": {"payment_status": "paid", "order_status": "processing"}}
            )
            # send confirmation email once
            refreshed = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
            if refreshed:
                _fire_and_log(send_order_confirmation(refreshed), label="order-confirmation")
    elif status.status == "expired" and txn.get("payment_status") != "paid":
        await db.payment_transactions.update_one(
            {"session_id": session_id}, {"$set": {"payment_status": "expired", "status": status.status}}
        )
        if order:
            await db.orders.update_one({"id": order["id"]}, {"$set": {"payment_status": "failed"}})

    return {
        "status": status.status,
        "payment_status": status.payment_status,
        "amount_total": status.amount_total,
        "currency": status.currency,
    }


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    origin = str(request.base_url).rstrip("/")
    stripe_checkout = StripeCheckout(
        api_key=os.environ["STRIPE_API_KEY"], webhook_url=f"{origin}/api/webhook/stripe"
    )
    try:
        evt = await stripe_checkout.handle_webhook(body, signature)
    except Exception as e:
        logger.exception("webhook error: %s", e)
        raise HTTPException(400, "Invalid webhook")
    if evt.session_id:
        order = await db.orders.find_one({"stripe_session_id": evt.session_id})
        if order and evt.payment_status == "paid" and order.get("payment_status") != "paid":
            await db.orders.update_one(
                {"id": order["id"]}, {"$set": {"payment_status": "paid", "order_status": "processing"}}
            )
            await db.payment_transactions.update_one(
                {"session_id": evt.session_id}, {"$set": {"payment_status": "paid"}}
            )
            refreshed = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
            if refreshed:
                _fire_and_log(send_order_confirmation(refreshed), label="order-confirmation")
    return {"received": True}


# ---------------------------------------------------------------------------
# PayPal Smart Buttons
# ---------------------------------------------------------------------------
@api.get("/paypal/config")
async def paypal_config():
    """Public config the frontend uses to render the Smart Buttons SDK."""
    return {
        "client_id": paypal_public_client_id(),
        "mode": os.environ.get("PAYPAL_MODE", "sandbox"),
        "currency": "USD",
        "enabled": paypal_is_configured(),
    }


class PayPalCreateOrderIn(BaseModel):
    sweet_vine_order_id: str
    origin_url: str


@api.post("/paypal/create-order")
async def paypal_create(payload: PayPalCreateOrderIn):
    """Step 1 — frontend calls this from the PayPalButtons.createOrder callback."""
    if not paypal_is_configured():
        raise HTTPException(503, "PayPal is not yet configured. Please use another payment method.")
    order = await db.orders.find_one({"id": payload.sweet_vine_order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Sweet Vine order not found")
    if order.get("payment_status") == "paid":
        raise HTTPException(400, "Order has already been paid")
    origin = payload.origin_url.rstrip("/")
    pp: dict = {}
    try:
        pp = await paypal_create_order(
            amount=float(order["subtotal"]),
            sweet_vine_order_id=order["id"],
            return_url=f"{origin}/order/{order['id']}",
            cancel_url=f"{origin}/checkout?cancelled=1",
        )
    except PayPalAPIError as exc:
        raise HTTPException(400, f"PayPal could not start checkout: {exc.description}")
    if not pp.get("id"):
        raise HTTPException(502, "PayPal did not return an order id")
    await db.orders.update_one(
        {"id": order["id"]},
        {"$set": {"paypal_order_id": pp["id"], "payment_status": "pending"}},
    )
    return {"id": pp["id"], "status": pp.get("status")}


class PayPalCaptureIn(BaseModel):
    sweet_vine_order_id: str
    paypal_order_id: str


@api.post("/paypal/capture-order")
async def paypal_capture(payload: PayPalCaptureIn):
    """Step 2 — frontend calls this from PayPalButtons.onApprove."""
    if not paypal_is_configured():
        raise HTTPException(503, "PayPal is not configured")
    order = await db.orders.find_one({"id": payload.sweet_vine_order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Sweet Vine order not found")
    if order.get("payment_status") == "paid":
        return {"status": "already_paid", "order_id": order["id"]}

    try:
        capture = await paypal_capture_order(payload.paypal_order_id)
    except PayPalAPIError as exc:
        # Common cases: ORDER_NOT_APPROVED · INSTRUMENT_DECLINED · PAYER_ACTION_REQUIRED
        friendly = {
            "ORDER_NOT_APPROVED": "PayPal hasn't received the buyer's approval yet. Please complete the PayPal window first.",
            "INSTRUMENT_DECLINED": "Your funding source was declined. Please try a different card or PayPal balance.",
            "PAYER_ACTION_REQUIRED": "PayPal needs an extra step from you — open the PayPal window again to finish.",
        }.get(exc.issue, exc.description)
        await db.orders.update_one(
            {"id": order["id"]},
            {"$set": {"payment_status": "failed", "paypal_capture_error": exc.body}},
        )
        raise HTTPException(400, friendly)

    captured_ok = capture.get("status") == "COMPLETED"
    if captured_ok:
        await db.orders.update_one(
            {"id": order["id"]},
            {"$set": {"payment_status": "paid", "order_status": "processing", "paypal_capture": capture}},
        )
        refreshed = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
        if refreshed:
            _fire_and_log(send_order_confirmation(refreshed), label="order-confirmation")
        return {"status": "paid", "order_id": order["id"]}

    # Captured but not COMPLETED (PENDING / DECLINED etc.)
    await db.orders.update_one(
        {"id": order["id"]},
        {"$set": {"payment_status": "failed", "paypal_capture": capture}},
    )
    raise HTTPException(400, f"PayPal capture status: {capture.get('status')}. Please try again.")


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    """Async PayPal events (refunds, disputes, captures).
    Verifies the PAYPAL-TRANSMISSION-* signature against PayPal's verify-webhook-signature API.
    Drops un-verified events. Configure PAYPAL_WEBHOOK_ID in .env after creating the webhook
    in the PayPal Developer Dashboard.
    """
    body_bytes = await request.body()
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "")
    if not webhook_id:
        # No webhook id configured yet — log only, never mutate orders
        logger.warning("paypal webhook received but PAYPAL_WEBHOOK_ID is not set — dropping for safety")
        return {"received": True, "verified": False}

    verified = await paypal_verify_webhook(dict(request.headers), body_bytes, webhook_id)
    if not verified:
        logger.warning("paypal webhook signature verification FAILED — possible spoof")
        raise HTTPException(401, "Webhook signature invalid")

    try:
        event = await request.json()
    except Exception:
        event = {}
    event_type = event.get("event_type", "")
    resource = event.get("resource") or {}
    logger.info("paypal webhook verified event_type=%s id=%s", event_type, event.get("id"))

    # Handle the key event types
    if event_type in ("CHECKOUT.ORDER.APPROVED", "PAYMENT.CAPTURE.COMPLETED"):
        paypal_order_id = resource.get("id") or (resource.get("supplementary_data", {}).get("related_ids", {}) or {}).get("order_id")
        if paypal_order_id:
            order = await db.orders.find_one({"paypal_order_id": paypal_order_id}, {"_id": 0})
            if order and order.get("payment_status") != "paid":
                await db.orders.update_one(
                    {"id": order["id"]},
                    {"$set": {"payment_status": "paid", "order_status": "processing"}},
                )
                refreshed = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
                if refreshed:
                    _fire_and_log(send_order_confirmation(refreshed), label="order-confirmation-webhook")
    return {"received": True, "verified": True}


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------
@api.get("/blog", response_model=List[BlogPost])
async def list_blog():
    docs = await db.blog.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [BlogPost(**d) for d in docs]


@api.get("/blog/{slug}", response_model=BlogPost)
async def get_blog(slug: str):
    doc = await db.blog.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Post not found")
    return BlogPost(**doc)


@api.post("/blog", response_model=BlogPost)
async def create_blog(payload: BlogPostIn, _: dict = Depends(require_admin)):
    if await db.blog.find_one({"slug": payload.slug}):
        raise HTTPException(400, "Slug already in use")
    post = BlogPost(id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc), **payload.model_dump())
    doc = post.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.blog.insert_one(doc)
    return post


@api.delete("/blog/{post_id}")
async def delete_blog(post_id: str, _: dict = Depends(require_admin)):
    r = await db.blog.delete_one({"id": post_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Post not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Newsletter + Contact
# ---------------------------------------------------------------------------
@api.post("/newsletter")
async def newsletter_subscribe(payload: NewsletterIn):
    email = payload.email.lower()
    existing = await db.newsletter.find_one({"email": email})
    if existing:
        return {"ok": True, "message": "Already subscribed"}
    await db.newsletter.insert_one(
        {"id": str(uuid.uuid4()), "email": email, "created_at": datetime.now(timezone.utc).isoformat()}
    )
    return {"ok": True, "message": "Subscribed!"}


class WelcomeIn(BaseModel):
    first_name: Optional[str] = ""
    email: EmailStr


@api.post("/welcome")
async def welcome_subscribe(payload: WelcomeIn):
    email = payload.email.lower()
    existing = await db.welcome_letter.find_one({"email": email})
    if existing:
        return {"ok": True, "message": "You're already on the welcome list."}
    await db.welcome_letter.insert_one(
        {
            "id": str(uuid.uuid4()),
            "first_name": (payload.first_name or "").strip(),
            "email": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    # Fire welcome letter (non-blocking, errors logged silently)
    _fire_and_log(send_welcome_letter(email, payload.first_name or ""), label="welcome")
    return {"ok": True, "message": "Welcome to the family."}


@api.get("/admin/welcome")
async def admin_list_welcome(_: dict = Depends(require_admin)):
    docs = await db.welcome_letter.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api.delete("/admin/welcome/{email}")
async def admin_delete_welcome(email: str, _: dict = Depends(require_admin)):
    """Delete a single welcome-letter subscriber by email."""
    res = await db.welcome_letter.delete_one({"email": email})
    return {"deleted": res.deleted_count}


@api.post("/admin/welcome/purge-test")
async def admin_purge_test_welcome(_: dict = Depends(require_admin)):
    """Remove obvious test entries: *@example.com, *@test.*, addresses starting
    with test_, plus duplicates beyond the most recent occurrence."""
    test_filter = {
        "$or": [
            {"email": {"$regex": "@example\\.(com|org|net|io)$", "$options": "i"}},
            {"email": {"$regex": "^test[_\\-@]", "$options": "i"}},
            {"email": {"$regex": "@test\\.", "$options": "i"}},
            {"email": {"$regex": "@localhost", "$options": "i"}},
        ]
    }
    res = await db.welcome_letter.delete_many(test_filter)

    # Also collapse exact-email duplicates, keeping the oldest record
    pipeline = [
        {"$sort": {"created_at": 1}},
        {"$group": {"_id": "$email", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    dup_deleted = 0
    async for grp in db.welcome_letter.aggregate(pipeline):
        # keep ids[0] (oldest), drop the rest
        for extra in grp["ids"][1:]:
            r = await db.welcome_letter.delete_one({"_id": extra})
            dup_deleted += r.deleted_count
    return {"test_deleted": res.deleted_count, "duplicates_deleted": dup_deleted}


class CampaignSendIn(BaseModel):
    subject: str = Field(min_length=2, max_length=180)
    body: str = Field(min_length=10, max_length=20000)
    preheader: str = ""
    audience: Literal["welcome", "newsletter", "both"] = "welcome"
    test_only: bool = False
    test_email: Optional[EmailStr] = None


def _campaign_body_html(plain_or_html: str) -> str:
    """If body looks like plain text, wrap each blank-line block in a <p> tag.
    Otherwise pass through as HTML."""
    s = plain_or_html.strip()
    if "<" in s and ">" in s:
        return s
    blocks = [b.strip() for b in s.split("\n\n") if b.strip()]
    return "\n".join(f'<p style="margin:0 0 14px 0;">{b.replace(chr(10), "<br>")}</p>' for b in blocks)


async def _collect_audience(audience: str) -> list[str]:
    emails: set[str] = set()
    if audience in ("welcome", "both"):
        async for d in db.welcome_letter.find({}, {"_id": 0, "email": 1}):
            if d.get("email"):
                emails.add(d["email"].lower())
    if audience in ("newsletter", "both"):
        async for d in db.newsletter.find({}, {"_id": 0, "email": 1}):
            if d.get("email"):
                emails.add(d["email"].lower())
    return sorted(emails)


@api.post("/admin/campaigns/send")
async def admin_send_campaign(payload: CampaignSendIn, _: dict = Depends(require_admin)):
    html_body = _campaign_body_html(payload.body)

    if payload.test_only:
        target = payload.test_email
        if not target:
            raise HTTPException(400, "Provide a test_email when test_only is true")
        eid = await send_campaign_email(target, payload.subject, html_body, preheader=payload.preheader)
        return {"ok": True, "mode": "test", "sent_to": [target], "sent_count": 1 if eid else 0}

    recipients = await _collect_audience(payload.audience)
    if not recipients:
        raise HTTPException(400, "No subscribers in the selected audience")

    # Send in parallel (Resend handles rate limits server-side; 100/req is well below their limits)
    results = await asyncio.gather(
        *[send_campaign_email(addr, payload.subject, html_body, preheader=payload.preheader) for addr in recipients],
        return_exceptions=True,
    )
    succeeded = sum(1 for r in results if isinstance(r, str))
    failed = len(recipients) - succeeded

    # Log the campaign for audit/history
    await db.campaigns.insert_one({
        "id": str(uuid.uuid4()),
        "subject": payload.subject,
        "preheader": payload.preheader,
        "audience": payload.audience,
        "recipient_count": len(recipients),
        "succeeded": succeeded,
        "failed": failed,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {"ok": True, "mode": "live", "recipient_count": len(recipients), "succeeded": succeeded, "failed": failed}


@api.get("/admin/campaigns")
async def admin_list_campaigns(_: dict = Depends(require_admin)):
    docs = await db.campaigns.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return docs


@api.post("/contact")
async def contact_submit(payload: ContactIn):
    await db.contact_messages.insert_one(
        {
            "id": str(uuid.uuid4()),
            "name": payload.name,
            "email": payload.email.lower(),
            "subject": payload.subject,
            "message": payload.message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Wedding & Events lead capture
# ---------------------------------------------------------------------------
@api.post("/event-inquiries")
async def event_inquiry_submit(payload: EventInquiryIn):
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "email": payload.email.lower(),
        "phone": (payload.phone or "").strip(),
        "event_type": payload.event_type,
        "event_date": (payload.event_date or "").strip(),
        "guest_count": payload.guest_count,
        "location": (payload.location or "").strip(),
        "message": (payload.message or "").strip(),
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.event_inquiries.insert_one(doc)
    # Send confirmation to the customer AND a notification to Lil Leo
    _fire_and_log(send_event_inquiry_confirmation(doc), label="event-inquiry-customer")
    _fire_and_log(send_event_inquiry_notification(doc), label="event-inquiry-admin")
    return {"ok": True, "id": doc["id"]}


@api.get("/admin/event-inquiries")
async def admin_list_event_inquiries(_: dict = Depends(require_admin)):
    docs = await db.event_inquiries.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


class EventInquiryStatusUpdate(BaseModel):
    status: str  # new / contacted / quoted / booked / closed


@api.put("/admin/event-inquiries/{inquiry_id}")
async def admin_update_event_inquiry(
    inquiry_id: str,
    payload: EventInquiryStatusUpdate,
    _: dict = Depends(require_admin),
):
    r = await db.event_inquiries.update_one(
        {"id": inquiry_id}, {"$set": {"status": payload.status}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Inquiry not found")
    return {"ok": True}


@api.get("/admin/newsletter")
async def admin_list_newsletter(_: dict = Depends(require_admin)):
    docs = await db.newsletter.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api.get("/admin/contact")
async def admin_list_contact(_: dict = Depends(require_admin)):
    docs = await db.contact_messages.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api.get("/admin/payment-handles")
async def admin_payment_handles(_: dict = Depends(require_admin)):
    return {
        "paypal": os.environ.get("PAYPAL_HANDLE", ""),
        "zelle": os.environ.get("ZELLE_HANDLE", ""),
        "venmo": os.environ.get("VENMO_HANDLE", ""),
    }


@api.get("/")
async def root():
    return {"message": "Sweet Vine Products API", "status": "ok"}


# ---------------------------------------------------------------------------
# Startup: indexes, admin seed, sample products
# ---------------------------------------------------------------------------
SAMPLE_PRODUCTS = [
    {
        "name": "Red Muscadine Juice",
        "slug": "red-muscadine-juice",
        "category": "Juices",
        "price": 18.0,
        "description": "Our award-winning 100% Red Muscadine Juice — cold-pressed from native Southern muscadine grapes. NCFSA 2024 \"Best In Taste\" winner. 25.4 Fl Oz (750 ml). No alcohol, no additives, no preservatives, no sugar added. Pasteurized. Refrigerate after opening.",
        "image_url": "https://customer-assets.emergentagent.com/job_vineyard-refresh-hub/artifacts/sozxiuho_rn-image_picker_lib_temp_4fe26851-8b3c-4195-a456-3633fe287678.png",
        "stock": 120,
        "featured": True,
    },
    {
        "name": "White Scuppernong Juice",
        "slug": "white-scuppernong-juice",
        "category": "Juices",
        "price": 18.0,
        "description": "Bright, honey-toned 100% White Scuppernong Juice. The Southern bronze grape, cold-pressed and bottled fresh. 25.4 Fl Oz (750 ml). No alcohol, no additives, no preservatives, no sugar added. Delicious scuppernong taste — health for the body, from the vine.",
        "image_url": "https://customer-assets.emergentagent.com/job_vineyard-refresh-hub/artifacts/b0w79657_rn-image_picker_lib_temp_c7e1c557-be98-459d-b086-9cf1fcc208c2.png",
        "stock": 120,
        "featured": True,
    },
    {
        "name": "Muscadine Heritage Jam",
        "slug": "muscadine-heritage-jam",
        "category": "Jellies, Jams & Preserves",
        "price": 12.5,
        "description": "Small-batch muscadine preserves made the old fashioned way. Spoon onto biscuits, cheese boards, or yogurt.",
        "image_url": "https://images.unsplash.com/photo-1776797117103-ecced3c3a1dd?w=1200",
        "stock": 80,
        "featured": True,
    },
    {
        "name": "Scuppernong Pepper Jelly",
        "slug": "scuppernong-pepper-jelly",
        "category": "Jellies, Jams & Preserves",
        "price": 13.0,
        "description": "Sweet scuppernong meets a gentle warmth of jalapeño. A southern table essential.",
        "image_url": "https://images.unsplash.com/photo-1776797117103-ecced3c3a1dd?w=1200&sat=-20",
        "stock": 60,
        "featured": False,
    },
]

SAMPLE_BLOG = [
    {
        "title": "Why Muscadines Are Nature's Superfruit",
        "slug": "why-muscadines-are-natures-superfruit",
        "excerpt": "Native to the American South, muscadines pack more antioxidants per ounce than nearly any other grape on earth.",
        "body": "Muscadines (Vitis rotundifolia) grow wild across the southeastern United States. Unlike their European cousins, muscadines have thick skins that are loaded with resveratrol, ellagic acid, and polyphenols.\n\nResearch from universities including UNC and UGA has highlighted muscadines' potential cardiovascular and anti-inflammatory benefits. Whether you're sipping the juice, spreading the jam, or popping a capsule, you're tapping into a heritage of wellness that's older than the country itself.",
        "cover_image": "https://static.prod-images.emergentagent.com/jobs/34b0f958-7f5d-4dc5-8c34-91b7e0fb475b/images/e62eb8984893f172e2b21d9c51ad91d224f6efae4193ad062295468c3eb5d6dc.png",
        "author": "Sweet Vine Team",
    },
    {
        "title": "Muscadine vs. Scuppernong: What's the Difference?",
        "slug": "muscadine-vs-scuppernong",
        "excerpt": "They're cousins, not twins. Here's how to tell them apart at the vineyard — and on the table.",
        "body": "All scuppernongs are muscadines, but not all muscadines are scuppernongs. Scuppernong is the bronze-skinned cultivar named after the Scuppernong River in North Carolina.\n\nMuscadines tend to be dark purple or black, with a deep, jammy flavor. Scuppernongs are golden and floral. Both make outstanding cold-pressed juice and preserves — and both deliver the same superfruit health benefits, without a drop of alcohol.",
        "cover_image": "https://images.unsplash.com/photo-1759221610612-3a3398d5e94d?w=1200",
        "author": "Sweet Vine Team",
    },
]


@app.on_event("startup")
async def on_startup():
    # indexes
    await db.users.create_index("email", unique=True)
    await db.products.create_index("slug", unique=True)
    await db.blog.create_index("slug", unique=True)
    await db.orders.create_index("id", unique=True)

    # admin seed (idempotent)
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one(
            {
                "id": str(uuid.uuid4()),
                "email": admin_email,
                "name": "Sweet Vine Admin",
                "password_hash": hash_password(admin_password),
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info("admin user seeded")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password), "role": "admin"}},
        )
        logger.info("admin password refreshed")

    # seed products if collection empty
    if await db.products.count_documents({}) == 0:
        now = datetime.now(timezone.utc).isoformat()
        await db.products.insert_many(
            [
                {**p, "id": str(uuid.uuid4()), "created_at": now}
                for p in SAMPLE_PRODUCTS
            ]
        )
        logger.info("sample products seeded")

    if await db.blog.count_documents({}) == 0:
        now = datetime.now(timezone.utc).isoformat()
        await db.blog.insert_many(
            [{**b, "id": str(uuid.uuid4()), "created_at": now} for b in SAMPLE_BLOG]
        )
        logger.info("sample blog seeded")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
