"""Command line.

  lottery-bot fetch                     download official draw history (data.ny.gov)
  lottery-bot import FILE --game G      use a CSV/JSON you downloaded yourself
  lottery-bot audit [--sims N]          randomness audit -> reports/<game>-audit.md
  lottery-bot picks [--game G] [-n N]   secure random picks that avoid popular patterns
  lottery-bot payday                    the default plan for this payday + budget left
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


def _past(game, data_dir: Path) -> set:
    try:
        return {d.whites for d in data.load(game, data_dir)}
    except data.DataError:
        return set()


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
    pk.add_argument("--allow-popular", action="store_true")
    sub.add_parser("payday")
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
                print(f"{g.name} (odds stay 1 in {g.jackpot_odds:,}):")
                for p in generate(g, a.n, avoid_popular=not a.allow_popular, past=_past(g, a.data_dir)):
                    print(f"  {p}")
        else:
            ledger = Ledger(a.ledger)
            if a.cmd == "payday":
                print("This payday's plan: 1 Mega Millions ($5) + 1 Powerball ($2) + scratch card (up to $8)\n")
                for g in GAMES.values():
                    p = generate(g, 1, past=_past(g, a.data_dir))[0]
                    print(f"  {g.name}: {p}")
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
