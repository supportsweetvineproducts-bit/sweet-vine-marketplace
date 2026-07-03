"""
Update the 4 backbone juice products' descriptions with the rich label info
(antioxidants, NCSFA award badge mention, ingredients, pasteurization, etc.)
"""
import asyncio, os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

DESCRIPTIONS = {
    "red-muscadine-juice": (
        "Our award-winning 100% Red Muscadine Juice — cold-pressed, not from "
        "concentrate, and bottled fresh from native Southern muscadine grapes. "
        "NCSFA 2024 \"Best In Taste\" Winner. Nature's #1 source of antioxidants — "
        "with an ORAC value of ~6,800 per 100 g, muscadines deliver nearly 10× "
        "the antioxidant power of common red grapes (739), more than açaí "
        "(4,500), pomegranate (3,300), and blueberries (2,400). 25.4 fl oz "
        "(750 ml) · 140 calories per 8 fl oz serving · 33 g natural sugars · "
        "0 g added sugar · 244 mg potassium. Ingredients: 100% Muscadine Juice, "
        "Sulfites. No alcohol, no additives, no preservatives. Pasteurized — "
        "refrigerate after opening. Produced & bottled for Sweet Vine Products, "
        "Stanfield, NC."
    ),
    "white-scuppernong-juice": (
        "Bright, honey-toned 100% White Scuppernong Juice — the Southern bronze "
        "muscadine, cold-pressed and bottled fresh, not from concentrate. "
        "Nature's #1 source of antioxidants — with an ORAC value of ~6,800 per "
        "100 g, scuppernongs deliver nearly 10× the antioxidant power of common "
        "red grapes, more than açaí, pomegranate, and blueberries combined. "
        "25.4 fl oz (750 ml) · 140 calories per 8 fl oz serving · 33 g natural "
        "sugars · 0 g added sugar · 244 mg potassium. Ingredients: 100% "
        "Muscadine Juice, Sulfites. No alcohol, no additives, no preservatives. "
        "Pasteurized — refrigerate after opening. Produced & bottled for Sweet "
        "Vine Products, Stanfield, NC."
    ),
    "red-muscadine-12oz-case": (
        "A case of 12 single-serve 12 fl oz bottles of our award-winning 100% "
        "Red Muscadine Juice — NCSFA 2024 \"Best In Taste\" Winner. Cold-pressed, "
        "not from concentrate, bottled fresh from native Southern muscadine "
        "grapes. Nature's #1 source of antioxidants — with an ORAC value of "
        "~6,800 per 100 g, muscadines deliver nearly 10× the antioxidant power "
        "of common red grapes. Each bottle: 100 calories per serving · 0 g "
        "added sugar · 100% Muscadine Juice, Sulfites. No alcohol, no "
        "additives, no preservatives. Pasteurized — refrigerate after opening. "
        "Perfect for sharing, gifting, or stocking the fridge. Free shipping on "
        "every case. Produced & bottled for Sweet Vine Products, Stanfield, NC."
    ),
    "white-scuppernong-12oz-case": (
        "A case of 12 single-serve 12 fl oz bottles of bright, honey-toned 100% "
        "White Scuppernong Juice — the Southern bronze muscadine, cold-pressed "
        "and bottled fresh, not from concentrate. Nature's #1 source of "
        "antioxidants — with an ORAC value of ~6,800 per 100 g, scuppernongs "
        "deliver nearly 10× the antioxidant power of common red grapes. Each "
        "bottle: 100 calories per serving · 0 g added sugar · 100% Muscadine "
        "Juice, Sulfites. No alcohol, no additives, no preservatives. "
        "Pasteurized — refrigerate after opening. Perfect for sharing, "
        "gifting, or stocking the fridge. Free shipping on every case. "
        "Produced & bottled for Sweet Vine Products, Stanfield, NC."
    ),
}


async def main():
    client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = client[os.getenv("DB_NAME")]
    for slug, desc in DESCRIPTIONS.items():
        res = await db.products.update_one({"slug": slug}, {"$set": {"description": desc}})
        print(f"{slug}: matched={res.matched_count} modified={res.modified_count}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
