"""PayPal Smart Buttons integration tests (Sweet Vine Products iter_5)."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://vineyard-refresh-hub.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sweetvine.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "SweetVine2026!")


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def customer(session):
    email = f"TEST_paypal_{uuid.uuid4().hex[:8]}@example.com"
    r = session.post(f"{API}/auth/register", json={"email": email, "password": "Password123!", "name": "PP Buyer"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"email": email, "token": data["token"], "id": data["user"]["id"]}


@pytest.fixture(scope="module")
def normal_product(session):
    r = session.get(f"{API}/products/red-muscadine-juice")
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def coming_soon_product(session):
    r = session.get(f"{API}/products/gift-3pack-pint")
    assert r.status_code == 200
    p = r.json()
    assert p["coming_soon"] is True
    return p


# ---------- /api/paypal/config ----------
class TestPayPalConfig:
    def test_config_returns_sandbox(self, session):
        r = session.get(f"{API}/paypal/config")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] in ("sandbox", "live")  # accept either — depends on PAYPAL_MODE
        assert d["currency"] == "USD"
        assert d["enabled"] is True
        assert isinstance(d["client_id"], str) and len(d["client_id"]) > 20
        # sandbox client_id should match the env-configured one
        env_cid = os.environ.get("PAYPAL_CLIENT_ID_SANDBOX")
        if env_cid:
            assert d["client_id"] == env_cid


# ---------- POST /api/orders with payment_method=paypal ----------
class TestPayPalOrderCreation:
    def test_paypal_order_awaiting_verification(self, session, customer, normal_product):
        payload = {
            "items": [{"product_id": normal_product["id"], "quantity": 2}],
            "customer_name": "PayPal Buyer",
            "customer_email": customer["email"],
            "shipping_address": "12 Vine Way, Charleston SC",
            "payment_method": "paypal",
            "origin_url": BASE_URL,
        }
        r = session.post(f"{API}/orders", json=payload,
                         headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "order_id" in data
        assert data["payment_status"] == "awaiting_verification"
        # persistence check
        ro = session.get(f"{API}/orders/{data['order_id']}")
        assert ro.status_code == 200
        body = ro.json()
        assert body["payment_method"] == "paypal"
        assert body["payment_status"] == "awaiting_verification"

    def test_paypal_order_with_coming_soon_rejected_400(self, session, customer, coming_soon_product):
        payload = {
            "items": [{"product_id": coming_soon_product["id"], "quantity": 1}],
            "customer_name": "Blocked",
            "customer_email": customer["email"],
            "shipping_address": "x",
            "payment_method": "paypal",
            "origin_url": BASE_URL,
        }
        r = session.post(f"{API}/orders", json=payload,
                         headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 400, r.text
        assert "coming soon" in r.text.lower()


# ---------- /api/paypal/create-order ----------
class TestPayPalCreateOrder:
    @pytest.fixture(scope="class")
    def sv_order_id(self, session, customer, normal_product):
        payload = {
            "items": [{"product_id": normal_product["id"], "quantity": 1}],
            "customer_name": "Create Buyer",
            "customer_email": customer["email"],
            "shipping_address": "1 Vine Way",
            "payment_method": "paypal",
            "origin_url": BASE_URL,
        }
        r = session.post(f"{API}/orders", json=payload,
                         headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 200, r.text
        return r.json()["order_id"]

    def test_create_order_returns_paypal_id_and_created(self, session, sv_order_id):
        r = session.post(f"{API}/paypal/create-order",
                         json={"sweet_vine_order_id": sv_order_id, "origin_url": BASE_URL})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "id" in d and isinstance(d["id"], str) and len(d["id"]) >= 10
        # alphanumeric token from PayPal
        assert d["id"].replace("-", "").isalnum()
        assert d["status"] == "CREATED"

    def test_create_order_unknown_order_404(self, session):
        r = session.post(f"{API}/paypal/create-order",
                         json={"sweet_vine_order_id": "non-existent-sv-order", "origin_url": BASE_URL})
        assert r.status_code == 404

    def test_create_order_already_paid_400(self, session, customer, normal_product, admin_token=None):
        # create an order
        payload = {
            "items": [{"product_id": normal_product["id"], "quantity": 1}],
            "customer_name": "Paid Buyer",
            "customer_email": customer["email"],
            "shipping_address": "addr",
            "payment_method": "paypal",
            "origin_url": BASE_URL,
        }
        r = session.post(f"{API}/orders", json=payload,
                         headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 200
        oid = r.json()["order_id"]
        # admin login + mark as paid
        adm = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert adm.status_code == 200
        admin_tok = adm.json()["token"]
        up = session.put(f"{API}/admin/orders/{oid}",
                         json={"payment_status": "paid"},
                         headers={"Authorization": f"Bearer {admin_tok}"})
        assert up.status_code == 200
        # now create-order should 400
        r2 = session.post(f"{API}/paypal/create-order",
                          json={"sweet_vine_order_id": oid, "origin_url": BASE_URL})
        assert r2.status_code == 400, r2.text
        assert "already" in r2.text.lower() or "paid" in r2.text.lower()


# ---------- /api/paypal/capture-order ----------
class TestPayPalCaptureOrder:
    def test_capture_unapproved_returns_400(self, session, customer, normal_product):
        # First make sweet-vine order
        payload = {
            "items": [{"product_id": normal_product["id"], "quantity": 1}],
            "customer_name": "Cap Buyer",
            "customer_email": customer["email"],
            "shipping_address": "a",
            "payment_method": "paypal",
            "origin_url": BASE_URL,
        }
        r = session.post(f"{API}/orders", json=payload,
                         headers={"Authorization": f"Bearer {customer['token']}"})
        oid = r.json()["order_id"]
        # Create a PayPal order to get a real (unapproved) id
        c = session.post(f"{API}/paypal/create-order",
                         json={"sweet_vine_order_id": oid, "origin_url": BASE_URL})
        assert c.status_code == 200, c.text
        pp_id = c.json()["id"]
        # capture without buyer approval → should be 400 with helpful error
        cap = session.post(f"{API}/paypal/capture-order",
                           json={"sweet_vine_order_id": oid, "paypal_order_id": pp_id})
        assert cap.status_code == 400, f"expected 400, got {cap.status_code}: {cap.text}"


# ---------- /api/paypal/webhook ----------
class TestPayPalWebhook:
    def test_webhook_returns_received(self, session):
        # When PAYPAL_WEBHOOK_ID is not configured, the endpoint drops the event
        # safely and returns verified=false. The HTTP status is still 200.
        r = session.post(f"{API}/paypal/webhook", json={"event_type": "TEST", "id": "x"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("received") is True
        assert "verified" in body

    def test_webhook_empty_body_ok(self, session):
        r = session.post(f"{API}/paypal/webhook", data="", headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("received") is True
