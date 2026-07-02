# GamesBacklog

A terminal game backlog tracker built with [Textual](https://github.com/Textualize/textual),
showing real cover art via the Kitty graphics protocol (through
[`textual-image`](https://github.com/lnqs/textual-image)). Three scrollable grids — Playing,
Backlog, Completed — each card showing cover art, title, and release date (upcoming releases
highlighted). Game data comes from [IGDB](https://www.igdb.com/).

Admin (add/remove/search/status changes) is done entirely through CLI flags rather than in-app —
run with no arguments to just browse.

## Requirements

- Python 3.11+
- A terminal that supports the Kitty graphics protocol or Sixel for cover art to render (Kitty,
  WezTerm, iTerm2, foot, etc.) — see [`textual-image`](https://github.com/lnqs/textual-image)'s
  support matrix. Without one, covers fall back to a text/Unicode approximation.
- An IGDB API application (free) — see **Credentials** below.

## Setup

```sh
git clone <this repo> GamesBacklog
cd GamesBacklog
python3 -m venv .venv
source .venv/bin/activate       # bash/zsh
# or: source .venv/bin/activate.fish   # fish
pip install -r requirements.txt
cp config.example.json config.json
```

Edit `config.json` and fill in your IGDB credentials (or export `IGDB_CLIENT_ID`/
`IGDB_CLIENT_SECRET` as env vars instead — those take priority over `config.json` if both are
set).

### IGDB credentials

IGDB's API auth goes through Twitch:

1. Go to <https://dev.twitch.tv/console/apps> and log in with a Twitch account (free).
2. Click **Register Your Application**.
   - Name: anything (e.g. `gamesbacklog`)
   - OAuth Redirect URLs: `http://localhost` (required but unused)
   - Category: `Application Integration`
3. Click **Manage** on the app for your **Client ID**, then **New Secret** for a **Client
   Secret**.
4. Put both in `config.json`, or export them:
   ```sh
   export IGDB_CLIENT_ID="your-client-id"
   export IGDB_CLIENT_SECRET="your-client-secret"
   ```

## Usage

```sh
python3 app.py          # launch the TUI (browse-only)
```

### CLI admin

```
-a NAME     Add a game (fetches date + cover from IGDB; if the search is
            ambiguous, lists numbered candidates and prompts for a pick)
-r NAME     Remove a game by name
-s QUERY    Search IGDB and print candidate matches without adding anything
-mc NAME    Mark a game as completed
-mp NAME    Mark a game as (now) playing
-u          Re-check IGDB for every game with no release date or a future
            one (already-released games are stable and skipped); updates
            the release date and/or fetches cover art if now available
-su NAME    Toggle a game's skip-update flag, excluding it from -u (useful
            if you've manually corrected a date IGDB gets wrong, e.g. an
            early-access date vs. the 1.0 release you're actually tracking)
```

## Configuration

`config.json` (gitignored; copy from `config.example.json`):

| Key                    | Default   | Meaning                                              |
| ----------------------- | --------- | ----------------------------------------------------- |
| `igdb_client_id`        | —         | IGDB/Twitch client ID (or use `IGDB_CLIENT_ID` env var) |
| `igdb_client_secret`    | —         | IGDB/Twitch client secret (or use `IGDB_CLIENT_SECRET` env var) |
| `style.columns`         | `4`       | Grid columns per row                                   |
| `style.accent_color`    | `null`    | Overrides Textual's default theme accent color (section headers) |
| `style.future_color`    | `"yellow"`| Color for release dates that are still in the future    |
| `style.header_spacing`  | `1`       | Top margin above each section header (PLAYING/BACKLOG/COMPLETED) |
| `style.row_spacing`     | `1`       | Vertical gap between grid rows                          |

## Terminal transparency (optional)

This looks best in a terminal with background transparency + a compositor blur effect (e.g.
Kitty with `background_opacity`/`background_blur` set, on a Wayland compositor that supports
blur-behind for semitransparent windows). The app sets `ansi_color=True` on the Textual `App` so
the terminal's own transparency can show through — Textual's default full-RGB rendering mode is
always opaque regardless of terminal settings, which is a documented Textual limitation, not a
bug in this app.

## Data

`library.json` (gitignored) holds your actual backlog — a flat list of games with `name`,
`status` (`playing`/`backlog`/`completed`), `release_date`, `cover` (path into `covers/`), and
`skip_update`. `covers/unknown.png` is the shipped fallback image used when a game has no cover
art; everything else in `covers/` is gitignored (downloaded per-user).

## License

MIT — see `LICENSE`.
