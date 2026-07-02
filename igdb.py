"""IGDB lookup + cover download. Ported from ~/games-backlog/fetch_dates.py —
same proven matching logic (exact-name + earliest-release-date preference,
since IGDB's `search` doesn't combine reliably with `where`/`sort`)."""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "game"


def get_token(client_id: str, client_secret: str) -> str:
    url = (
        "https://id.twitch.tv/oauth2/token"
        f"?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials"
    )
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["access_token"]


def lookup_game(client_id: str, token: str, game_name: str) -> tuple[str, str | None, str | None]:
    """Returns (matched_name, ISO date string or None, cover image_id or None)."""
    body = (
        f'search "{game_name}"; '
        "fields name,first_release_date,cover.image_id; "
        "limit 10;"
    ).encode()
    req = urllib.request.Request(
        "https://api.igdb.com/v4/games",
        data=body,
        method="POST",
        headers={
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain",
        },
    )
    with urllib.request.urlopen(req) as resp:
        results = json.load(resp)

    if not results:
        return game_name, None, None

    exact = [r for r in results if r.get("name", "").casefold() == game_name.casefold()]
    candidates = exact or results

    def sort_key(r):
        ts = r.get("first_release_date")
        return (ts is None, ts if ts is not None else 0)

    match = min(candidates, key=sort_key)
    matched_name = match.get("name", game_name)

    timestamp = match.get("first_release_date")
    date = None
    if timestamp is not None:
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()

    cover = match.get("cover") or {}
    image_id = cover.get("image_id")

    return matched_name, date, image_id


def search_candidates(client_id: str, token: str, query: str, limit: int = 10) -> list[dict]:
    """Returns raw IGDB search results (name, release date, cover image_id) for
    disambiguation — unlike lookup_game, doesn't narrow down to a single best guess."""
    body = (
        f'search "{query}"; '
        "fields name,first_release_date,cover.image_id,summary; "
        f"limit {limit};"
    ).encode()
    req = urllib.request.Request(
        "https://api.igdb.com/v4/games",
        data=body,
        method="POST",
        headers={
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain",
        },
    )
    with urllib.request.urlopen(req) as resp:
        results = json.load(resp)

    candidates = []
    for r in results:
        timestamp = r.get("first_release_date")
        date = None
        if timestamp is not None:
            date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        candidates.append(
            {
                "name": r.get("name"),
                "release_date": date,
                "image_id": (r.get("cover") or {}).get("image_id"),
                "summary": r.get("summary"),
            }
        )
    return candidates


def download_cover(image_id: str, game_name: str, covers_dir: str, size: str = "cover_big") -> str | None:
    """Downloads the cover to <covers_dir>/<slug>.jpg, returns an absolute path (or None)."""
    os.makedirs(covers_dir, exist_ok=True)
    filename = f"{slugify(game_name)}.jpg"
    dest = os.path.join(covers_dir, filename)

    if os.path.exists(dest):
        return dest

    url = f"https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception:
        return None

    return dest
