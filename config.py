"""Loads IGDB credentials + style overrides from config.json.

Credentials: env vars (IGDB_CLIENT_ID/IGDB_CLIENT_SECRET) take priority over
config.json, so existing shell-based setups keep working unchanged.
Style: config.json values override these defaults; anything unset falls
back to the default below.
"""

import json
import os

DATA_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "gamesbacklog")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULT_STYLE = {
    "columns": 4,
    "accent_color": None,  # None = use Textual's default theme accent
    "future_color": "yellow",
    "header_spacing": 1,
    "row_spacing": 1,
}


def _load_raw() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_credentials() -> tuple[str | None, str | None]:
    raw = _load_raw()
    client_id = os.environ.get("IGDB_CLIENT_ID") or raw.get("igdb_client_id") or None
    client_secret = os.environ.get("IGDB_CLIENT_SECRET") or raw.get("igdb_client_secret") or None
    return client_id, client_secret


def get_style() -> dict:
    raw = _load_raw()
    style = dict(DEFAULT_STYLE)
    style.update(raw.get("style", {}))
    return style
