#!/usr/bin/env python3
"""
Generates spoken narration audio for a verse using edge-tts (Microsoft's
free neural TTS service). This MUST run somewhere with normal internet
access — speech.platform.bing.com is blocked from the Claude sandbox dev
environment, but GitHub Actions runners reach it fine.

Usage (standalone):
    python narrate.py --text "For God so loved the world..." --output narration.mp3

Usage (from post.py):
    from narrate import narrate, build_narration_script
    script = build_narration_script(verse)
    narrate(script, "/tmp/narration.mp3")
"""
import argparse
import asyncio

import edge_tts

# Warm, clear female voice — reads well for devotional/faith content.
# Alternatives: en-US-AriaNeural, en-US-EmmaNeural (female); en-US-GuyNeural,
# en-US-ChristopherNeural (male).
DEFAULT_VOICE = "en-US-JennyNeural"
DEFAULT_RATE = "-10%"  # slightly slower than default for a reverent, unhurried pace


def build_narration_script(verse):
    """Builds the text that gets spoken: verse text, then the reference,
    then the reflection line (if present), each as its own sentence so
    edge-tts adds natural pauses between them."""
    parts = [verse["text"].strip().rstrip(".") + "."]
    parts.append(verse["reference"] + ".")
    reflection = verse.get("reflection", "").strip()
    if reflection:
        parts.append(reflection if reflection.endswith((".", "!", "?")) else reflection + ".")
    return " ".join(parts)


async def _synthesize(text, output_path, voice, rate):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


def narrate(text, output_path, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    asyncio.run(_synthesize(text, output_path, voice, rate))
    return output_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--voice", default=DEFAULT_VOICE)
    p.add_argument("--rate", default=DEFAULT_RATE)
    args = p.parse_args()
    narrate(args.text, args.output, voice=args.voice, rate=args.rate)
    print(f"NARRATION_SAVED={args.output}")
