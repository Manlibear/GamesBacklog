#!/usr/bin/env python3
"""Games Backlog — Textual TUI with real cover art via Kitty's graphics protocol."""

import os
import shutil
from datetime import date
from functools import lru_cache

from PIL import Image as PILImage
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label
from textual_image.widget import Image

import config
import igdb
from library import COVERS_DIR, Game, Library

STATUS_LABELS = {"playing": "PLAYING", "backlog": "BACKLOG", "completed": "COMPLETED"}
UNKNOWN_COVER = os.path.join(COVERS_DIR, "unknown.png")
MAX_SEARCH_RESULTS = 25
STATUS_COVER_OVERLAYS = {
    "completed": os.path.join(COVERS_DIR, "_overlay_completed.png"),
    "playing": os.path.join(COVERS_DIR, "_overlay_playing.png"),
    "backlog": os.path.join(COVERS_DIR, "_overlay_backlog.png"),
}

# Search results get their covers downloaded here rather than into COVERS_DIR
# directly, since most searches never get added — this dir is wiped on every
# app start and every new search, and a cover only earns a permanent home in
# COVERS_DIR once its game is actually marked with a status.
SEARCH_COVERS_DIR = os.path.join(COVERS_DIR, "search")


def _reset_search_covers() -> None:
    shutil.rmtree(SEARCH_COVERS_DIR, ignore_errors=True)
    os.makedirs(SEARCH_COVERS_DIR, exist_ok=True)


def _promote_cover(cover_path: str | None) -> str | None:
    """Copies a search-temp cover into the permanent covers dir, if needed."""
    if not cover_path or not cover_path.startswith(SEARCH_COVERS_DIR):
        return cover_path
    dest = os.path.join(COVERS_DIR, os.path.basename(cover_path))
    if not os.path.exists(dest):
        shutil.copy2(cover_path, dest)
    return dest


@lru_cache(maxsize=None)
def _cover_with_overlay(cover_path: str, overlay_path: str) -> PILImage.Image:
    """Cover art with a status badge pre-composited onto it.

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
    overlay = PILImage.open(overlay_path).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, PILImage.LANCZOS)
    return PILImage.alpha_composite(base, overlay)


class StatusModal(ModalScreen[str | None]):
    """Small centered dialog for picking a game's status."""

    CSS = """
    StatusModal {
        align: center middle;
    }
    #status-dialog {
        width: auto;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #status-dialog .dialog-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        margin-bottom: 1;
    }
    #status-dialog Button {
        width: 32;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]
    AUTO_FOCUS = ""

    def __init__(self, game_name: str):
        super().__init__()
        self.game_name = game_name

    def compose(self) -> ComposeResult:
        with Vertical(id="status-dialog"):
            yield Label(self.game_name, classes="dialog-title")
            yield Button("Playing", id="playing")
            yield Button("Backlog", id="backlog")
            yield Button("Completed", id="completed")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None if event.button.id == "cancel" else event.button.id)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GameCard(Vertical):
    def __init__(self, game: Game, show_status_overlay: bool = False):
        super().__init__(classes="game-card")
        self.game = game
        # Backlog/playing overlays only make sense where a card could be any
        # status (the search screen) — the main screen's cards are already
        # grouped under a status heading, so those overlays would be
        # redundant there. Completed always gets its overlay everywhere.
        self.show_status_overlay = show_status_overlay

    def on_click(self, event: events.Click) -> None:
        self._pick_status()

    @work
    async def _pick_status(self) -> None:
        status = await self.app.push_screen_wait(StatusModal(self.game.name))
        if status is None:
            return

        cover_path = _promote_cover(self.game.cover)

        lib = Library.load()
        lib.add(
            Game(
                name=self.game.name,
                status=status,
                release_date=self.game.release_date,
                cover=cover_path,
            ),
            overwrite_status=True,
        )
        lib.save()

        self.game.status = status
        self.game.cover = cover_path
        self.show_status_overlay = True
        await self.recompose()

        self.app.refresh_library()

    def compose(self) -> ComposeResult:
        # The cover sits in a fixed-height frame so the card's layout stays
        # consistent whether or not this game actually has a cover image —
        # an Image widget with no image reports 0x0 content size, which was
        # collapsing the whole card (and everything below it) when unset.
        cover = (
            self.game.cover
            if self.game.cover and os.path.exists(self.game.cover)
            else UNKNOWN_COVER
        )
        show_overlay = self.game.status == "completed" or self.show_status_overlay
        overlay_path = STATUS_COVER_OVERLAYS.get(self.game.status) if show_overlay else None
        cover_image = (
            _cover_with_overlay(cover, overlay_path) if overlay_path else cover
        )
        with Vertical(classes="cover-frame"):
            yield Image(cover_image, classes="cover")

        yield Label(self.game.name, classes="game-name")

        if self.game.release_date:
            is_future = self.game.release_date > date.today().isoformat()
            yield Label(
                self.game.release_date,
                classes="release-date future" if is_future else "release-date",
            )
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


class SearchScreen(Screen):
    CSS = """
    SearchScreen {
        align: center top;
    }
    #search-bar {
        width: 100%;
        height: auto;
        padding: 0 1;
        align: left middle;
    }
    #search-icon {
        width: 3;
        height: 3;
        content-align: center middle;
    }
    #search-input {
        width: 1fr;
    }
    #search-results-scroll {
        height: 1fr;
        scrollbar-size: 0 0;
    }
    #footer-bar {
        dock: bottom;
        height: 1;
        width: 100%;
        background: $footer-background;
    }
    #search-status {
        width: auto;
        padding: 0 2;
        content-align: left middle;
        color: $text-muted;
        background: $footer-background;
    }
    #footer-bar Footer {
        dock: none;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Back", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-bar"):
            yield Label("\U0001F50D", id="search-icon")
            yield Input(placeholder="Search for a game...", id="search-input")
        with VerticalScroll(id="search-results-scroll"):
            yield Grid(id="search-results-grid", classes="game-grid")
        with Horizontal(id="footer-bar"):
            yield Label("", id="search-status")
            yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()
        self.query_one("#search-results-grid").styles.grid_size_columns = (
            config.get_style()["columns"]
        )

    def action_close(self) -> None:
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        self.query_one("#search-status", Label).update("Searching...")
        self.query_one("#search-results-grid", Grid).remove_children()
        _reset_search_covers()
        self._run_search(query)

    @work(exclusive=True, thread=True)
    def _run_search(self, query: str) -> None:
        client_id, client_secret = config.get_credentials()
        if not client_id or not client_secret:
            self.app.call_from_thread(
                self.query_one("#search-status", Label).update,
                "Missing IGDB credentials.",
            )
            return

        try:
            token = igdb.get_token(client_id, client_secret)
            candidates = igdb.search_candidates(client_id, token, query, MAX_SEARCH_RESULTS)
        except Exception as e:
            self.app.call_from_thread(
                self.query_one("#search-status", Label).update,
                f"Search failed: {e}",
            )
            return

        lib = Library.load()
        results = []
        for c in candidates:
            existing = lib.find(c["name"])
            if existing and existing.cover and os.path.exists(existing.cover):
                cover_path = existing.cover
            elif c["image_id"]:
                cover_path = igdb.download_cover(
                    c["image_id"], c["name"], SEARCH_COVERS_DIR
                )
            else:
                cover_path = None
            game = Game(
                name=c["name"],
                status=existing.status if existing else "backlog",
                release_date=c["release_date"],
                cover=cover_path,
            )
            results.append((game, existing is not None))

        self.app.call_from_thread(self._display_results, results)

    def _display_results(self, results: list[tuple[Game, bool]]) -> None:
        if not results:
            status = "No results found."
        elif len(results) >= MAX_SEARCH_RESULTS:
            status = f"+{MAX_SEARCH_RESULTS} result(s)"
        else:
            status = f"{len(results)} result(s)"
        self.query_one("#search-status", Label).update(status)
        grid = self.query_one("#search-results-grid", Grid)
        for game, in_library in results:
            grid.mount(GameCard(game, show_status_overlay=in_library))


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
        grid-rows: 14;
    }
    .game-card {
        align: center middle;
        height: 14;
        width: 100%;
    }
    .game-card .cover-frame {
        height: 9;
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
        Binding("ctrl+c", "quit", "Quit", priority=True, show=False),
        Binding("ctrl+q", "noop", show=False, priority=True),
        Binding("q", "quit", "Quit"),
        Binding("s", "search", "Search"),
    ]

    def action_noop(self) -> None:
        pass

    def action_search(self) -> None:
        self.push_screen(SearchScreen())

    def refresh_library(self) -> None:
        self.library = Library.load()
        scroll = self.query_one("#scroll-area")
        scroll.remove_children()
        for status in ("playing", "backlog", "completed"):
            scroll.mount(StatusGrid(status, self.library.by_status(status)))

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
        _reset_search_covers()
        self.library = Library.load()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="scroll-area"):
            for status in ("playing", "backlog", "completed"):
                yield StatusGrid(status, self.library.by_status(status))
        yield Footer()


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
        choice = (
            input(f"Enter a number (1-{len(candidates)}, or 'c' to cancel): ")
            .strip()
            .lower()
        )
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

    matched_name, release_date, image_id = (
        match["name"],
        match["release_date"],
        match["image_id"],
    )

    cover_path = None
    if image_id:
        cover_path = igdb.download_cover(image_id, matched_name, COVERS_DIR)

    lib = Library.load()
    lib.add(
        Game(
            name=matched_name,
            status="backlog",
            release_date=release_date,
            cover=cover_path,
        )
    )
    lib.save()
    print(
        f"Added '{matched_name}'"
        + (f" ({release_date})" if release_date else " (no release date found)")
    )
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
    targets = [
        g
        for g in lib.games
        if (not g.release_date or g.release_date > today) and not g.skip_update
    ]
    skipped = [g.name for g in lib.games if g.skip_update]

    if not targets:
        print("No unreleased/unknown-date games to check.")
        return

    any_changes = False
    for game in targets:
        candidates = igdb.search_candidates(client_id, token, game.name)
        exact = next(
            (c for c in candidates if c["name"].casefold() == game.name.casefold()),
            None,
        )
        if not exact:
            print(f"{NAME_COLOR}{game.name}{RESET}: no exact IGDB match, skipped")
            continue

        changes = []
        if exact["release_date"] and exact["release_date"] != game.release_date:
            changes.append(
                f"date {game.release_date or '????-??-??'} -> {exact['release_date']}"
            )
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
    state = (
        "will be skipped by -u" if game.skip_update else "will be checked by -u again"
    )
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

    parser = argparse.ArgumentParser(
        description="Games Backlog — run with no arguments to launch the TUI."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-s", metavar="QUERY", help="Search IGDB and print candidate matches"
    )
    group.add_argument(
        "-a", metavar="NAME", help="Add a game (fetches date + cover from IGDB)"
    )
    group.add_argument("-r", metavar="NAME", help="Remove a game by name")
    group.add_argument("-mc", metavar="NAME", help="Mark a game as completed")
    group.add_argument("-mp", metavar="NAME", help="Mark a game as (now) playing")
    group.add_argument("-mb", metavar="NAME", help="Mark a in the backlog")
    group.add_argument(
        "-u",
        action="store_true",
        help="Re-check IGDB for unreleased/unknown-date games (date + cover updates)",
    )
    group.add_argument(
        "-su",
        metavar="NAME",
        help="Toggle skip-update flag for a game (excludes it from -u)",
    )
    parser.add_argument(
        "-c",
        metavar="COUNT",
        help="Numbers of items to returns for a search/add request",
    )
    args = parser.parse_args()

    if args.a:
        if args.c:
            cli_add(args.a, args.c)
        else:
            cli_add(args.a)
    elif args.r:
        cli_remove(args.r)
    elif args.s:
        if args.c:
            cli_search(args.s, args.c)
        else:
            cli_search(args.s)
    elif args.mc:
        cli_set_status(args.mc, "completed")
    elif args.mp:
        cli_set_status(args.mp, "playing")
    elif args.mb:
        cli_set_status(args.mb, "backlog")
    elif args.u:
        cli_update_unreleased()
    elif args.su:
        cli_toggle_skip(args.su)
    else:
        BacklogApp().run()
