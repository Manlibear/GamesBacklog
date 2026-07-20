"""JSON-backed game library — Playing / Backlog / Completed."""

import json
import os
from dataclasses import asdict, dataclass, field

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(ROOT, "assets")

DATA_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "gamesbacklog")
LIBRARY_PATH = os.path.join(DATA_DIR, "library.json")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
os.makedirs(COVERS_DIR, exist_ok=True)

STATUSES = ("playing", "backlog", "completed")


@dataclass
class Game:
    name: str
    status: str = "backlog"
    release_date: str | None = None
    cover: str | None = None
    skip_update: bool = False


@dataclass
class Library:
    games: list[Game] = field(default_factory=list)

    @classmethod
    def load(cls, path: str = LIBRARY_PATH) -> "Library":
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(games=[Game(**g) for g in data.get("games", [])])

    def save(self, path: str = LIBRARY_PATH) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"games": [asdict(g) for g in self.games]}, f, indent=2)
            f.write("\n")

    def by_status(self, status: str) -> list[Game]:
        games = [g for g in self.games if g.status == status]
        if status == "backlog":
            games.sort(key=lambda g: (g.release_date is None, g.release_date or ""))
        else:
            games.sort(key=lambda g: g.name.casefold())
        return games

    def find(self, name: str) -> Game | None:
        for g in self.games:
            if g.name.casefold() == name.casefold():
                return g
        return None

    def add(self, game: Game, overwrite_status: bool = False) -> None:
        """Adds a new game, or refreshes date/cover on an existing one by name.

        `overwrite_status` defaults to False so re-adding/refreshing an
        existing game (e.g. to pull fresh cover art) doesn't silently reset
        its status back to `game.status`'s default of "backlog".
        """
        existing = self.find(game.name)
        if existing:
            if overwrite_status:
                existing.status = game.status
            existing.release_date = game.release_date or existing.release_date
            existing.cover = game.cover or existing.cover
        else:
            self.games.append(game)

    def remove(self, name: str) -> bool:
        existing = self.find(name)
        if existing:
            self.games.remove(existing)
            return True
        return False
