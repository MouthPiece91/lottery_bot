"""Command line.

  lottery-bot fetch                     download official draw history (data.ny.gov)
  lottery-bot import FILE --game G      use a CSV/JSON you downloaded yourself
  lottery-bot audit [--sims N]          randomness audit -> reports/<game>-audit.md
  lottery-bot picks [--strategy S]      picks built from the draw history (balanced/hot/cold/random)
  lottery-bot payday [--strategy S]     this payday's picks + budget left
  lottery-bot backtest                  replay history: did any strategy beat pure chance?
  lottery-bot buy GAME [--cost X]       record a ticket (refused if over budget)
  lottery-bot win AMOUNT [--game G]     record a prize
  lottery-bot cashout AMOUNT            move winnings out of the ticket pool
  lottery-bot status                    budget, winnings pool, all-time net
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import data
from .audit import run_audit, to_markdown
from .games import GAMES
from .ledger import BudgetRefused, Ledger, cents, describe, money
from .picks import generate
from .strategies import DEFAULT_WINDOW, STRATEGIES, History, backtest, backtest_markdown, stat_pick


def _picks(game, data_dir: Path, strategy: str, n: int, window: int, show_profile: bool) -> None:
    try:
        h = History.from_draws(game, data.load(game, data_dir), window)
    except data.DataError:
        print(f"{game.name}: no history yet (run: lottery-bot fetch); using plain random picks")
        for p in generate(game, n):
            print(f"  {p}")
        return
    print(f"{game.name} - strategy: {strategy} (odds stay 1 in {game.jackpot_odds:,})")
    if show_profile:
        for line in h.describe():
            print(f"  {line}")
    seen = set()
    while len(seen) < n:
        p = stat_pick(h, strategy)
        if p.whites in seen:
            continue
        seen.add(p.whites)
        print(f"  {p}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lottery-bot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--ledger", type=Path, default=Path("ledger.json"))
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default today)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch")
    imp = sub.add_parser("import")
    imp.add_argument("file", type=Path)
    imp.add_argument("--game", choices=GAMES, required=True)
    au = sub.add_parser("audit")
    au.add_argument("--game", choices=GAMES)
    au.add_argument("--sims", type=int, default=500)
    au.add_argument("--out", type=Path, default=Path("reports"))
    pk = sub.add_parser("picks")
    pk.add_argument("--game", choices=GAMES)
    pk.add_argument("-n", type=int, default=1)
    pk.add_argument("--strategy", choices=STRATEGIES, default="balanced")
    pk.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="recent draws for hot/cold")
    pk.add_argument("--show-profile", action="store_true", help="print the historical shape used")
    pd = sub.add_parser("payday")
    pd.add_argument("--strategy", choices=STRATEGIES, default="balanced")
    pd.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    bt = sub.add_parser("backtest")
    bt.add_argument("--game", choices=GAMES)
    bt.add_argument("--picks-per-draw", type=int, default=10)
    bt.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    bt.add_argument("--seed", type=int, default=7)
    bt.add_argument("--out", type=Path, default=Path("reports"))
    by = sub.add_parser("buy")
    by.add_argument("game", help="powerball, megamillions, scratch, ...")
    by.add_argument("--cost", help="price in dollars (required for scratch cards)")
    by.add_argument("--note", default="")
    wn = sub.add_parser("win")
    wn.add_argument("amount")
    wn.add_argument("--game", default="")
    wn.add_argument("--note", default="")
    co = sub.add_parser("cashout")
    co.add_argument("amount")
    sub.add_parser("status")

    a = ap.parse_args(argv)
    today = a.date or date.today()
    games = [GAMES[a.game]] if getattr(a, "game", None) in GAMES else list(GAMES.values())

    try:
        if a.cmd == "fetch":
            for g in GAMES.values():
                path = data.save(g, data.fetch(g), a.data_dir)
                n = len(data.load(g, a.data_dir))
                print(f"{g.name}: saved {path} ({n} draws under current rules since {g.era_start})")
        elif a.cmd == "import":
            g = GAMES[a.game]
            text = a.file.read_text()
            data.current_era(data.parse_text(text, g), g)  # validate before saving
            print(f"{g.name}: imported {data.save(g, text, a.data_dir)}")
        elif a.cmd == "audit":
            a.out.mkdir(parents=True, exist_ok=True)
            for g in games:
                report = run_audit(data.load(g, a.data_dir), g, sims=a.sims)
                path = a.out / f"{g.key}-audit.md"
                path.write_text(to_markdown(report))
                print(f"{g.name}: {report.verdict}\n  full report: {path}")
        elif a.cmd == "picks":
            for g in games:
                _picks(g, a.data_dir, a.strategy, a.n, a.window, a.show_profile)
        elif a.cmd == "backtest":
            a.out.mkdir(parents=True, exist_ok=True)
            for g in games:
                print(f"{g.name}: replaying history, this can take a minute...")
                r = backtest(data.load(g, a.data_dir), g, a.picks_per_draw, window=a.window, seed=a.seed)
                path = a.out / f"{g.key}-backtest.md"
                text = backtest_markdown(r)
                path.write_text(text)
                print(text)
        else:
            ledger = Ledger(a.ledger)
            if a.cmd == "payday":
                print("This payday's plan: 1 Mega Millions ($5) + 1 Powerball ($2) + scratch card (up to $8)\n")
                for g in (GAMES["megamillions"], GAMES["powerball"]):
                    _picks(g, a.data_dir, a.strategy, 1, a.window, False)
                print()
                print(describe(ledger.status(today), ledger.config["budget_per_period_cents"]))
            elif a.cmd == "buy":
                e = ledger.buy(a.game, today, cents(a.cost) if a.cost else None, a.note)
                ledger.save()
                print(f"Recorded {a.game} {money(e['cents'])} paid from {e['source']}.")
                print(describe(ledger.status(today), ledger.config["budget_per_period_cents"]))
            elif a.cmd == "win":
                ledger.win(cents(a.amount), today, a.game, a.note)
                ledger.save()
                print(describe(ledger.status(today), ledger.config["budget_per_period_cents"]))
            elif a.cmd == "cashout":
                ledger.cashout(cents(a.amount), today)
                ledger.save()
                print(describe(ledger.status(today), ledger.config["budget_per_period_cents"]))
            elif a.cmd == "status":
                print(describe(ledger.status(today), ledger.config["budget_per_period_cents"]))
    except (BudgetRefused, data.DataError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
