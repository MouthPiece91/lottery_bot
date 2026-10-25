"""Download and parse official draw history from New York State Open Data (data.ny.gov).

The parser accepts both the JSON API (fieldName keys, ISO dates) and the CSV export
(display-name headers, MM/DD/YYYY dates), so a manually downloaded file works too.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .games import Game


@dataclass(frozen=True)
class Draw:
    draw_date: date
    whites: tuple[int, ...]  # sorted
    special: int


class DataError(ValueError):
    pass


def _parse_date(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise DataError(f"unrecognised date: {s!r}")


def _get(row: dict, *keys: str) -> str | None:
    lowered = {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for k in keys:
        v = lowered.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def parse_row(row: dict, game: Game) -> Draw:
    d = _get(row, "draw_date")
    nums = _get(row, "winning_numbers")
    if d is None or nums is None:
        raise DataError(f"row missing date or numbers: {row}")
    values = [int(x) for x in nums.split()]
    if game.special_in_winning_numbers:
        if len(values) != game.white_count + 1:
            raise DataError(f"expected {game.white_count + 1} numbers, got {nums!r}")
        whites, special = values[:-1], values[-1]
    else:
        mb = _get(row, "mega_ball")
        if mb is None or len(values) != game.white_count:
            raise DataError(f"bad row: {row}")
        whites, special = values, int(mb)
    return Draw(_parse_date(d), tuple(sorted(whites)), special)


def parse_rows(rows: list[dict], game: Game) -> list[Draw]:
    return sorted((parse_row(r, game) for r in rows), key=lambda x: x.draw_date)


def parse_text(text: str, game: Game) -> list[Draw]:
    text = text.lstrip("﻿")
    if text.lstrip().startswith("["):
        return parse_rows(json.loads(text), game)
    return parse_rows(list(csv.DictReader(io.StringIO(text))), game)


def current_era(draws: list[Draw], game: Game) -> list[Draw]:
    """Keep only draws under the current matrix, and fail loudly on any impossible number."""
    out = [d for d in draws if d.draw_date >= game.era_start]
    for d in out:
        bad = (
            len(set(d.whites)) != game.white_count
            or not all(1 <= w <= game.white_max for w in d.whites)
            or not 1 <= d.special <= game.special_max
        )
        if bad:
            raise DataError(f"{game.name} draw on {d.draw_date} is outside the current rules: {d}")
    return out


def fetch(game: Game, timeout: int = 30) -> str:
    req = urllib.request.Request(game.json_url, headers={"User-Agent": "lottery-bot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
        return resp.read().decode("utf-8")


def load(game: Game, data_dir: Path) -> list[Draw]:
    path = data_dir / f"{game.key}.data"
    if not path.exists():
        raise DataError(f"No data for {game.name}. Run: lottery-bot fetch")
    return current_era(parse_text(path.read_text(), game), game)


def save(game: Game, text: str, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{game.key}.data"
    path.write_text(text)
    return path
