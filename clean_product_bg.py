"""
One-off batch script: Use Gemini Nano Banana to regenerate ONLY the background
of each product photo to a clean professional studio look while preserving the
bottle/jar/label EXACTLY as-is.

Usage:
    python3 /app/backend/scripts/clean_product_bg.py --slug red-muscadine-juice
    python3 /app/backend/scripts/clean_product_bg.py --all
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Make backend importable not needed; we use raw libs
sys.path.insert(0, "/app/backend")

load_dotenv("/app/backend/.env")

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # noqa: E402

PUBLIC_DIR = Path("/app/frontend/public/products")
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "gemini-3.1-flash-image-preview"

PROMPT_BY_CATEGORY = {
    "default": (
        "Replace ONLY the background of this product photo with a clean, "
        "premium e-commerce studio backdrop: soft warm cream gradient "
        "(#FBF7F1 to #F1E9DA) with a subtle natural drop-shadow under the "
        "product to ground it. Keep the product (bottle, jar, label, cap, "
        "fill level, glass reflections, and all text/artwork on the label) "
        "EXACTLY as-is — do not alter the product itself, do not redesign "
        "the label, do not change the cap or color. Center the product, "
        "remove any clutter, hands, props, or distractions. Result should "
        "look like a professional Amazon/Shopify hero shot. Square aspect, "
        "high resolution, soft diffused lighting from upper-left."
    ),
}


async def fetch_image(image_url: str) -> bytes:
    """Resolve and download a product image to raw bytes."""
    if image_url.startswith("/products/"):
        local = PUBLIC_DIR / Path(image_url).name
        if local.exists():
            return local.read_bytes()
    # Otherwise treat as full URL
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        return r.content


async def clean_one(slug: str, image_url: str) -> str:
    """Run Nano Banana on a single product; save output, return new /products/... path."""
    api_key = os.getenv("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY missing from /app/backend/.env")

    print(f"[{slug}] downloading source: {image_url[:80]}")
    src_bytes = await fetch_image(image_url)
    print(f"[{slug}] source size: {len(src_bytes)} bytes")
    img_b64 = base64.b64encode(src_bytes).decode("utf-8")

    chat = LlmChat(
        api_key=api_key,
        session_id=f"clean-bg-{slug}-{uuid.uuid4().hex[:8]}",
        system_message="You are a professional product photography retoucher.",
    )
    chat.with_model("gemini", MODEL).with_params(modalities=["image", "text"])

    prompt = PROMPT_BY_CATEGORY["default"]
    msg = UserMessage(text=prompt, file_contents=[ImageContent(img_b64)])

    print(f"[{slug}] calling Nano Banana ({MODEL})...")
    text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise RuntimeError(f"No image returned. Text: {text[:200]}")

    img = images[0]
    out_bytes = base64.b64decode(img["data"])
    mime = img.get("mime_type", "image/png")
    ext = ".png" if "png" in mime else ".jpg"
    out_name = f"clean-{slug}{ext}"
    out_path = PUBLIC_DIR / out_name
    out_path.write_bytes(out_bytes)
    print(f"[{slug}] saved: {out_path} ({len(out_bytes)} bytes, {mime})")
    return f"/products/{out_name}"


async def update_db(slug: str, new_url: str):
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]
    res = await db.products.update_one(
        {"slug": slug},
        {"$set": {"image_url": new_url}},
    )
    print(f"[{slug}] DB updated: matched={res.matched_count} modified={res.modified_count}")
    client.close()


async def run_one(slug: str):
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]
    prod = await db.products.find_one({"slug": slug})
    client.close()
    if not prod:
        raise SystemExit(f"Product not found: {slug}")
    new_url = await clean_one(slug, prod["image_url"])
    await update_db(slug, new_url)


async def run_all():
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]
    products = await db.products.find({}, {"slug": 1, "image_url": 1}).to_list(length=None)
    client.close()

    print(f"Processing {len(products)} products...\n")
    failed = []
    for p in products:
        slug = p["slug"]
        # Skip already-cleaned products
        if (p.get("image_url") or "").startswith("/products/clean-"):
            print(f"[{slug}] already cleaned — skipping")
            continue
        try:
            new_url = await clean_one(slug, p["image_url"])
            await update_db(slug, new_url)
            await asyncio.sleep(1.0)  # gentle pacing
        except Exception as e:  # noqa: BLE001
            print(f"[{slug}] FAILED: {e}")
            failed.append((slug, str(e)))
    print("\n=== DONE ===")
    if failed:
        print(f"Failed: {len(failed)}")
        for s, e in failed:
            print(f"  - {s}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", help="Process one product by slug")
    parser.add_argument("--all", action="store_true", help="Process every product")
    args = parser.parse_args()

    if args.slug:
        asyncio.run(run_one(args.slug))
    elif args.all:
        asyncio.run(run_all())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
