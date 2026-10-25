"""Game definitions.

Only draws made under the CURRENT number matrix are analysed. Mixing in draws
from an older matrix (e.g. Mega Millions' Mega Ball pool of 25 before April 2025)
would make honest numbers look biased.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import comb


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    white_max: int
    white_count: int
    special_max: int
    special_name: str
    base_price: int  # USD per play
    era_start: date  # first drawing under the current matrix
    era_source: str
    dataset_id: str  # data.ny.gov dataset
    special_in_winning_numbers: bool  # Powerball's red ball is the 6th number in the field

    @property
    def jackpot_odds(self) -> int:
        return comb(self.white_max, self.white_count) * self.special_max

    @property
    def json_url(self) -> str:
        return f"https://data.ny.gov/resource/{self.dataset_id}.json?$limit=50000&$order=draw_date"

    @property
    def csv_url(self) -> str:
        return f"https://data.ny.gov/api/v3/views/{self.dataset_id}/export.csv?accessType=DOWNLOAD"


POWERBALL = Game(
    key="powerball",
    name="Powerball",
    white_max=69,
    white_count=5,
    special_max=26,
    special_name="Powerball",
    base_price=2,
    era_start=date(2015, 10, 7),
    era_source="Powerball moved to 69 white / 26 red balls beginning with the October 7, 2015 drawing",
    dataset_id="d6yy-54nr",
    special_in_winning_numbers=True,
)

MEGA_MILLIONS = Game(
    key="megamillions",
    name="Mega Millions",
    white_max=70,
    white_count=5,
    special_max=24,
    special_name="Mega Ball",
    base_price=5,
    era_start=date(2025, 4, 8),
    era_source="New Mega Millions ($5, Mega Ball 1-24): first drawing April 8, 2025",
    dataset_id="5xaw-6ayf",
    special_in_winning_numbers=False,
)

GAMES = {g.key: g for g in (POWERBALL, MEGA_MILLIONS)}
