"""
Regenerate vineyard-scenic backgrounds for the 4 backbone juice products:
- red-muscadine-juice (25oz single)
- white-scuppernong-juice (25oz single)
- red-muscadine-12oz-case
- white-scuppernong-12oz-case

Uses Gemini Nano Banana, takes the AI-cleaned product photo as input, and
replaces the cream backdrop with a vineyard scene at golden hour: rolling
hills, hanging grape clusters, wooden table, soft sunset light.
"""
from __future__ import annotations
import asyncio
import base64
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # noqa: E402

PUBLIC_DIR = Path("/app/frontend/public/products")
MODEL = "gemini-3.1-flash-image-preview"

TARGETS = [
    "red-muscadine-juice",
    "white-scuppernong-juice",
    "red-muscadine-12oz-case",
    "white-scuppernong-12oz-case",
]

PROMPT = (
    "Replace ONLY the background of this product photo with a warm golden-hour "
    "vineyard scene: rolling vineyard hills with rows of grape vines stretching "
    "to the horizon, a rustic wooden table beneath the product, a soft cluster "
    "of muscadine grapes resting on the table as an accent, gentle bokeh "
    "background, warm sunset sidelight from upper-left, no people, no text, no "
    "watermarks. Keep the product (bottles, cases, jars, labels, caps, fill "
    "levels, label artwork, badges, and ALL text on the labels) EXACTLY as it "
    "appears — do not alter the product itself, do not redesign the label, do "
    "not change the cap or any colors of the product. The product must remain "
    "the sharp, in-focus hero. Premium e-commerce hero shot, square aspect, "
    "high resolution, natural shadow grounding the product."
)


async def fetch_image(image_url: str) -> bytes:
    if image_url.startswith("/products/"):
        local = PUBLIC_DIR / Path(image_url).name
        if local.exists():
            return local.read_bytes()
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        return r.content


async def regenerate(slug: str, image_url: str) -> str:
    api_key = os.getenv("EMERGENT_LLM_KEY")
    print(f"[{slug}] source: {image_url}")
    src_bytes = await fetch_image(image_url)
    print(f"[{slug}] {len(src_bytes)} bytes -> Nano Banana")
    img_b64 = base64.b64encode(src_bytes).decode("utf-8")

    chat = LlmChat(
        api_key=api_key,
        session_id=f"vineyard-{slug}-{uuid.uuid4().hex[:8]}",
        system_message="You are a professional product photography retoucher.",
    )
    chat.with_model("gemini", MODEL).with_params(modalities=["image", "text"])
    msg = UserMessage(text=PROMPT, file_contents=[ImageContent(img_b64)])
    text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise RuntimeError(f"No image returned. Text: {text[:200]}")
    img = images[0]
    out_bytes = base64.b64decode(img["data"])
    mime = img.get("mime_type", "image/png")
    ext = ".png" if "png" in mime else ".jpg"
    out_name = f"vineyard-{slug}{ext}"
    out_path = PUBLIC_DIR / out_name
    out_path.write_bytes(out_bytes)
    print(f"[{slug}] saved: {out_path} ({len(out_bytes)} bytes)")
    return f"/products/{out_name}"


async def main():
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]

    failed = []
    for slug in TARGETS:
        prod = await db.products.find_one({"slug": slug})
        if not prod:
            print(f"[{slug}] NOT FOUND")
            failed.append(slug)
            continue
        try:
            new_url = await regenerate(slug, prod["image_url"])
            res = await db.products.update_one({"slug": slug}, {"$set": {"image_url": new_url}})
            print(f"[{slug}] DB updated: matched={res.matched_count} modified={res.modified_count}")
            await asyncio.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            print(f"[{slug}] FAILED: {e}")
            failed.append(slug)

    client.close()
    print("\n=== DONE ===")
    if failed:
        print(f"Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
