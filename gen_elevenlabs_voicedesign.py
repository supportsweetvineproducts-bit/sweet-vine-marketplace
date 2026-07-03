"""ElevenLabs Voice Design — synthesize a voice from a description.

Step 1: Generate 3 voice previews from a description (Black Southern soulful)
Step 2: For each preview, render the Sweet Vine brand story script
Step 3: Save audio + preview_id so we can finalize the user's pick later
"""
import os, json
from pathlib import Path
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

load_dotenv("/app/backend/.env")

OUT_DIR = Path("/app/frontend/public/audio")
OUT_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_META = OUT_DIR / "voice-design-previews.json"

# Voice description — describe the voice we want
DESCRIPTION = (
    "A mature Black Southern American woman in her late 40s. "
    "Deep, warm, soulful, with the rich gospel-singer richness of Aretha "
    "Franklin and the wise, measured cadence of Oprah Winfrey. Slow, intimate "
    "delivery with breath pauses. Velvety lower register, intimate and "
    "romantic, like a late-night radio host who has lived. Distinctly "
    "African-American Southern vernacular pacing — not generic American, "
    "not British, not Caribbean. Strong, but never harsh. The kind of voice "
    "that makes you lean in."
)

# Sample text the preview will speak (used to evaluate the voice)
SAMPLE_TEXT = (
    "From the Northern Rivers of North Carolina, mmm… to Alabama's sweet "
    "artesian springs… Sweet Vine Products. One hundred percent muscadine — "
    "nature's number one source of antioxidants. No alcohol. No sugar added. "
    "No substitutes. Just a healthy body… from the vine."
)


def main():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY missing")
    client = ElevenLabs(api_key=api_key)

    print("Calling Voice Design create_previews...")
    print(f"  description ({len(DESCRIPTION)} chars): {DESCRIPTION[:100]}...")
    print(f"  sample text  ({len(SAMPLE_TEXT)} chars)")
    print()

    res = client.text_to_voice.design(
        voice_description=DESCRIPTION,
        text=SAMPLE_TEXT,
        model_id="eleven_multilingual_ttv_v2",
        output_format="mp3_44100_128",
    )

    previews = res.previews if hasattr(res, "previews") else res
    print(f"Got {len(previews)} previews")

    meta = []
    import base64
    for i, p in enumerate(previews[:3], start=1):
        # Each preview has 'generated_voice_id' and 'audio_base_64' (or similar)
        gvid = getattr(p, "generated_voice_id", None) or getattr(p, "voice_id", None)
        b64 = getattr(p, "audio_base_64", None) or getattr(p, "audio", None)
        if not b64:
            # fallback: dump attributes
            print(f"  preview {i}: keys = {[k for k in dir(p) if not k.startswith('_')]}")
            continue
        audio = base64.b64decode(b64)
        out = OUT_DIR / f"hero-voiceover-design-{i}.mp3"
        out.write_bytes(audio)
        print(f"  preview {i}: gvid={gvid}  -> {out.name}  ({len(audio)} bytes)")
        meta.append({"index": i, "generated_voice_id": gvid, "file": out.name})

    PREVIEW_META.write_text(json.dumps(meta, indent=2))
    print(f"\nSaved metadata: {PREVIEW_META}")


if __name__ == "__main__":
    main()
