"""Check the real Sarvam integration with your key.

    cd api && .venv/bin/python scripts/smoke_sarvam.py [path/to/audio.wav]

Step 1 always runs: journey extraction from a Hinglish sentence.
Step 2 runs only if you pass an audio file: speech-to-text, then extraction.
On failure it prints Sarvam's own error body: usually a wrong model name
(set SARVAM_STT_MODEL / SARVAM_CHAT_MODEL in api/.env).
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import sarvam  # noqa: E402
from journey import build_journey  # noqa: E402

SENTENCE = "Mujhe 27 November ko Bangalore se Hyderabad jaana hai. Train nahi mili toh shared cab dekhna."


async def main() -> int:
    print(f"STT model={config.SARVAM_STT_MODEL!r}  chat model={config.SARVAM_CHAT_MODEL!r}")
    text = SENTENCE

    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        print(f"\n[1/2] speech-to-text on {path.name}")
        suffix = path.suffix.lstrip(".").lower() or "wav"
        t = await sarvam.transcribe(path.read_bytes(), path.name, f"audio/{suffix}")
        print(f"  transcript:    {t.text!r}\n  language_code: {t.language_code}")
        text = t.text or SENTENCE
    else:
        print("\n[1/2] speech-to-text skipped (pass an audio file to test it)")

    print(f"\n[2/2] extraction from: {text!r}")
    extraction = await sarvam.extract_journey(text)
    print("  raw extraction:", json.dumps(extraction, ensure_ascii=False))
    print("  validated:     ", build_journey(extraction).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except sarvam.SarvamError as exc:
        print(f"\nFAILED: {exc}")
        sys.exit(1)
