#!/usr/bin/env python3
"""Games Backlog — Textual TUI with real cover art via Kitty's graphics protocol."""

import os
from datetime import date
from functools import lru_cache

from PIL import Image as PILImage
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.widgets import Label
from textual_image.widget import Image

import config
import igdb
from library import COVERS_DIR, Game, Library

STATUS_LABELS = {"playing": "PLAYING", "backlog": "BACKLOG", "completed": "COMPLETED"}
UNKNOWN_COVER = os.path.join(COVERS_DIR, "unknown.png")
COMPLETED_COVER_OVERLAY = os.path.join(COVERS_DIR, "completed_overlay.png")


@lru_cache(maxsize=None)
def _completed_cover(cover_path: str) -> PILImage.Image:
    """Cover art with the completed badge pre-composited onto it.

    Two stacked Image widgets over the same cells doesn't work here: Kitty
    rendering via textual-image works by writing special placeholder glyphs
    into the terminal's text cells, and Textual's widget layering — like any
    text-cell compositor — just replaces the lower layer's glyphs wherever
    the upper layer occupies a cell. The base cover's glyphs never reach the
    terminal for the overlapped region, so there's nothing for the overlay
    to alpha-blend against. Compositing the pixels ourselves first sidesteps
    this — there's only ever one Kitty placement per card.
    """
    base = PILImage.open(cover_path).convert("RGBA")
    overlay = PILImage.open(COMPLETED_COVER_OVERLAY).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, PILImage.LANCZOS)
    return PILImage.alpha_composite(base, overlay)


class GameCard(Vertical):
    def __init__(self, game: Game):
        super().__init__(classes="game-card")
        self.game = game

    def compose(self) -> ComposeResult:
        # The cover sits in a fixed-height frame so the card's layout stays
        # consistent whether or not this game actually has a cover image —
        # an Image widget with no image reports 0x0 content size, which was
        # collapsing the whole card (and everything below it) when unset.
        cover = self.game.cover if self.game.cover and os.path.exists(self.game.cover) else UNKNOWN_COVER
        cover_image = _completed_cover(cover) if self.game.status == "completed" else cover
        with Vertical(classes="cover-frame"):
            yield Image(cover_image, classes="cover")

        yield Label(self.game.name, classes="game-name")

        if self.game.release_date:
            is_future = self.game.release_date > date.today().isoformat()
            yield Label(self.game.release_date, classes="release-date future" if is_future else "release-date")
        else:
            yield Label("????-??-??", classes="release-date")


class StatusGrid(Vertical):
    def __init__(self, status: str, games: list[Game]):
        super().__init__()
        self.status = status
        self.games = games

    def compose(self) -> ComposeResult:
        yield Label(STATUS_LABELS[self.status], classes="section")
        grid = Grid(classes="game-grid")
        grid.styles.grid_size_columns = config.get_style()["columns"]
        with grid:
            for game in self.games:
                yield GameCard(game)


class BacklogApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #scroll-area {
        height: 1fr;
        scrollbar-size: 0 0;
    }
    StatusGrid {
        height: auto;
    }
    Label.section {
        text-style: bold;
        color: $accent;
        margin: $header-spacing 0 0 2;
    }
    .game-grid {
        grid-gutter: $row-spacing 2;
        padding: 1 2;
        height: auto;
        grid-rows: 18;
    }
    .game-card {
        align: center middle;
        height: 18;
        width: 100%;
    }
    .game-card .cover-frame {
        height: 14;
        width: 100%;
        align: center middle;
    }
    .game-card .cover {
        width: auto;
        height: auto;
    }

    .game-card .game-name {
        text-align: center;
        text-style: bold;
        width: 100%;
        height: 2;
    }
    .game-card .release-date {
        text-align: center;
        color: $text-muted;
        width: 100%;
        height: 1;
    }
    .game-card .release-date.future {
        color: $future-color;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+q", "noop", show=False, priority=True),
    ]

    def action_noop(self) -> None:
        pass

    def get_css_variables(self) -> dict[str, str]:
        variables = super().get_css_variables()
        style = config.get_style()
        variables["future-color"] = style["future_color"]
        variables["header-spacing"] = str(style["header_spacing"])
        variables["row-spacing"] = str(style["row_spacing"])
        if style["accent_color"]:
            variables["accent"] = style["accent_color"]
        return variables

    def __init__(self):
        # ansi_color=True makes Textual emit ANSI color codes instead of
        # explicit 24-bit RGB. Kitty's background_opacity/background_blur
        # only apply to the terminal's own "default" ANSI background — any
        # explicit RGB paint (Textual's normal mode) is always fully opaque
        # regardless of terminal transparency settings, which is what was
        # causing the visible background panel. Tradeoff: loses Textual's
        # internal alpha-blend/shading effects, unused here anyway.
        super().__init__(ansi_color=True)
        self.library = Library.load()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="scroll-area"):
            for status in ("playing", "backlog", "completed"):
                yield StatusGrid(status, self.library.by_status(status))


def _require_credentials() -> tuple[str, str]:
    client_id, client_secret = config.get_credentials()
    if not client_id or not client_secret:
        print(
            "Set IGDB_CLIENT_ID/IGDB_CLIENT_SECRET env vars, or add igdb_client_id/"
            "igdb_client_secret to config.json (see config.example.json)."
        )
        raise SystemExit(1)
    return client_id, client_secret


NAME_COLOR = "\033[1;36m"  # bold cyan
RESET = "\033[0m"


def _print_candidates(candidates: list[dict]) -> None:
    for i, c in enumerate(candidates, start=1):
        date = c["release_date"] or "unknown date"
        print(f"{i}. {NAME_COLOR}{c['name']}{RESET} ({date})")
        if c["summary"]:
            summary = c["summary"].replace("\n", " ")
            print(f"   {summary[:140]}{'...' if len(summary) > 140 else ''}")
        print()


def _prompt_candidate_choice(candidates: list[dict]) -> dict | None:
    """Pacman-style disambiguation prompt. Returns None if the user cancels."""
    _print_candidates(candidates)
    while True:
        choice = input(f"Enter a number (1-{len(candidates)}, or 'c' to cancel): ").strip().lower()
        if choice in ("c", "cancel", ""):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1]
        print("Invalid selection.")


def cli_add(name: str, count: int = 10) -> None:
    client_id, client_secret = _require_credentials()
    token = igdb.get_token(client_id, client_secret)
    candidates = igdb.search_candidates(client_id, token, name, count)

    if not candidates:
        print(f"No IGDB results for '{name}'")
        return

    if len(candidates) == 1:
        match = candidates[0]
    else:
        match = _prompt_candidate_choice(candidates)
        if match is None:
            print("Cancelled.")
            return

    matched_name, release_date, image_id = match["name"], match["release_date"], match["image_id"]

    cover_path = None
    if image_id:
        cover_path = igdb.download_cover(image_id, matched_name, COVERS_DIR)

    lib = Library.load()
    lib.add(Game(name=matched_name, status="backlog", release_date=release_date, cover=cover_path))
    lib.save()
    print(f"Added '{matched_name}'" + (f" ({release_date})" if release_date else " (no release date found)"))
    if not cover_path:
        print("  (no cover art found)")


def cli_remove(name: str) -> None:
    lib = Library.load()
    if lib.remove(name):
        lib.save()
        print(f"Removed '{name}'")
    else:
        print(f"No game found matching '{name}'")


def cli_update_unreleased() -> None:
    """Re-checks IGDB for every game with no release date or a future one —
    released games are stable and not worth churning through on every run."""
    client_id, client_secret = _require_credentials()
    token = igdb.get_token(client_id, client_secret)
    lib = Library.load()

    today = date.today().isoformat()
    targets = [g for g in lib.games if (not g.release_date or g.release_date > today) and not g.skip_update]
    skipped = [g.name for g in lib.games if g.skip_update]

    if not targets:
        print("No unreleased/unknown-date games to check.")
        return

    any_changes = False
    for game in targets:
        candidates = igdb.search_candidates(client_id, token, game.name)
        exact = next((c for c in candidates if c["name"].casefold() == game.name.casefold()), None)
        if not exact:
            print(f"{NAME_COLOR}{game.name}{RESET}: no exact IGDB match, skipped")
            continue

        changes = []
        if exact["release_date"] and exact["release_date"] != game.release_date:
            changes.append(f"date {game.release_date or '????-??-??'} -> {exact['release_date']}")
            game.release_date = exact["release_date"]

        if not game.cover and exact["image_id"]:
            cover_path = igdb.download_cover(exact["image_id"], game.name, COVERS_DIR)
            if cover_path:
                changes.append("cover art now available")
                game.cover = cover_path

        if changes:
            any_changes = True
            print(f"{NAME_COLOR}{game.name}{RESET}: {', '.join(changes)}")
        else:
            print(f"{game.name}: no change")

    if any_changes:
        lib.save()
    if skipped:
        print(f"\n(skipped, marked no-update: {', '.join(skipped)})")
    print("\nDone.")


def cli_toggle_skip(name: str) -> None:
    lib = Library.load()
    game = lib.find(name)
    if not game:
        print(f"No game found matching '{name}'")
        return
    game.skip_update = not game.skip_update
    lib.save()
    state = "will be skipped by -u" if game.skip_update else "will be checked by -u again"
    print(f"'{game.name}' -> {state}")


def cli_set_status(name: str, status: str) -> None:
    lib = Library.load()
    game = lib.find(name)
    if not game:
        print(f"No game found matching '{name}'")
        return
    game.status = status
    lib.save()
    print(f"'{game.name}' -> {status}")


def cli_search(query: str, count: int = 10) -> None:
    client_id, client_secret = _require_credentials()
    token = igdb.get_token(client_id, client_secret)
    candidates = igdb.search_candidates(client_id, token, query, count)

    if not candidates:
        print(f"No IGDB results for '{query}'")
        return

    _print_candidates(candidates)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Games Backlog — run with no arguments to launch the TUI.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-s", metavar="QUERY", help="Search IGDB and print candidate matches")
    group.add_argument("-a", metavar="NAME", help="Add a game (fetches date + cover from IGDB)")
    group.add_argument("-r", metavar="NAME", help="Remove a game by name")
    group.add_argument("-mc", metavar="NAME", help="Mark a game as completed")
    group.add_argument("-mp", metavar="NAME", help="Mark a game as (now) playing")
    group.add_argument(
        "-u", action="store_true", help="Re-check IGDB for unreleased/unknown-date games (date + cover updates)"
    )
    group.add_argument("-su", metavar="NAME", help="Toggle skip-update flag for a game (excludes it from -u)")
    parser.add_argument("-c", metavar="COUNT", help="Numbers of items to returns for a search/add request")
    args = parser.parse_args()

    if args.a:
        if(args.c):
            cli_add(args.a, args.c)
        else:
            cli_add(args.a)
    elif args.r:
        cli_remove(args.r)
    elif args.s:
        if(args.c):
            cli_search(args.s, args.c)
        else:
            cli_search(args.s)
    elif args.mc:
        cli_set_status(args.mc, "completed")
    elif args.mp:
        cli_set_status(args.mp, "playing")
    elif args.u:
        cli_update_unreleased()
    elif args.su:
        cli_toggle_skip(args.su)
    else:
        BacklogApp().run()
