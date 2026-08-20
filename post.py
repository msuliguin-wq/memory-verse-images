#!/usr/bin/env python3
"""
End-to-end daily Bible verse -> Instagram poster.

Flow:
  1. Pick today's verse (deterministic by day-of-year).
  2. Render the card image (photo_card.py — real photo backgrounds).
  3. Generate spoken narration of the verse (narrate.py, edge-tts) and mix
     it with a background music bed into a 1080x1920 video Reel
     (make_reel.py, ffmpeg) with a slow Ken Burns zoom on the card.
     (--static-image falls back to the old plain-image post instead.)
  4. Upload the image or video to a public GitHub repo (Contents API) to
     get a public raw.githubusercontent.com URL. (Imgur's anonymous app
     registration was blocked for this brand-new account, so GitHub is
     used as the public asset host instead.)
  5. Create an Instagram media container (Graph API) and publish it.
  6. Optionally refresh the long-lived access token and print the new one
     so the caller can rotate it into the next day's stored credentials.

Requires: requests, edge-tts (pip install -r requirements.txt) and
ffmpeg/ffprobe on PATH. edge-tts needs real internet access (it's blocked
from some sandboxed dev environments) — this is designed to run on a
GitHub Actions runner.
"""
import argparse
import base64
import json
import sys
import time
import datetime

import requests

from photo_card import load_verses, pick_verse, generate
from caption import build_caption
from narrate import narrate, build_narration_script
from make_reel import make_reel

GRAPH_API_VERSION = "v21.0"
# Instagram API with Instagram Login (no linked Facebook Page required).
# Publishing calls go to graph.instagram.com, not graph.facebook.com.
GRAPH_BASE = "https://graph.instagram.com"
IG_OAUTH_BASE = "https://api.instagram.com/oauth"
GITHUB_API_BASE = "https://api.github.com"

# GitHub Actions runners use UTC. The daily cron fires at 23:30 UTC, which is
# 7:30 AM Philippine Time (UTC+8) -- but that's still the *previous* calendar
# day in UTC. Using datetime.date.today() (the runner's UTC date) for
# "today's" verse/date_str meant the scheduled run picked the SAME calendar
# date -- and therefore the same verse and asset path -- as any manual run
# done earlier that same UTC day, which caused a real duplicate Instagram
# post. Everything date-related below is computed in Philippine time instead
# so "today" rolls over at the moment that matters for this brand's audience.
PH_TZ = datetime.timezone(datetime.timedelta(hours=8))


def today_ph():
    return datetime.datetime.now(PH_TZ).date()

# Background music bed for the narrated reel. Pixabay Content License track
# ("Calm Piano Background" by VibeHorn) — free for this use, no attribution
# required. Downloaded fresh each run (not committed to the repo) so the
# repo stays lean; this direct download URL is expected to stay stable, but
# if Pixabay ever rotates it, update this constant.
MUSIC_URL = (
    "https://cdn.pixabay.com/download/audio/2026/06/09/audio_3f76d66c89.mp3"
    "?filename=vibehorn-calm-piano-background-539083.mp3"
)


def download_music(dest_path, url=MUSIC_URL):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return dest_path


def upload_to_github(local_path, owner, repo, token, branch="main",
                      folder="cards", ext="png"):
    """Uploads a file to a public GitHub repo via the Contents API and
    returns its public raw.githubusercontent.com URL. Path is unique per
    day so nothing gets overwritten."""
    date_str = today_ph().isoformat()
    path = f"{folder}/{date_str}.{ext}"

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    # If a file already exists at this path (e.g. a re-run on the same UTC
    # calendar date), the Contents API requires its current blob sha to
    # update it -- otherwise it 422s. Look it up first; a fresh path (404)
    # is the normal case and just means "create new".
    existing_sha = None
    get_resp = requests.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
        headers=headers,
        params={"ref": branch},
        timeout=30,
    )
    if get_resp.status_code == 200:
        existing_sha = get_resp.json().get("sha")
    elif get_resp.status_code not in (404,):
        raise RuntimeError(f"GitHub lookup failed: {get_resp.status_code} {get_resp.text}")

    payload = {
        "message": f"Add {folder} asset {date_str}",
        "content": content_b64,
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha
        payload["message"] = f"Update {folder} asset {date_str}"

    resp = requests.put(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub upload failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return data["content"]["download_url"]


def publish_to_instagram(ig_user_id, access_token, caption, image_url=None,
                          video_url=None, max_wait_seconds=180):
    """Publishes either a static image (image_url) or a Reel (video_url).
    Exactly one of image_url/video_url should be set. Video containers take
    much longer to process than images, so we poll longer for those."""
    if bool(image_url) == bool(video_url):
        raise ValueError("Pass exactly one of image_url or video_url")

    # Step 1: create media container
    data = {"caption": caption, "access_token": access_token}
    if video_url:
        data["media_type"] = "REELS"
        data["video_url"] = video_url
    else:
        data["image_url"] = image_url

    create_resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        data=data,
        timeout=30,
    )
    create_data = create_resp.json()
    if "id" not in create_data:
        raise RuntimeError(f"Media container creation failed: {create_data}")
    creation_id = create_data["id"]

    # Step 2: poll container status until FINISHED. Images finish almost
    # instantly; video containers can take a minute or more to transcode.
    poll_interval = 3
    attempts = max(1, max_wait_seconds // poll_interval)
    for _ in range(attempts):
        status_resp = requests.get(
            f"{GRAPH_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=15,
        )
        status = status_resp.json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Media container processing failed: {status_resp.json()}")
        time.sleep(poll_interval)
    else:
        raise RuntimeError(f"Media container did not finish processing within {max_wait_seconds}s")

    # Step 3: publish
    publish_resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=30,
    )
    publish_data = publish_resp.json()
    if "id" not in publish_data:
        raise RuntimeError(f"Publish failed: {publish_data}")
    return publish_data["id"]


def exchange_code_for_short_lived_token(code, app_id, app_secret, redirect_uri):
    """One-time step: trade the OAuth authorization code (from the manual
    browser step) for a short-lived (~1hr) token + the numeric IG user id."""
    resp = requests.post(
        f"{IG_OAUTH_BASE}/access_token",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Code exchange failed: {data}")
    return data["access_token"], data.get("user_id")


def exchange_for_long_lived_token(short_lived_token, app_secret):
    """One-time step: trade a short-lived token for a long-lived (~60 day) one."""
    resp = requests.get(
        f"{GRAPH_BASE}/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": short_lived_token,
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Long-lived token exchange failed: {data}")
    return data["access_token"], data.get("expires_in")


def refresh_long_lived_token(current_token, app_id=None, app_secret=None):
    """Extends a long-lived token by another ~60 days. Only works on a
    token that's at least 24h old and not yet expired. Unlike the old
    Facebook Login flow, this does NOT need the app id/secret."""
    resp = requests.get(
        f"{GRAPH_BASE}/refresh_access_token",
        params={
            "grant_type": "ig_refresh_token",
            "access_token": current_token,
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    return data["access_token"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ig-user-id", required=True)
    p.add_argument("--access-token", required=True)
    p.add_argument("--github-owner", required=True)
    p.add_argument("--github-repo", required=True)
    p.add_argument("--github-token", required=True)
    p.add_argument("--brand", default="Memory Verse For Today")
    p.add_argument("--app-id", default=None, help="Meta App ID (unused, kept for compat)")
    p.add_argument("--app-secret", default=None, help="Meta App secret (unused, kept for compat)")
    p.add_argument("--dry-run", action="store_true", help="Generate everything but skip GitHub/Instagram calls")
    p.add_argument("--verse-index", default=None, help="Force a specific verse index instead of date-based pick")
    p.add_argument("--static-image", action="store_true",
                    help="Post the classic static image card instead of a narrated video Reel")
    p.add_argument("--voice", default=None, help="edge-tts voice override (see narrate.py DEFAULT_VOICE)")
    args = p.parse_args()

    verses = load_verses()
    verse, idx = pick_verse(verses, args.verse_index)
    today = today_ph()
    date_str = today.isoformat()
    image_path = f"/tmp/verse_card_{date_str}.png"
    day_of_year = today.timetuple().tm_yday
    generate(verse, idx=idx, day_number=day_of_year, brand=args.brand, verses=verses, output_path=image_path)
    caption = build_caption(verse, idx, brand=args.brand)

    print(f"VERSE_INDEX={idx}")
    print(f"VERSE_REF={verse['reference']}")
    print(f"IMAGE_PATH={image_path}")
    print("CAPTION_PREVIEW:")
    print(caption)

    reel_path = None
    if not args.static_image:
        script = build_narration_script(verse)
        narration_path = f"/tmp/narration_{date_str}.mp3"
        narrate_kwargs = {"voice": args.voice} if args.voice else {}
        narrate(script, narration_path, **narrate_kwargs)
        print(f"NARRATION_PATH={narration_path}")

        music_path = f"/tmp/music_{date_str}.mp3"
        download_music(music_path)
        print(f"MUSIC_PATH={music_path}")

        reel_path = f"/tmp/reel_{date_str}.mp4"
        _, reel_duration = make_reel(image_path, narration_path, music_path, reel_path)
        print(f"REEL_PATH={reel_path}")
        print(f"REEL_DURATION={reel_duration:.2f}")

    if args.dry_run:
        print("DRY_RUN_OK")
        return

    if reel_path:
        video_url = upload_to_github(reel_path, args.github_owner, args.github_repo,
                                      args.github_token, folder="reels", ext="mp4")
        print(f"VIDEO_URL={video_url}")
        post_id = publish_to_instagram(args.ig_user_id, args.access_token, caption, video_url=video_url)
    else:
        image_url = upload_to_github(image_path, args.github_owner, args.github_repo,
                                      args.github_token, folder="cards", ext="png")
        print(f"IMAGE_URL={image_url}")
        post_id = publish_to_instagram(args.ig_user_id, args.access_token, caption, image_url=image_url)

    print(f"POST_SUCCESS post_id={post_id}")

    # Instagram Login long-lived tokens (~60 days) refresh with just the
    # token itself -- no app id/secret needed, unlike the old FB Login flow.
    try:
        new_token = refresh_long_lived_token(args.access_token)
        print(f"NEW_TOKEN={new_token}")
    except Exception as e:
        print(f"TOKEN_REFRESH_FAILED={e}")


if __name__ == "__main__":
    main()
