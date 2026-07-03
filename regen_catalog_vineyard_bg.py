"""
Apply the vineyard-scenic prompt to every product that's still on the clean
cream backdrop (excluding the 2 illustrated gift boxes). Unifies the whole
catalog visually.
"""
import asyncio, base64, os, sys, uuid
from pathlib import Path
import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # noqa: E402

PUBLIC_DIR = Path("/app/frontend/public/products")
MODEL = "gemini-3.1-flash-image-preview"

# Gift boxes are illustrated cards — skip
SKIP = {"gift-3pack-pint", "gift-4pack-hot-sauce"}

PROMPT = (
    "Replace ONLY the background of this product photo with a warm golden-hour "
    "vineyard scene: rolling vineyard hills with rows of grape vines stretching "
    "to the horizon, a rustic wooden table beneath the product, a soft cluster "
    "of muscadine grapes resting on the table as an accent, gentle bokeh "
    "background, warm sunset sidelight from upper-left, no people, no text, no "
    "watermarks. Keep the product (bottles, jars, caps, lids, labels, fill "
    "levels, label artwork, and ALL text on the labels) EXACTLY as it appears "
    "— do not alter the product itself, do not redesign the label, do not "
    "change the cap or any colors of the product. The product must remain the "
    "sharp, in-focus hero. Premium e-commerce hero shot, square aspect, high "
    "resolution, natural shadow grounding the product."
)


async def fetch(url: str) -> bytes:
    if url.startswith("/products/"):
        return (PUBLIC_DIR / Path(url).name).read_bytes()
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(url); r.raise_for_status(); return r.content


async def regen(slug: str, url: str) -> str:
    src = await fetch(url)
    print(f"[{slug}] {len(src)}B -> NB")
    chat = LlmChat(
        api_key=os.getenv("EMERGENT_LLM_KEY"),
        session_id=f"vy-{slug}-{uuid.uuid4().hex[:8]}",
        system_message="You are a professional product photography retoucher.",
    )
    chat.with_model("gemini", MODEL).with_params(modalities=["image", "text"])
    msg = UserMessage(text=PROMPT, file_contents=[ImageContent(base64.b64encode(src).decode())])
    text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise RuntimeError(f"no image: {text[:160]}")
    img = images[0]
    out = base64.b64decode(img["data"])
    ext = ".png" if "png" in img.get("mime_type", "") else ".jpg"
    name = f"vineyard-{slug}{ext}"
    (PUBLIC_DIR / name).write_bytes(out)
    print(f"[{slug}] saved {name} ({len(out)}B)")
    return f"/products/{name}"


async def main():
    cl = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = cl[os.getenv("DB_NAME")]
    prods = await db.products.find({}, {"slug": 1, "image_url": 1}).to_list(length=None)
    failed = []
    for p in prods:
        slug = p["slug"]
        url = p.get("image_url") or ""
        if slug in SKIP:
            print(f"[{slug}] SKIP (gift box)"); continue
        if not url.startswith("/products/clean-"):
            print(f"[{slug}] SKIP (not clean- or already vineyard'd)"); continue
        try:
            new_url = await regen(slug, url)
            res = await db.products.update_one({"slug": slug}, {"$set": {"image_url": new_url}})
            print(f"[{slug}] DB matched={res.matched_count} modified={res.modified_count}")
            await asyncio.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            print(f"[{slug}] FAILED: {e}"); failed.append((slug, str(e)))
    cl.close()
    print("\n=== DONE ===")
    if failed:
        for s, e in failed: print(f"  - {s}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
