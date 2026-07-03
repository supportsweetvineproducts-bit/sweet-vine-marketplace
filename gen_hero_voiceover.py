"""Generate the brand-story hero voiceover with OpenAI TTS coral (warmest voice).

Run: python3 /app/backend/scripts/gen_hero_voiceover.py
"""
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

from emergentintegrations.llm.openai import OpenAITextToSpeech  # noqa: E402

OUT_PATH = Path("/app/frontend/public/audio/hero-voiceover.mp3")

# ~15 seconds at speed=0.95. Soft Southern phrasing — gentle pauses for breath.
SCRIPT = (
    "From the Northern Rivers of North Carolina, "
    "to Alabama's artesian springs… "
    "Sweet Vine Products. "
    "One hundred percent muscadine juice — "
    "nature's number one source of antioxidants. "
    "No alcohol. No sugar added. No substitutes. "
    "A healthy body… from the vine."
)


async def main():
    api_key = os.getenv("EMERGENT_LLM_KEY")
    if not api_key:
        raise SystemExit("EMERGENT_LLM_KEY missing")
    tts = OpenAITextToSpeech(api_key=api_key)
    print(f"Generating voiceover ({len(SCRIPT)} chars)...")
    audio_bytes = await tts.generate_speech(
        text=SCRIPT,
        model="tts-1-hd",
        voice="coral",   # warm, friendly
        response_format="mp3",
        speed=0.95,       # slightly slower for a Southern cadence
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(audio_bytes)
    print(f"Saved: {OUT_PATH} ({len(audio_bytes)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
