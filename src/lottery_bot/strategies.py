"""Statistical pick strategies built from the draw history, plus a backtest.

Strategies
- balanced: random numbers, but only combinations whose "shape" matches what winning
  draws usually look like: total in the middle 80% of past sums, the most common
  odd/even split and low/high split. Most combinations have that shape, which is
  exactly why most winning draws do too.
- hot: each number's chance is proportional to how often it was drawn recently.
- cold: each number's chance is proportional to how rarely it was drawn recently.
- random: plain uniform random (the baseline to beat).

All strategies also apply the popular-pattern filter and the balanced shape filter.

Honest note: every individual combination has the same chance in a fair draw.
`backtest` replays history, picking each draw using only data from before it,
and compares each strategy's matches with what pure chance predicts.
"""

from __future__ import annotations

import random
import secrets
from bisect import insort
from collections import Counter, deque
from dataclasses import dataclass, field
from statistics import mean

from .data import Draw
from .games import Game
from .picks import Pick, popularity_flags

STRATEGIES = ("balanced", "hot", "cold", "random")
DEFAULT_WINDOW = 100  # recent draws used for hot / cold


@dataclass
class History:
    """Running statistics over past draws. Can be built at once or grown draw by draw."""

    game: Game
    window: int = DEFAULT_WINDOW
    sums: list[int] = field(default_factory=list)  # kept sorted
    odd_counts: Counter = field(default_factory=Counter)
    low_counts: Counter = field(default_factory=Counter)
    recent: deque = field(default_factory=deque)
    white_recent: Counter = field(default_factory=Counter)
    special_recent: Counter = field(default_factory=Counter)
    past: set = field(default_factory=set)
    n: int = 0

    @classmethod
    def from_draws(cls, game: Game, draws: list[Draw], window: int = DEFAULT_WINDOW) -> "History":
        h = cls(game=game, window=window)
        for d in draws:
            h.add(d)
        return h

    def add(self, d: Draw) -> None:
        g = self.game
        insort(self.sums, sum(d.whites))
        self.odd_counts[sum(w % 2 for w in d.whites)] += 1
        self.low_counts[sum(w <= g.white_max // 2 for w in d.whites)] += 1
        self.past.add(d.whites)
        self.recent.append(d)
        self.white_recent.update(d.whites)
        self.special_recent[d.special] += 1
        if len(self.recent) > self.window:
            old = self.recent.popleft()
            self.white_recent.subtract(old.whites)
            self.special_recent[old.special] -= 1
        self.n += 1

    # -- shape of typical winning draws -------------------------------------- #

    def sum_band(self) -> tuple[int, int]:
        s = self.sums
        return s[int(0.10 * (len(s) - 1))], s[int(0.90 * (len(s) - 1))]

    def common(self, counter: Counter, min_share: float = 0.15) -> set[int]:
        total = sum(counter.values())
        return {k for k, v in counter.items() if v / total >= min_share}

    def shape_ok(self, whites: tuple[int, ...]) -> bool:
        if self.n < 30:  # not enough history to describe a typical shape
            return True
        lo, hi = self.sum_band()
        g = self.game
        return (
            lo <= sum(whites) <= hi
            and sum(w % 2 for w in whites) in self.common(self.odd_counts)
            and sum(w <= g.white_max // 2 for w in whites) in self.common(self.low_counts)
        )

    def describe(self) -> list[str]:
        lo, hi = self.sum_band()
        odd = sorted(self.common(self.odd_counts))
        low = sorted(self.common(self.low_counts))
        half = self.game.white_max // 2
        return [
            f"Based on {self.n} past draws:",
            f"  typical total of the 5 white numbers: {lo} to {hi} (middle 80%)",
            f"  typical number of odd numbers: {', '.join(map(str, odd))}",
            f"  typical number of low numbers (1-{half}): {', '.join(map(str, low))}",
        ]

    # -- weights ------------------------------------------------------------- #

    def weights(self, strategy: str, special: bool) -> list[float]:
        g = self.game
        top = g.special_max if special else g.white_max
        counts = self.special_recent if special else self.white_recent
        if strategy == "hot":
            return [counts.get(i, 0) + 1.0 for i in range(1, top + 1)]
        if strategy == "cold":
            return [1.0 / (counts.get(i, 0) + 1.0) for i in range(1, top + 1)]
        return [1.0] * top


def _weighted_sample(k: int, weights: list[float], rng: random.Random) -> tuple[int, ...]:
    items = list(range(1, len(weights) + 1))
    w = list(weights)
    out = []
    for _ in range(k):
        i = rng.choices(range(len(items)), weights=w)[0]
        out.append(items.pop(i))
        w.pop(i)
    return tuple(sorted(out))


def stat_pick(h: History, strategy: str = "balanced", rng: random.Random | None = None,
              max_tries: int = 5000) -> Pick:
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}")
    rng = rng or secrets.SystemRandom()
    g = h.game
    ww = h.weights(strategy, special=False)
    for _ in range(max_tries):
        whites = _weighted_sample(g.white_count, ww, rng)
        if strategy == "random":
            break
        if h.shape_ok(whites) and not popularity_flags(whites, h.past):
            break
    else:
        raise RuntimeError("no pick passed the filters")
    special = rng.choices(range(1, g.special_max + 1), weights=h.weights(strategy, special=True))[0]
    return Pick(whites, special)


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #

@dataclass
class BacktestRow:
    strategy: str
    picks: int
    avg_white_matches: float
    special_hit_rate: float
    three_plus: int  # picks matching 3 or more white numbers


@dataclass
class BacktestReport:
    game: Game
    draws_tested: int
    picks_per_draw: int
    rows: list[BacktestRow]

    @property
    def expected_white_matches(self) -> float:
        g = self.game
        return g.white_count * g.white_count / g.white_max

    @property
    def expected_special_rate(self) -> float:
        return 1 / self.game.special_max


def backtest(draws: list[Draw], g: Game, picks_per_draw: int = 10, warmup: int = 50,
             window: int = DEFAULT_WINDOW, seed: int = 7) -> BacktestReport:
    """For each draw after `warmup`, pick using ONLY earlier draws, then score against it."""
    if len(draws) <= warmup + 10:
        raise ValueError(f"need more than {warmup + 10} draws to backtest")
    rng = random.Random(seed)
    h = History(game=g, window=window)
    for d in draws[:warmup]:
        h.add(d)
    stats = {s: {"w": [], "sp": 0, "3p": 0, "n": 0} for s in STRATEGIES}
    for d in draws[warmup:]:
        target = set(d.whites)
        for s in STRATEGIES:
            for _ in range(picks_per_draw):
                p = stat_pick(h, s, rng)
                m = len(target & set(p.whites))
                st = stats[s]
                st["w"].append(m)
                st["sp"] += p.special == d.special
                st["3p"] += m >= 3
                st["n"] += 1
        h.add(d)  # only now does this draw become "history"
    rows = [BacktestRow(s, st["n"], mean(st["w"]), st["sp"] / st["n"], st["3p"]) for s, st in stats.items()]
    return BacktestReport(g, len(draws) - warmup, picks_per_draw, rows)


def backtest_markdown(r: BacktestReport) -> str:
    g = r.game
    exp3 = expected_three_plus(g)
    lines = [
        f"# {g.name} strategy backtest",
        "",
        f"Replayed {r.draws_tested} past draws. Before each one, every strategy made "
        f"{r.picks_per_draw} picks using only the draws before it. Then the picks were scored.",
        "",
        "| Strategy | Picks | Avg white numbers matched | Pure chance | "
        f"{g.special_name} matched | Pure chance | 3+ white matches | Pure chance |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in r.rows:
        lines.append(
            f"| {row.strategy} | {row.picks:,} | {row.avg_white_matches:.3f} | {r.expected_white_matches:.3f} | "
            f"{row.special_hit_rate:.2%} | {r.expected_special_rate:.2%} | {row.three_plus} | "
            f"{exp3 * row.picks:.1f} |"
        )
    lines += [
        "",
        "How to read it: if a strategy had a real edge, its numbers would sit clearly above "
        "the pure-chance columns, and stay there when you rerun with a different `--seed`. "
        "Small differences that change from run to run are luck.",
    ]
    return "\n".join(lines) + "\n"


def expected_three_plus(g: Game) -> float:
    """Chance a random 5-number ticket matches 3 or more of the 5 drawn whites."""
    from math import comb
    total = comb(g.white_max, g.white_count)
    k = g.white_count
    return sum(comb(k, m) * comb(g.white_max - k, k - m) for m in range(3, k + 1)) / total
