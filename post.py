#!/usr/bin/env python3
"""
End-to-end daily Bible verse -> Instagram poster.

Flow:
  1. Pick today's verse (deterministic by day-of-year).
  2. Render the card image (photo_card.py — real photo backgrounds).
  3. Upload the image to a public GitHub repo (Contents API) to get a
     public raw.githubusercontent.com URL. (Imgur's anonymous app
     registration was blocked for this brand-new account, so GitHub is
     used as the public image host instead.)
  4. Create an Instagram media container (Graph API) and publish it.
  5. Optionally refresh the long-lived access token and print the new one
     so the caller can rotate it into the next day's stored credentials.

Requires: requests (pip install requests --break-system-packages)
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

GRAPH_API_VERSION = "v21.0"
# Instagram API with Instagram Login (no linked Facebook Page required).
# Publishing calls go to graph.instagram.com, not graph.facebook.com.
GRAPH_BASE = "https://graph.instagram.com"
IG_OAUTH_BASE = "https://api.instagram.com/oauth"
GITHUB_API_BASE = "https://api.github.com"


def upload_to_github(image_path, owner, repo, token, branch="main"):
    """Uploads the image to a public GitHub repo via the Contents API and
    returns its public raw.githubusercontent.com URL. Path is unique per
    day so nothing gets overwritten."""
    date_str = datetime.date.today().isoformat()
    path = f"cards/{date_str}.png"

    with open(image_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")

    resp = requests.put(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "message": f"Add verse card {date_str}",
            "content": content_b64,
            "branch": branch,
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub upload failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return data["content"]["download_url"]


def publish_to_instagram(ig_user_id, access_token, image_url, caption):
    # Step 1: create media container
    create_resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    create_data = create_resp.json()
    if "id" not in create_data:
        raise RuntimeError(f"Media container creation failed: {create_data}")
    creation_id = create_data["id"]

    # Step 2: poll container status until FINISHED (usually instant for image_url)
    for _ in range(10):
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
        time.sleep(2)

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
    args = p.parse_args()

    verses = load_verses()
    verse, idx = pick_verse(verses, args.verse_index)
    image_path = f"/tmp/verse_card_{datetime.date.today().isoformat()}.png"
    day_of_year = datetime.date.today().timetuple().tm_yday
    generate(verse, idx=idx, day_number=day_of_year, brand=args.brand, output_path=image_path)
    caption = build_caption(verse, idx, brand=args.brand)

    print(f"VERSE_INDEX={idx}")
    print(f"VERSE_REF={verse['reference']}")
    print(f"IMAGE_PATH={image_path}")
    print("CAPTION_PREVIEW:")
    print(caption)

    if args.dry_run:
        print("DRY_RUN_OK")
        return

    image_url = upload_to_github(image_path, args.github_owner, args.github_repo, args.github_token)
    print(f"IMAGE_URL={image_url}")

    post_id = publish_to_instagram(args.ig_user_id, args.access_token, image_url, caption)
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
