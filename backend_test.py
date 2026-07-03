"""Sweet Vine Products backend tests."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://vineyard-refresh-hub.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sweetvine.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "SweetVine2026!")
TEST_CUSTOMER_PASSWORD = os.environ.get("TEST_CUSTOMER_PASSWORD", "Password123!")


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"]["role"] == "admin"
    return data["token"]


@pytest.fixture(scope="session")
def customer(session):
    email = f"TEST_user_{uuid.uuid4().hex[:8]}@example.com"
    password = TEST_CUSTOMER_PASSWORD
    r = session.post(f"{API}/auth/register", json={"email": email, "password": password, "name": "Test User"})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"email": email, "password": password, "token": data["token"], "id": data["user"]["id"]}


# ---------- Products ----------
class TestProducts:
    def test_list_products_returns_seeded(self, session):
        r = session.get(f"{API}/products")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert len(items) >= 6, f"expected >=6 seeded products, got {len(items)}"
        # validate structure
        p = items[0]
        for k in ["id", "name", "slug", "category", "price", "image_url"]:
            assert k in p

    def test_filter_by_category_muscadine_juices(self, session):
        r = session.get(f"{API}/products", params={"category": "Muscadine Juices"})
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 4, f"expected 4 muscadine juices, got {len(items)}"
        slugs = {p["slug"] for p in items}
        assert {"red-muscadine-juice", "white-scuppernong-juice"}.issubset(slugs)
        for p in items:
            assert p["category"] == "Muscadine Juices"

    def test_categories_master_set(self, session):
        r = session.get(f"{API}/products")
        assert r.status_code == 200
        cats = {p["category"] for p in r.json()}
        expected = {"Muscadine Juices", "Artisan Ciders", "Spreads & Jellies", "Sauces & Dressings", "Gift Boxes"}
        assert expected.issubset(cats), f"missing categories. got={cats}"

    def test_no_supplements_or_wines(self, session):
        r = session.get(f"{API}/products")
        assert r.status_code == 200
        cats = {p["category"] for p in r.json()}
        assert "Supplements" not in cats, f"Supplements still present: {cats}"
        assert "Wines" not in cats, f"Wines still present: {cats}"
        # filtered query should also return nothing for those removed categories
        for bad in ["Supplements", "Wines"]:
            rr = session.get(f"{API}/products", params={"category": bad})
            assert rr.status_code == 200
            assert rr.json() == []

    def test_get_red_muscadine_juice(self, session):
        r = session.get(f"{API}/products/red-muscadine-juice")
        assert r.status_code == 200
        p = r.json()
        assert p["slug"] == "red-muscadine-juice"
        assert p["category"] == "Muscadine Juices"
        assert p["name"] == "Red Muscadine Juice"

    def test_get_white_scuppernong_juice(self, session):
        r = session.get(f"{API}/products/white-scuppernong-juice")
        assert r.status_code == 200
        p = r.json()
        assert p["slug"] == "white-scuppernong-juice"
        assert p["category"] == "Muscadine Juices"
        assert p["name"] == "White Scuppernong Juice"

    def test_get_product_404(self, session):
        r = session.get(f"{API}/products/nonexistent-slug-xyz")
        assert r.status_code == 404


# ---------- Blog ----------
class TestBlog:
    def test_list_blog(self, session):
        r = session.get(f"{API}/blog")
        assert r.status_code == 200
        posts = r.json()
        assert len(posts) >= 2

    def test_blog_by_slug(self, session):
        r = session.get(f"{API}/blog/why-muscadines-are-natures-superfruit")
        assert r.status_code == 200
        post = r.json()
        assert post["slug"] == "why-muscadines-are-natures-superfruit"
        assert "body" in post and len(post["body"]) > 0


# ---------- Auth ----------
class TestAuth:
    def test_register_and_me(self, session):
        email = f"TEST_reg_{uuid.uuid4().hex[:8]}@example.com"
        r = session.post(f"{API}/auth/register", json={"email": email, "password": "Pass1234", "name": "Reg User"})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data and data["user"]["email"] == email.lower()
        # me
        rm = session.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
        assert rm.status_code == 200
        assert rm.json()["email"] == email.lower()

    def test_register_duplicate(self, session, customer):
        r = session.post(f"{API}/auth/register", json={"email": customer["email"], "password": "x" * 8, "name": "Dup"})
        assert r.status_code == 400

    def test_login_admin(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_login_invalid(self, session):
        r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me_no_token(self, session):
        r = session.get(f"{API}/auth/me")
        assert r.status_code == 401


# ---------- Admin product CRUD ----------
class TestAdminProductCRUD:
    def test_customer_cannot_create_product(self, session, customer):
        r = session.post(
            f"{API}/products",
            json={"name": "X", "slug": "x", "category": "Juices", "price": 1.0, "description": "d", "image_url": "u"},
            headers={"Authorization": f"Bearer {customer['token']}"},
        )
        assert r.status_code == 403

    def test_admin_full_crud(self, session, admin_token):
        slug = f"test-product-{uuid.uuid4().hex[:8]}"
        # create
        r = session.post(
            f"{API}/products",
            json={
                "name": "TEST Product",
                "slug": slug,
                "category": "Juices",
                "price": 9.99,
                "description": "test",
                "image_url": "https://example.com/img.png",
                "stock": 10,
                "featured": True,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        assert r.json()["slug"] == slug

        # update
        ru = session.put(
            f"{API}/products/{pid}",
            json={"price": 12.5, "stock": 50},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert ru.status_code == 200
        assert ru.json()["price"] == 12.5
        assert ru.json()["stock"] == 50

        # verify via GET
        rg = session.get(f"{API}/products/{slug}")
        assert rg.status_code == 200
        assert rg.json()["price"] == 12.5

        # delete
        rd = session.delete(f"{API}/products/{pid}", headers={"Authorization": f"Bearer {admin_token}"})
        assert rd.status_code == 200

        # confirm gone
        rg2 = session.get(f"{API}/products/{slug}")
        assert rg2.status_code == 404


# ---------- Orders ----------
class TestOrders:
    @pytest.fixture(scope="class")
    def first_product(self, session):
        # pick a non-coming-soon product so orders are accepted
        r = session.get(f"{API}/products/red-muscadine-juice-12oz")
        if r.status_code == 200:
            return r.json()
        r = session.get(f"{API}/products")
        for p in r.json():
            if not p.get("coming_soon"):
                return p
        raise RuntimeError("no purchasable product found")

    def test_create_stripe_order(self, session, customer, first_product):
        payload = {
            "items": [{"product_id": first_product["id"], "quantity": 2}],
            "customer_name": "Test Buyer",
            "customer_email": customer["email"],
            "shipping_address": "123 Vine St, Charleston, SC",
            "payment_method": "stripe",
            "origin_url": BASE_URL,
        }
        r = session.post(
            f"{API}/orders", json=payload, headers={"Authorization": f"Bearer {customer['token']}"}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "order_id" in data
        assert "checkout_url" in data and data["checkout_url"].startswith("http")
        assert "session_id" in data
        assert data["payment_status"] == "pending"

        # verify order persisted
        ro = session.get(f"{API}/orders/{data['order_id']}")
        assert ro.status_code == 200
        assert ro.json()["stripe_session_id"] == data["session_id"]

    def test_create_zelle_order(self, session, customer, first_product):
        payload = {
            "items": [{"product_id": first_product["id"], "quantity": 1}],
            "customer_name": "Zelle Buyer",
            "customer_email": customer["email"],
            "shipping_address": "456 Scuppernong Ln",
            "payment_method": "zelle",
            "origin_url": BASE_URL,
        }
        r = session.post(
            f"{API}/orders", json=payload, headers={"Authorization": f"Bearer {customer['token']}"}
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["payment_status"] == "awaiting_verification"
        assert "payment_handle" in data and data["payment_handle"]
        assert "instructions" in data
        # persisted
        ro = session.get(f"{API}/orders/{data['order_id']}")
        assert ro.status_code == 200
        assert ro.json()["payment_method"] == "zelle"
        assert ro.json()["payment_status"] == "awaiting_verification"

    def test_my_orders(self, session, customer, first_product):
        # ensure at least one order
        session.post(
            f"{API}/orders",
            json={
                "items": [{"product_id": first_product["id"], "quantity": 1}],
                "customer_name": "Me",
                "customer_email": customer["email"],
                "shipping_address": "addr",
                "payment_method": "paypal",
                "origin_url": BASE_URL,
            },
            headers={"Authorization": f"Bearer {customer['token']}"},
        )
        r = session.get(f"{API}/orders/mine/all", headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 200
        orders = r.json()
        assert isinstance(orders, list) and len(orders) >= 1
        for o in orders:
            assert o["customer_email"] == customer["email"].lower()

    def test_admin_orders_requires_admin(self, session, customer):
        r = session.get(f"{API}/admin/orders", headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 403

    def test_admin_can_update_order(self, session, admin_token, customer, first_product):
        # create an order
        c = session.post(
            f"{API}/orders",
            json={
                "items": [{"product_id": first_product["id"], "quantity": 1}],
                "customer_name": "Upd",
                "customer_email": customer["email"],
                "shipping_address": "x",
                "payment_method": "venmo",
                "origin_url": BASE_URL,
            },
            headers={"Authorization": f"Bearer {customer['token']}"},
        )
        oid = c.json()["order_id"]
        r = session.put(
            f"{API}/admin/orders/{oid}",
            json={"payment_status": "paid", "order_status": "shipped"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert r.json()["payment_status"] == "paid"
        assert r.json()["order_status"] == "shipped"

    def test_mixed_juice_zelle_order(self, session, customer):
        # fetch muscadine juices and use the 25.4oz pair (price=18.0 each)
        r = session.get(f"{API}/products", params={"category": "Muscadine Juices"})
        juices = r.json()
        assert len(juices) == 4
        red = next(j for j in juices if j["slug"] == "red-muscadine-juice")
        white = next(j for j in juices if j["slug"] == "white-scuppernong-juice")
        payload = {
            "items": [
                {"product_id": red["id"], "quantity": 3},
                {"product_id": white["id"], "quantity": 3},
            ],
            "customer_name": "Mix Buyer",
            "customer_email": customer["email"],
            "shipping_address": "789 Mix St",
            "payment_method": "zelle",
            "origin_url": BASE_URL,
        }
        rc = session.post(
            f"{API}/orders", json=payload, headers={"Authorization": f"Bearer {customer['token']}"}
        )
        assert rc.status_code == 200, rc.text
        oid = rc.json()["order_id"]
        ro = session.get(f"{API}/orders/{oid}")
        assert ro.status_code == 200
        body = ro.json()
        assert len(body["items"]) == 2
        slugs_qty = {it["name"]: it["quantity"] for it in body["items"]}
        assert slugs_qty.get("Red Muscadine Juice") == 3
        assert slugs_qty.get("White Scuppernong Juice") == 3
        expected_subtotal = round((red["price"] + white["price"]) * 3, 2)
        assert body["subtotal"] == expected_subtotal
        assert body["payment_method"] == "zelle"
        assert body["payment_status"] == "awaiting_verification"


# ---------- Newsletter + Contact ----------
class TestNewsletterContact:
    def test_newsletter_subscribe_and_dedup(self, session):
        email = f"TEST_news_{uuid.uuid4().hex[:8]}@example.com"
        r1 = session.post(f"{API}/newsletter", json={"email": email})
        assert r1.status_code == 200
        assert r1.json()["message"] == "Subscribed!"
        r2 = session.post(f"{API}/newsletter", json={"email": email})
        assert r2.status_code == 200
        assert r2.json()["message"] == "Already subscribed"

    def test_contact_submit(self, session):
        r = session.post(
            f"{API}/contact",
            json={
                "name": "Tester",
                "email": "tester@example.com",
                "subject": "Hi",
                "message": "Hello there",
            },
        )
        assert r.status_code == 200

    def test_admin_lists_require_admin(self, session, customer, admin_token):
        rn = session.get(f"{API}/admin/newsletter", headers={"Authorization": f"Bearer {customer['token']}"})
        rc = session.get(f"{API}/admin/contact", headers={"Authorization": f"Bearer {customer['token']}"})
        assert rn.status_code == 403 and rc.status_code == 403

        rn2 = session.get(f"{API}/admin/newsletter", headers={"Authorization": f"Bearer {admin_token}"})
        rc2 = session.get(f"{API}/admin/contact", headers={"Authorization": f"Bearer {admin_token}"})
        assert rn2.status_code == 200 and rc2.status_code == 200
        assert isinstance(rn2.json(), list) and isinstance(rc2.json(), list)


# ---------- Welcome Letter (NEW iteration_3) ----------
class TestWelcomeLetter:
    def test_post_welcome_creates_entry(self, session):
        email = f"TEST_welcome_{uuid.uuid4().hex[:8]}@example.com"
        r1 = session.post(f"{API}/welcome", json={"first_name": "Aria", "email": email})
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body.get("ok")  # truthy bool from JSON
        assert "welcome" in body.get("message", "").lower() or "family" in body.get("message", "").lower()

    def test_post_welcome_idempotent_second_submit(self, session):
        email = f"TEST_welcome_dup_{uuid.uuid4().hex[:8]}@example.com"
        r1 = session.post(f"{API}/welcome", json={"first_name": "Lee", "email": email})
        assert r1.status_code == 200
        assert "already" not in r1.json().get("message", "").lower()
        r2 = session.post(f"{API}/welcome", json={"first_name": "Lee", "email": email})
        assert r2.status_code == 200
        assert "already" in r2.json().get("message", "").lower()

    def test_post_welcome_invalid_email_returns_422(self, session):
        r = session.post(f"{API}/welcome", json={"first_name": "X", "email": "not-an-email"})
        assert r.status_code == 422

    def test_post_welcome_first_name_optional(self, session):
        email = f"TEST_welcome_nofn_{uuid.uuid4().hex[:8]}@example.com"
        r = session.post(f"{API}/welcome", json={"email": email})
        assert r.status_code == 200, r.text
        assert r.json().get("ok")

    def test_admin_welcome_requires_auth(self, session):
        r = session.get(f"{API}/admin/welcome")
        assert r.status_code in (401, 403)

    def test_admin_welcome_forbidden_for_customer(self, session, customer):
        r = session.get(f"{API}/admin/welcome", headers={"Authorization": f"Bearer {customer['token']}"})
        assert r.status_code == 403

    def test_admin_welcome_returns_array_with_admin(self, session, admin_token):
        # seed one entry to guarantee non-empty
        seed_email = f"TEST_welcome_seed_{uuid.uuid4().hex[:8]}@example.com"
        rs = session.post(f"{API}/welcome", json={"first_name": "Seed", "email": seed_email})
        assert rs.status_code == 200
        r = session.get(f"{API}/admin/welcome", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # ensure no Mongo _id leaks
        for d in data:
            assert "_id" not in d
            assert "email" in d
            assert "created_at" in d
        # the seeded email should be present
        emails = {d["email"] for d in data}
        assert seed_email.lower() in emails


# ---------- Product count regression ----------
class TestProductsCount:
    def test_product_count_is_20(self, session):
        r = session.get(f"{API}/products")
        assert r.status_code == 200
        assert len(r.json()) == 20, f"expected 20 products, got {len(r.json())}"


# ---------- Gift Boxes & Coming-Soon ----------
class TestGiftBoxesAndComingSoon:
    def test_gift_boxes_filter_returns_two_coming_soon(self, session):
        r = session.get(f"{API}/products", params={"category": "Gift Boxes"})
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2, f"expected 2 gift box products, got {len(items)}"
        slugs = {p["slug"] for p in items}
        assert slugs == {"gift-3pack-pint", "gift-4pack-hot-sauce"}
        for p in items:
            assert p["coming_soon"], f"{p['slug']} should be coming_soon"
            assert p["category"] == "Gift Boxes"

    def test_order_with_coming_soon_returns_400(self, session, customer):
        # locate one of the coming-soon gift boxes by slug
        rp = session.get(f"{API}/products/gift-3pack-pint")
        assert rp.status_code == 200
        gift = rp.json()
        assert gift["coming_soon"]
        payload = {
            "items": [{"product_id": gift["id"], "quantity": 1}],
            "customer_name": "Blocked Buyer",
            "customer_email": customer["email"],
            "shipping_address": "1 Vine Way",
            "payment_method": "zelle",
            "origin_url": BASE_URL,
        }
        r = session.post(
            f"{API}/orders", json=payload, headers={"Authorization": f"Bearer {customer['token']}"}
        )
        assert r.status_code == 400, f"coming-soon order should be rejected, got {r.status_code} {r.text}"
        assert "coming soon" in r.text.lower()

    def test_order_with_coming_soon_mixed_returns_400(self, session, customer):
        # mixing a normal product with a coming-soon one should still 400
        gift = session.get(f"{API}/products/gift-4pack-hot-sauce").json()
        normal = session.get(f"{API}/products/red-muscadine-juice").json()
        payload = {
            "items": [
                {"product_id": normal["id"], "quantity": 1},
                {"product_id": gift["id"], "quantity": 1},
            ],
            "customer_name": "Mixed Buyer",
            "customer_email": customer["email"],
            "shipping_address": "1 Vine Way",
            "payment_method": "stripe",
            "origin_url": BASE_URL,
        }
        r = session.post(
            f"{API}/orders", json=payload, headers={"Authorization": f"Bearer {customer['token']}"}
        )
        assert r.status_code == 400
