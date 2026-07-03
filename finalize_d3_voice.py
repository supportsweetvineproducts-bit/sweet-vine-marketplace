"""Finalize D3 as a permanent voice + re-render with corrected pronunciation.

Fixes:
- Remove the "mmm…" filler
- Force "muscadine"/"muscadines" to pronounce as MUSS-kuh-DYNE (rhymes with vine)
  using ElevenLabs phoneme tags (IPA).
"""
import os, json
from pathlib import Path
from dotenv import load_dotenv
from elevenlabs import ElevenLabs, VoiceSettings

load_dotenv("/app/backend/.env")
OUT_DIR = Path("/app/frontend/public/audio")
META = OUT_DIR / "voice-design-previews.json"

# Hardcode D3 from prior run (gvid)
D3_GVID = "uWHY739blDJTMC5mORjD"
D3_DESCRIPTION = (
    "A mature Black Southern American woman in her late 40s. "
    "Deep, warm, soulful, with the rich gospel-singer richness of Aretha "
    "Franklin and the wise, measured cadence of Oprah Winfrey. Slow, intimate "
    "delivery with breath pauses. Velvety lower register, intimate and "
    "romantic. Distinctly African-American Southern vernacular pacing. "
    "Strong, but never harsh."
)

# Script with phoneme tags for correct pronunciation of muscadine
# IPA: /ˈmʌskədaɪn/ (MUSS-kə-DYNE, rhymes with "vine")
# Removed "mmm…" filler per user request.
SCRIPT = (
    'From the Northern Rivers of North Carolina… '
    "to Alabama's sweet artesian springs… "
    'Sweet Vine Products. '
    'One hundred percent <phoneme alphabet="ipa" ph="ˈmʌskədaɪn">muscadine</phoneme> juice — '
    "nature's number one source of antioxidants. "
    'No alcohol. No sugar added. No substitutes. '
    'A healthy body… from the vine.'
)


def main():
    client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

    # 1) Promote the preview to a permanent voice
    print(f"Saving D3 preview {D3_GVID} as 'Sweet Vine — Signature Voice'...")
    voice = client.text_to_voice.create(
        voice_name="Sweet Vine — Signature Voice",
        voice_description=D3_DESCRIPTION,
        generated_voice_id=D3_GVID,
    )
    voice_id = voice.voice_id
    print(f"  permanent voice_id = {voice_id}")

    # 2) Render the corrected brand-story voiceover
    print("\nRendering corrected hero voiceover with phoneme fix...")
    settings = VoiceSettings(
        stability=0.4,
        similarity_boost=0.9,
        style=0.5,
        use_speaker_boost=True,
    )
    chunks = client.text_to_speech.convert(
        text=SCRIPT,
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        voice_settings=settings,
        output_format="mp3_44100_128",
    )
    data = b"".join(chunks)
    primary = OUT_DIR / "hero-voiceover.mp3"
    primary.write_bytes(data)
    print(f"  saved {primary} ({len(data)} bytes)")

    # Also save labeled file for the preview page
    labeled = OUT_DIR / "hero-voiceover-d3-final.mp3"
    labeled.write_bytes(data)

    # Persist voice_id for future re-renders
    meta_file = Path("/app/backend/.signature_voice.json")
    meta_file.write_text(json.dumps({
        "voice_id": voice_id,
        "name": "Sweet Vine — Signature Voice",
        "model": "eleven_multilingual_v2",
        "description": D3_DESCRIPTION,
    }, indent=2))
    print(f"\nSaved signature voice metadata: {meta_file}")
    print("\nDone. Refresh the homepage and 'Watch the story' to hear the new D3 voice.")


if __name__ == "__main__":
    main()
