"""Pick generator.

Every combination has exactly the same chance of winning. These filters do NOT
improve your odds. They only steer away from combinations many other people play
(birthdays, sequences, patterns), so that IF you win, you are less likely to split
the jackpot. Numbers come from the operating system's secure random source.
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass

from .games import Game

BIRTHDAY_MAX = 31


@dataclass(frozen=True)
class Pick:
    whites: tuple[int, ...]
    special: int

    def __str__(self) -> str:
        return " ".join(f"{w:02d}" for w in self.whites) + f"  +  {self.special:02d}"


def popularity_flags(whites: tuple[int, ...], past: set[tuple[int, ...]] | None = None) -> list[str]:
    """Reasons a set of white numbers looks like something many people would pick."""
    w = sorted(whites)
    flags = []
    if all(x <= BIRTHDAY_MAX for x in w):
        flags.append("all numbers are 31 or lower (birthday picks)")
    run = longest = 1
    for a, b in zip(w, w[1:]):
        run = run + 1 if b == a + 1 else 1
        longest = max(longest, run)
    if longest >= 3:
        flags.append(f"{longest} consecutive numbers")
    steps = {b - a for a, b in zip(w, w[1:])}
    if len(steps) == 1:
        flags.append("evenly spaced pattern")
    endings = [x % 10 for x in w]
    if max(endings.count(e) for e in set(endings)) >= 4:
        flags.append("4+ numbers share a last digit")
    decades = [x // 10 for x in w]
    if max(decades.count(d) for d in set(decades)) >= 4:
        flags.append("4+ numbers in the same ten-block (row of the play slip)")
    if past and tuple(w) in past:
        flags.append("a previous winning combination")
    return flags


def generate(g: Game, count: int = 1, avoid_popular: bool = True,
             past: set[tuple[int, ...]] | None = None, rng: random.Random | None = None,
             max_tries: int = 10_000) -> list[Pick]:
    rng = rng or secrets.SystemRandom()
    out: list[Pick] = []
    seen: set[tuple[int, ...]] = set()
    for _ in range(count):
        for _ in range(max_tries):
            whites = tuple(sorted(rng.sample(range(1, g.white_max + 1), g.white_count)))
            if whites in seen:
                continue
            if avoid_popular and popularity_flags(whites, past):
                continue
            break
        else:
            raise RuntimeError("could not find a pick that passes the filters")
        seen.add(whites)
        out.append(Pick(whites, rng.randint(1, g.special_max)))
    return out
