#!/usr/bin/env python3
"""
Generates short narration samples across several edge-tts voices, all
reading the same verse, so a human can compare and pick one — run this on
a machine with real internet access (GitHub Actions), not the sandbox.

Usage:
    python voice_samples.py --outdir /tmp/voice_samples
"""
import argparse
import os

from narrate import narrate, build_narration_script
from photo_card import load_verses

# A spread of natural-sounding neural voices, mixing warmth/register, worth
# comparing for a calm devotional/faith-content read. All are free via
# edge-tts (Microsoft Edge's TTS service).
CANDIDATE_VOICES = [
    "en-US-JennyNeural",       # warm female, general-purpose (current default)
    "en-US-AriaNeural",        # expressive female
    "en-US-AvaNeural",         # newer, natural conversational female
    "en-US-EmmaNeural",        # newer, warm female
    "en-US-AndrewNeural",      # newer, natural conversational male
    "en-US-ChristopherNeural", # deeper, calm male
    "en-GB-SoniaNeural",       # British female
    "en-GB-RyanNeural",        # British male
]

SAMPLE_REFERENCE = "John 3:16"
RATE = "-10%"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", default="/tmp/voice_samples")
    p.add_argument("--rate", default=RATE)
    p.add_argument("--reference", default=SAMPLE_REFERENCE)
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    verses = load_verses()
    by_ref = {v["reference"]: v for v in verses}
    verse = by_ref[args.reference]
    script = build_narration_script(verse)
    print(f"Sample text: {script}")

    for voice in CANDIDATE_VOICES:
        out_path = os.path.join(args.outdir, f"{voice}.mp3")
        try:
            narrate(script, out_path, voice=voice, rate=args.rate)
            print(f"OK   {voice} -> {out_path}")
        except Exception as e:
            print(f"FAIL {voice}: {e}")


if __name__ == "__main__":
    main()
