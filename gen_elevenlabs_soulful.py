"""Generate 3 more soulful voice samples using known pre-made voice IDs with
maxed-out emotional settings (low stability, high style).

Voices tried:
- Charlotte (XB0fDUnXU5powFXDhCwa) - sultry warm, retuned for soul
- Matilda  (XrExE9yKIg1WjnnlVkGX) - mature warm female
- Lily     (pFZP5JQG7iQjIQuC4Bku) - soft warm female
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from elevenlabs import ElevenLabs, VoiceSettings

load_dotenv("/app/backend/.env")
OUT_DIR = Path("/app/frontend/public/audio")

SCRIPT = (
    "From the Northern Rivers of North Carolina, mmm… "
    "to Alabama's sweet artesian springs… "
    "Sweet Vine Products. "
    "One hundred percent muscadine — "
    "nature's number one source of antioxidants. "
    "No alcohol. No sugar added. No substitutes. "
    "Just a healthy body… from the vine."
)

# Maxed-out soulful settings — emotional, drawn-out, stylistic
SETTINGS = VoiceSettings(
    stability=0.22,         # very expressive, allows breath/inflection
    similarity_boost=0.92,  # stay close to the voice's natural timbre
    style=0.78,             # heavy stylistic emphasis (drawl, drama)
    use_speaker_boost=True,
)

# Pre-made voice IDs (no voices_read permission needed when you know the id)
VOICES = [
    ("charlotte-soul", "XB0fDUnXU5powFXDhCwa"),
    ("matilda",        "XrExE9yKIg1WjnnlVkGX"),
    ("lily",           "pFZP5JQG7iQjIQuC4Bku"),
]


def main():
    client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    for name, vid in VOICES:
        print(f"Generating {name} ({vid})...")
        chunks = client.text_to_speech.convert(
            text=SCRIPT,
            voice_id=vid,
            model_id="eleven_multilingual_v2",
            voice_settings=SETTINGS,
            output_format="mp3_44100_128",
        )
        data = b"".join(chunks)
        out = OUT_DIR / f"hero-voiceover-{name}.mp3"
        out.write_bytes(data)
        print(f"  saved {out.name}  ({len(data)} bytes)")


if __name__ == "__main__":
    main()
