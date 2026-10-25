"""Randomness audit.

Question it answers: do the official draws look like fair, independent random draws?

Method: for each statistic, simulate many histories of the same length drawn
perfectly at random under the game's rules, and ask how often a fair history is at
least as extreme as the real one (a Monte Carlo p-value). Because five tests run at
once, a result only counts as suspicious below alpha / 5 (Bonferroni correction).

Passing does not prove fairness; it means no bias large enough to detect with this
many draws. The report states how big a bias would have to be to be detected.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from math import sqrt
from statistics import mean

from .data import Draw
from .games import Game

TESTS = {
    "white_frequency": "Are all white numbers drawn equally often? (chi-square)",
    "special_frequency": "Is every {special} drawn equally often? (chi-square)",
    "max_pair": "Does any pair of white numbers show up together too often?",
    "repeat_from_previous": "Do numbers carry over from the previous draw more or less than chance?",
    "white_sum": "Is the average sum of the white numbers where chance puts it?",
}


@dataclass
class TestResult:
    name: str
    question: str
    observed: float
    fair_mean: float
    p_value: float
    suspicious: bool


@dataclass
class AuditReport:
    game: Game
    n_draws: int
    first: str
    last: str
    sims: int
    alpha: float
    results: list[TestResult]
    white_counts: Counter
    special_counts: Counter
    detectable_extra: float  # extra appearances one number needs before it would be flagged
    max_count_fair_range: tuple[int, int]

    @property
    def verdict(self) -> str:
        if any(r.suspicious for r in self.results):
            return "SUSPICIOUS: at least one test is outside what fair draws produce. Re-check the data before concluding anything."
        return "CONSISTENT WITH RANDOM: no test found a pattern beyond what fair draws produce."


def _stats(whites: list[tuple[int, ...]], specials: list[int], g: Game) -> dict[str, float]:
    n = len(whites)
    wc = Counter(w for d in whites for w in d)
    ew = n * g.white_count / g.white_max
    sc = Counter(specials)
    es = n / g.special_max
    pairs = Counter(p for d in whites for p in combinations(d, 2))
    overlaps = [len(set(a) & set(b)) for a, b in zip(whites, whites[1:])]
    return {
        "white_frequency": sum((wc.get(i, 0) - ew) ** 2 / ew for i in range(1, g.white_max + 1)),
        "special_frequency": sum((sc.get(i, 0) - es) ** 2 / es for i in range(1, g.special_max + 1)),
        "max_pair": max(pairs.values()) if pairs else 0,
        "repeat_from_previous": mean(overlaps) if overlaps else 0.0,
        "white_sum": mean(sum(d) for d in whites),
        "_max_white_count": max(wc.values()) if wc else 0,
    }


TWO_SIDED = {"repeat_from_previous", "white_sum"}


def simulate(g: Game, n: int, rng: random.Random) -> tuple[list[tuple[int, ...]], list[int]]:
    pool = range(1, g.white_max + 1)
    whites = [tuple(sorted(rng.sample(pool, g.white_count))) for _ in range(n)]
    specials = [rng.randint(1, g.special_max) for _ in range(n)]
    return whites, specials


def run_audit(draws: list[Draw], g: Game, sims: int = 500, alpha: float = 0.05, seed: int = 2026) -> AuditReport:
    if len(draws) < 30:
        raise ValueError(f"Only {len(draws)} draws; need at least 30 for a meaningful audit.")
    whites = [d.whites for d in draws]
    specials = [d.special for d in draws]
    obs = _stats(whites, specials, g)

    rng = random.Random(seed)
    sim_stats = [_stats(*simulate(g, len(draws), rng), g) for _ in range(sims)]

    threshold = alpha / len(TESTS)
    results = []
    for name, question in TESTS.items():
        vals = [s[name] for s in sim_stats]
        centre = mean(vals)
        if name in TWO_SIDED:
            extreme = sum(abs(v - centre) >= abs(obs[name] - centre) for v in vals)
        else:
            extreme = sum(v >= obs[name] for v in vals)
        p = (1 + extreme) / (1 + sims)
        results.append(TestResult(name, question.format(special=g.special_name), obs[name], centre, p, p < threshold))

    n = len(draws)
    p_one = g.white_count / g.white_max
    sd = sqrt(n * p_one * (1 - p_one))
    max_counts = sorted(s["_max_white_count"] for s in sim_stats)
    lo, hi = max_counts[int(0.025 * sims)], max_counts[min(sims - 1, int(0.975 * sims))]
    return AuditReport(
        game=g, n_draws=n, first=str(draws[0].draw_date), last=str(draws[-1].draw_date),
        sims=sims, alpha=alpha, results=results,
        white_counts=Counter(w for d in whites for w in d), special_counts=Counter(specials),
        detectable_extra=3.5 * sd,  # ~3.5 sd is needed once you correct for testing every number
        max_count_fair_range=(lo, hi),
    )


def to_markdown(r: AuditReport) -> str:
    g = r.game
    expected = r.n_draws * g.white_count / g.white_max
    hot = r.white_counts.most_common(5)
    cold = sorted(((i, r.white_counts.get(i, 0)) for i in range(1, g.white_max + 1)), key=lambda x: x[1])[:5]
    lines = [
        f"# {g.name} randomness audit",
        "",
        f"**{r.verdict}**",
        "",
        f"- Draws analysed: {r.n_draws} ({r.first} to {r.last}), current rules only: "
        f"5 of 1-{g.white_max} + {g.special_name} 1-{g.special_max}",
        f"- Fair histories simulated per test: {r.sims}",
        f"- A test counts as suspicious below p = {r.alpha / len(TESTS):.3f} ({r.alpha} split across {len(TESTS)} tests)",
        "",
        "| Test | Question | Real draws | Fair average | p-value | Suspicious? |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for t in r.results:
        lines.append(f"| {t.name} | {t.question} | {t.observed:.3f} | {t.fair_mean:.3f} | {t.p_value:.3f} | "
                     f"{'YES' if t.suspicious else 'no'} |")
    lo, hi = r.max_count_fair_range
    lines += [
        "",
        "## \"Hot\" and \"cold\" numbers",
        "",
        f"Each white number is expected about {expected:.1f} times. "
        f"Most drawn: {', '.join(f'{n} ({c})' for n, c in hot)}. "
        f"Least drawn: {', '.join(f'{n} ({c})' for n, c in cold)}.",
        "",
        f"In fair simulated histories, the most-drawn number appears between {lo} and {hi} times "
        f"(95% range). A \"hot\" number inside that range is just normal randomness and says nothing "
        f"about the next draw.",
        "",
        "## How big a bias could this detect?",
        "",
        f"With {r.n_draws} draws, a single number would need roughly {r.detectable_extra:.0f} extra "
        f"appearances (about {expected + r.detectable_extra:.0f} instead of {expected:.0f}) before it "
        f"could be flagged. Smaller biases, if any exist, are invisible with this much data. Machines "
        f"and ball sets are also rotated at random, which would wash out any one machine's quirk.",
        "",
        f"Jackpot odds per play: 1 in {g.jackpot_odds:,}. Nothing in this report changes them.",
    ]
    return "\n".join(lines) + "\n"
