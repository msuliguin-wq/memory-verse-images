#!/usr/bin/env python3
"""Generates a warm, simple Instagram caption for a given verse."""

OPENERS = [
    "Good morning! Here's a little light for your day:",
    "Starting the day with this promise:",
    "A gentle reminder this morning:",
    "Something to carry with you today:",
    "Here's today's word of encouragement:",
    "Take a moment with this today:",
    "For your morning: a word of peace.",
]

HASHTAGS = (
    "#BibleVerse #DailyDevotion #Scripture #WordOfGod #FaithOverFear "
    "#KJV #BibleQuotes #GodIsGood "
    "#PinoyChristian #FilipinoChristian #Pilipinas "
    "#SeventhDayAdventist #SDA #PinoySDA"
)


def build_caption(verse, index=0, brand="Memory Verse For Today"):
    opener = OPENERS[index % len(OPENERS)]
    text = verse["text"].strip()
    ref = verse["reference"]
    explanation = verse.get("explanation", "").strip()

    parts = [
        f"{opener}\n\n"
        f"“{text}”\n"
        f"— {ref}",
    ]
    if explanation:
        parts.append(f"📖 What this means: {explanation}")
    parts.append(f"{HASHTAGS}")

    caption = "\n\n".join(parts)
    return caption


if __name__ == "__main__":
    import json
    with open("verses.json") as f:
        verses = json.load(f)
    print(build_caption(verses[0], 0))
