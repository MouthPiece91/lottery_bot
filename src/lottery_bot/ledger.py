"""Budget ledger with hard limits.

Your rules, enforced in code:
- Paydays are mid-month and end of month, so each half-month (1st-15th, 16th-end)
  gets one budget of $15 of your own money. Unused budget does NOT carry over.
- Default plan per payday: 1 Mega Millions ($5) + 1 Powerball ($2) + a scratch card.
- Extra tickets can only be paid from winnings. If both the period budget and the
  winnings pool are short, the purchase is refused.

Amounts are stored in cents so totals never drift.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

DEFAULT_CONFIG = {
    "budget_per_period_cents": 1500,
    "prices_cents": {"megamillions": 500, "powerball": 200},
}


class BudgetRefused(Exception):
    pass


def cents(amount: str | float | int | Decimal) -> int:
    d = Decimal(str(amount))
    if d <= 0:
        raise ValueError("amount must be positive")
    if d != d.quantize(Decimal("0.01")):
        raise ValueError("amount can have at most 2 decimal places")
    return int(d * 100)


def money(c: int) -> str:
    sign = "-" if c < 0 else ""
    return f"{sign}${abs(c) / 100:,.2f}"


def period_of(d: date) -> tuple[date, date]:
    """The half-month a date falls in: 1st-15th or 16th-last day."""
    if d.day <= 15:
        return date(d.year, d.month, 1), date(d.year, d.month, 15)
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 16), date(d.year, d.month, last)


@dataclass
class Status:
    period: tuple[date, date]
    budget_left: int
    winnings_pool: int
    own_money_spent: int
    winnings_spent: int
    total_won: int
    cashed_out: int

    @property
    def net(self) -> int:
        """All prizes minus all money you put in. Negative = what lottery has cost you."""
        return self.total_won - self.own_money_spent


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {"config": DEFAULT_CONFIG, "entries": []}
        self.config = data["config"]
        self.entries: list[dict] = data["entries"]

    def save(self) -> None:
        self.path.write_text(json.dumps({"config": self.config, "entries": self.entries}, indent=2))

    # ---- queries -------------------------------------------------------- #

    def _sum(self, kind: str, source: str | None = None, within: tuple[date, date] | None = None) -> int:
        total = 0
        for e in self.entries:
            if e["kind"] != kind or (source and e.get("source") != source):
                continue
            if within and not within[0] <= date.fromisoformat(e["date"]) <= within[1]:
                continue
            total += e["cents"]
        return total

    def status(self, on: date) -> Status:
        p = period_of(on)
        spent_now = self._sum("buy", "budget", p)
        pool = self._sum("win") - self._sum("buy", "winnings") - self._sum("cashout")
        return Status(
            period=p,
            budget_left=self.config["budget_per_period_cents"] - spent_now,
            winnings_pool=pool,
            own_money_spent=self._sum("buy", "budget"),
            winnings_spent=self._sum("buy", "winnings"),
            total_won=self._sum("win"),
            cashed_out=self._sum("cashout"),
        )

    # ---- actions -------------------------------------------------------- #

    def buy(self, game: str, on: date, cost_cents: int | None = None, note: str = "") -> dict:
        if cost_cents is None:
            prices = self.config["prices_cents"]
            if game not in prices:
                raise ValueError(f"give a cost for '{game}' (e.g. a scratch card's price)")
            cost_cents = prices[game]
        s = self.status(on)
        if cost_cents <= s.budget_left:
            source = "budget"
        elif cost_cents <= s.winnings_pool:
            source = "winnings"
        else:
            raise BudgetRefused(
                f"Refused: {game} costs {money(cost_cents)}. This pay period has {money(s.budget_left)} "
                f"left and your winnings pool has {money(s.winnings_pool)}. Wait for the next payday."
            )
        entry = {"kind": "buy", "date": on.isoformat(), "game": game, "cents": cost_cents,
                 "source": source, "note": note}
        self.entries.append(entry)
        return entry

    def win(self, amount_cents: int, on: date, game: str = "", note: str = "") -> dict:
        entry = {"kind": "win", "date": on.isoformat(), "game": game, "cents": amount_cents, "note": note}
        self.entries.append(entry)
        return entry

    def cashout(self, amount_cents: int, on: date, note: str = "") -> dict:
        pool = self.status(on).winnings_pool
        if amount_cents > pool:
            raise BudgetRefused(f"Refused: winnings pool is only {money(pool)}.")
        entry = {"kind": "cashout", "date": on.isoformat(), "cents": amount_cents, "note": note}
        self.entries.append(entry)
        return entry


def describe(s: Status, budget_per_period: int) -> str:
    start, end = s.period
    yearly = budget_per_period * 24
    lines = [
        f"Pay period {start:%b %d} - {end:%b %d}: {money(s.budget_left)} of {money(budget_per_period)} left",
        f"Winnings pool (only source for extra tickets): {money(s.winnings_pool)}",
        "",
        f"All-time own money spent:   {money(s.own_money_spent)}",
        f"All-time prizes won:        {money(s.total_won)}",
        f"Spent from winnings:        {money(s.winnings_spent)}",
        f"Cashed out to keep:         {money(s.cashed_out)}",
        f"Net (prizes - own money):   {money(s.net)}",
        "",
        f"Your cap: {money(budget_per_period)} x 24 paydays = {money(yearly)} a year, at most.",
    ]
    return "\n".join(lines)
