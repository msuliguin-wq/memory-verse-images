#!/usr/bin/env python3
"""
Verse card using real photo backgrounds (from backgrounds/) with a frosted-glass
text panel — verse + reference + short modern reflection + day counter.
"""
import json
import os
import glob
import datetime
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1350

# Font files are bundled in this repo (fonts/) so generation doesn't depend
# on whatever fonts happen to be preinstalled on the runner.
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
SERIF_ITALIC = os.path.join(_FONT_DIR, "Lora-Italic-Variable.ttf")
SANS_MEDIUM = os.path.join(_FONT_DIR, "Poppins-Medium.ttf")
SANS_LIGHT = os.path.join(_FONT_DIR, "Poppins-Light.ttf")

TEXT_COLOR = (48, 38, 32)
ACCENT = (176, 120, 56)
MUTED = (96, 78, 64)
PANEL_TINT = (255, 250, 240, 150)  # frosted glass tint over blurred photo

BACKGROUNDS_DIR = "backgrounds"

# GitHub Actions runners use UTC. The daily cron fires at 23:30 UTC (7:30 AM
# Philippine Time the *next* day), so date.today() on the runner still
# reports the previous calendar day at that moment. Computing "today" in
# Philippine time instead means the verse-of-the-day rolls over at the
# right moment and won't collide with a manual run made earlier the same
# UTC day.
PH_TZ = datetime.timezone(datetime.timedelta(hours=8))


def today_ph():
    return datetime.datetime.now(PH_TZ).date()


# Simple thematic mapping so the mood of the photo matches the verse.
# Falls back to round-robin if a reference isn't explicitly mapped.
THEME_MAP = {
    "ocean_aerial.jpg": ["Psalm 23:1", "Isaiah 26:3", "John 14:27", "Psalm 46:1",
                          "Isaiah 41:10", "Matthew 11:28", "Psalm 34:18", "Nahum 1:7"],
    "redwood_forest.jpg": ["Joshua 1:9", "Deuteronomy 31:6", "Philippians 4:13",
                            "Isaiah 40:31", "2 Timothy 1:7", "Hebrews 11:1", "Proverbs 18:10"],
    "fig_tree_sun.jpg": ["Jeremiah 29:11", "John 3:16", "Romans 8:28", "Psalm 118:24",
                          "Lamentations 3:22-23", "Psalm 30:5", "Psalm 16:11", "1 John 4:19"],
    "poppy_field.jpg": ["Psalm 37:4", "Zephaniah 3:17", "Matthew 5:16", "Psalm 139:14",
                         "Romans 15:13", "1 Corinthians 13:13", "Micah 6:8", "3 John 1:2"],
}
REF_TO_BG = {ref: bg for bg, refs in THEME_MAP.items() for ref in refs}
BG_LIST = list(THEME_MAP.keys())


def load_verses(path="verses.json"):
    with open(path) as f:
        return json.load(f)


def pick_verse(verses, key=None):
    if key is None:
        day_of_year = today_ph().timetuple().tm_yday
        idx = day_of_year % len(verses)
    else:
        idx = int(key) % len(verses)
    return verses[idx], idx


def pick_background(verse, idx):
    return REF_TO_BG.get(verse["reference"], BG_LIST[idx % len(BG_LIST)])


_background_sequence_cache = {}


def _compute_background_sequence(verses):
    """Walks the full verse cycle in day order once and resolves every
    consecutive-day collision, so shifting one day's background to avoid a
    repeat can never just create a new repeat with the day after it (a
    naive "only look at yesterday" check doesn't guarantee that -- fixing
    one collision can chain into the next slot)."""
    n = len(verses)
    seq = []
    for i in range(n):
        bg = pick_background(verses[i], i)
        if seq and bg == seq[-1]:
            bg = BG_LIST[(BG_LIST.index(bg) + 1) % len(BG_LIST)]
        seq.append(bg)
    # The cycle also wraps (day 40 follows day 39 into day 0 of the next
    # 40-day loop) -- fix that seam too, best-effort.
    if len(seq) > 1 and seq[-1] == seq[0]:
        seq[0] = BG_LIST[(BG_LIST.index(seq[0]) + 1) % len(BG_LIST)]
    return seq


def pick_background_no_repeat(verses, verse, idx):
    """Like pick_background, but guarantees the result never matches the
    background used for the immediately preceding calendar day. Several
    verses intentionally share a themed background (e.g. both
    "1 John 4:19" and "Psalm 118:24" use fig_tree_sun.jpg), so two
    consecutive days can land on the same photo purely by chance -- this
    resolves that across the whole cycle without changing any of the
    deliberate verse-to-photo pairings."""
    cache_key = id(verses)
    if cache_key not in _background_sequence_cache:
        _background_sequence_cache[cache_key] = _compute_background_sequence(verses)
    return _background_sequence_cache[cache_key][idx % len(verses)]


CROP_BIAS = {
    # 0.0 = crop from the very top, 1.0 = crop from the very bottom
    "poppy_field.jpg": 0.62,
    "fig_tree_sun.jpg": 0.30,
    "ocean_aerial.jpg": 0.50,
    "redwood_forest.jpg": 0.42,
}


def cover_crop_resize(img, target_w, target_h, bias=0.4):
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_h = src_h
        new_w = int(src_h * target_ratio)
    else:
        new_w = src_w
        new_h = int(src_w / target_ratio)
    left = (src_w - new_w) // 2
    top = int((src_h - new_h) * bias)
    cropped = img.crop((left, top, left + new_w, top + new_h))
    return cropped.resize((target_w, target_h), Image.LANCZOS)


def frosted_panel(base_rgba, box, blur_radius=28, tint=PANEL_TINT, radius=30):
    """Crops box from base, blurs it, tints it, masks to rounded rect, pastes back."""
    x0, y0, x1, y1 = box
    region = base_rgba.crop(box).filter(ImageFilter.GaussianBlur(blur_radius))
    tint_layer = Image.new("RGBA", region.size, tint)
    region = Image.alpha_composite(region.convert("RGBA"), tint_layer)

    mask = Image.new("L", region.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, region.size[0] - 1, region.size[1] - 1], radius=radius, fill=255)
    base_rgba.paste(region, (x0, y0), mask)

    # subtle border
    d = ImageDraw.Draw(base_rgba)
    d.rounded_rectangle(box, radius=radius, outline=(255, 255, 255, 90), width=2)


def wrap_and_fit(draw, text, font_path, max_width, max_height, start_size=50, min_size=28):
    size = start_size
    lines, font, line_h = [text], None, 0
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        avg_char_w = font.getlength("n")
        chars_per_line = max(10, int(max_width / avg_char_w))
        lines = textwrap.wrap(text, width=chars_per_line)
        while True:
            too_wide = any(draw.textlength(line, font=font) > max_width for line in lines)
            if not too_wide:
                break
            chars_per_line -= 2
            if chars_per_line < 8:
                break
            lines = textwrap.wrap(text, width=chars_per_line)
        bbox = font.getbbox("Ag")
        line_h = (bbox[3] - bbox[1]) * 1.32
        total_height = len(lines) * line_h
        if total_height <= max_height:
            return font, lines, line_h
        size -= 2
    return font, lines, line_h


def generate(verse, idx=0, day_number=None, brand="Memory Verse For Today",
             background=None, verses=None, output_path="photo_card.png"):
    if background:
        bg_name = background
    elif verses:
        bg_name = pick_background_no_repeat(verses, verse, idx)
    else:
        bg_name = pick_background(verse, idx)
    bg_path = os.path.join(BACKGROUNDS_DIR, bg_name)
    photo = Image.open(bg_path).convert("RGB")
    bias = CROP_BIAS.get(bg_name, 0.4)
    canvas = cover_crop_resize(photo, WIDTH, HEIGHT, bias=bias).convert("RGBA")

    # gentle overall warm scrim for cohesion across different photos
    scrim = Image.new("RGBA", canvas.size, (40, 28, 20, 40))
    canvas.alpha_composite(scrim)
    # smooth vertical gradient (darker top, clear by mid-frame) — no hard edges
    grad = Image.new("L", (1, HEIGHT), 0)
    for y in range(HEIGHT):
        t = min(1.0, y / (HEIGHT * 0.45))
        grad.putpixel((0, y), int(80 * (1 - t)))
    grad = grad.resize((WIDTH, HEIGHT))
    top_scrim = Image.new("RGBA", canvas.size, (15, 10, 8, 0))
    top_scrim.putalpha(grad)
    canvas.alpha_composite(top_scrim)

    dummy_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    margin_x = 90
    panel_w = WIDTH - 2 * margin_x

    quote_text = f"“{verse['text'].strip()}”"
    quote_font, quote_lines, quote_lh = wrap_and_fit(
        dummy_draw, quote_text, SERIF_ITALIC, panel_w - 100, 460, start_size=44, min_size=26
    )
    refl_font = ImageFont.truetype(SERIF_ITALIC, 32)
    refl_lines = textwrap.wrap(verse.get("reflection", ""), width=34)
    ref_font = ImageFont.truetype(SANS_MEDIUM, 26)
    day_font = ImageFont.truetype(SANS_MEDIUM, 22)

    pad_top, pad_bottom = 44, 38
    line_gap = 16
    panel_h = pad_top
    if day_number:
        panel_h += 30 + 16
    panel_h += len(quote_lines) * quote_lh
    panel_h += 40
    panel_h += line_gap
    panel_h += len(refl_lines) * 40
    panel_h += pad_bottom

    panel_y = int(HEIGHT * 0.22)
    box = (margin_x, panel_y, margin_x + panel_w, panel_y + int(panel_h))
    frosted_panel(canvas, box)

    d = ImageDraw.Draw(canvas)
    cx = WIDTH // 2
    cy = panel_y + pad_top

    if day_number:
        label = f"DAY {day_number} OF 365"
        spaced = " ".join(label)
        lw = d.textlength(spaced, font=day_font)
        d.text((cx - lw / 2, cy), spaced, font=day_font, fill=ACCENT)
        cy += 30 + 16

    for line in quote_lines:
        lw = d.textlength(line, font=quote_font)
        d.text((cx - lw / 2, cy), line, font=quote_font, fill=TEXT_COLOR)
        cy += quote_lh

    ref_text = " ".join(verse["reference"].upper())
    rw = d.textlength(ref_text, font=ref_font)
    d.text((cx - rw / 2, cy), ref_text, font=ref_font, fill=ACCENT)
    cy += 40 + line_gap

    for line in refl_lines:
        lw = d.textlength(line, font=refl_font)
        d.text((cx - lw / 2, cy), line, font=refl_font, fill=MUTED)
        cy += 40

    # brand footer with soft shadow for legibility over photo
    if brand:
        foot_font = ImageFont.truetype(SANS_LIGHT, 24)
        foot_text = " ".join(brand.upper())
        fw = d.textlength(foot_text, font=foot_font)
        fx, fy = WIDTH / 2 - fw / 2, HEIGHT - 60
        d.text((fx + 1, fy + 1), foot_text, font=foot_font, fill=(0, 0, 0, 120))
        d.text((fx, fy), foot_text, font=foot_font, fill=(255, 250, 240))

    canvas.convert("RGB").save(output_path, "PNG", quality=92)
    return output_path, bg_name


if __name__ == "__main__":
    import sys
    verses = load_verses()
    key = sys.argv[1] if len(sys.argv) > 1 else None
    out = sys.argv[2] if len(sys.argv) > 2 else "photo_sample.png"
    verse, idx = pick_verse(verses, key)
    day_of_year = today_ph().timetuple().tm_yday
    path, bg = generate(verse, idx=idx, day_number=day_of_year, verses=verses, output_path=out)
    print(f"idx={idx} ref={verse['reference']} bg={bg} -> {path}")
