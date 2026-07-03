"""Generate 3 alternative hero voiceovers for A/B preview:
   - sage   @ 0.88 speed (wise, measured)
   - fable  @ 0.92 speed (expressive, storytelling)
   - coral  @ 0.85 speed (warm + slower, more romantic)

   Saves each as /app/frontend/public/audio/hero-voiceover-{voice}.mp3
   so the user can preview them, then we lock in the chosen one as the
   primary hero-voiceover.mp3.
"""
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from emergentintegrations.llm.openai import OpenAITextToSpeech  # noqa: E402

OUT_DIR = Path("/app/frontend/public/audio")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# More lyrical phrasing — ellipses force gentle breath pauses for a soul-singer cadence
SCRIPT = (
    "From the Northern Rivers of North Carolina… "
    "to Alabama's sweet artesian springs… "
    "Sweet Vine Products. "
    "One hundred percent muscadine juice — "
    "nature's number one source of antioxidants. "
    "No alcohol. No sugar added. No substitutes. "
    "A healthy body… "
    "from the vine."
)

VARIANTS = [
    ("sage", 0.88),
    ("fable", 0.92),
    ("coral", 0.85),
]


async def main():
    tts = OpenAITextToSpeech(api_key=os.getenv("EMERGENT_LLM_KEY"))
    for voice, speed in VARIANTS:
        print(f"Generating {voice} @ {speed}x...")
        audio = await tts.generate_speech(
            text=SCRIPT,
            model="tts-1-hd",
            voice=voice,
            response_format="mp3",
            speed=speed,
        )
        out = OUT_DIR / f"hero-voiceover-{voice}.mp3"
        out.write_bytes(audio)
        print(f"  saved {out.name}  ({len(audio)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
