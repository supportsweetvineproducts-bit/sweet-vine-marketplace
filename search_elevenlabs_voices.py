"""Search ElevenLabs voice library for soulful Black Southern female voices."""
import os, json
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

load_dotenv("/app/backend/.env")
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Fetch shared voice library (curated community + featured voices)
keywords = ["soulful", "deep", "rich", "warm", "mature", "soul", "gospel"]
print("=== Shared Library — featured female voices ===\n")
try:
    # search shared library; gender female, category=high_quality, language=en
    res = client.voices.get_shared(
        gender="female",
        language="en",
        page_size=100,
    )
    seen = 0
    for v in res.voices:
        desc = (v.description or "").lower()
        labels = " ".join((v.labels or {}).values()).lower() if v.labels else ""
        cat = " ".join([
            (v.category or "").lower(),
            (v.use_case or "").lower() if hasattr(v, "use_case") else "",
        ])
        haystack = f"{desc} {labels} {cat} {v.name.lower()}"
        if any(k in haystack for k in keywords):
            print(f"--- {v.name} ({v.voice_id}) ---")
            print(f"  desc:     {(v.description or '')[:120]}")
            print(f"  labels:   {v.labels}")
            print(f"  category: {v.category}")
            if hasattr(v, "accent"):
                print(f"  accent:   {getattr(v, 'accent', None)}")
            if hasattr(v, "age"):
                print(f"  age:      {getattr(v, 'age', None)}")
            print()
            seen += 1
            if seen >= 25:
                break
    print(f"Total matches: {seen}")
except Exception as e:
    print(f"Shared library error: {e}")

print("\n=== Pre-made library voices ===\n")
voices = client.voices.get_all().voices
for v in voices:
    desc = (v.description or "").lower() if v.description else ""
    labels = json.dumps(v.labels or {})
    haystack = f"{desc} {labels.lower()} {v.name.lower()}"
    if any(k in haystack for k in keywords) or "african" in haystack or "southern" in haystack:
        print(f"--- {v.name} ({v.voice_id}) ---")
        print(f"  desc:   {(v.description or '')[:120]}")
        print(f"  labels: {v.labels}")
        print()
