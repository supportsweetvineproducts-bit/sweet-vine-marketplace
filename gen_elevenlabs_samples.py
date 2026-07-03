"""Generate 3 ElevenLabs voice samples for the Sweet Vine hero voiceover.

Saves to /app/frontend/public/audio/hero-voiceover-{voice}.mp3 so the user
can preview each in the browser, then we lock in their pick as the primary.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from elevenlabs import ElevenLabs, VoiceSettings

load_dotenv("/app/backend/.env")

OUT_DIR = Path("/app/frontend/public/audio")
OUT_DIR.mkdir(parents=True, exist_ok=True)

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

# ElevenLabs default library voice IDs (warm, mature female voices)
VOICES = [
    ("charlotte", "XB0fDUnXU5powFXDhCwa"),  # sultry, warm
    ("jessica",   "cgSgspJ2msm6clMCkdW9"),  # rich, smooth
    ("sarah",     "EXAVITQu4vr4xnSDxMaL"),  # calm, deep
]

# Settings tuned for a soul-singer richness:
# - stability 0.45 = expressive (not robotic), allows emotional variation
# - similarity 0.85 = keep the chosen voice's natural timbre
# - style 0.35 = moderate stylistic emphasis (slight drawl/drama)
# - speaker_boost on = clarity & warmth
SETTINGS = VoiceSettings(
    stability=0.45,
    similarity_boost=0.85,
    style=0.35,
    use_speaker_boost=True,
)


def main():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY missing from /app/backend/.env")
    client = ElevenLabs(api_key=api_key)

    for name, vid in VOICES:
        print(f"Generating {name} ({vid}) ...")
        audio_iter = client.text_to_speech.convert(
            text=SCRIPT,
            voice_id=vid,
            model_id="eleven_multilingual_v2",
            voice_settings=SETTINGS,
            output_format="mp3_44100_128",
        )
        data = b"".join(audio_iter)
        out = OUT_DIR / f"hero-voiceover-{name}.mp3"
        out.write_bytes(data)
        print(f"  saved {out.name}  ({len(data)} bytes)")


if __name__ == "__main__":
    main()
