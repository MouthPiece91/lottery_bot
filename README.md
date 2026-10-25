# lottery_bot

A personal toolkit for Powerball and Mega Millions. **It does not predict numbers,
and nothing can.** The drawings use physical ball machines, with machines and ball
sets chosen at random before each draw and independent auditors present. Every
combination has the same odds:

| Game | Pick | Price | Jackpot odds |
| --- | --- | --- | --- |
| Powerball | 5 of 1-69 + 1 of 1-26 | $2 | 1 in 292,201,338 |
| Mega Millions | 5 of 1-70 + 1 of 1-24 | $5 | 1 in 290,472,336 |

What it does instead:

1. **Randomness audit.** Downloads the official draw history and tests whether the
   draws behave like fair random draws: number frequency, special-ball frequency,
   repeated pairs, carry-over from the previous draw, and the average sum. Each test
   is compared against hundreds of simulated fair histories, with a correction for
   running five tests at once. The report also says how big a bias the data could
   even detect.
2. **Split-avoiding picks.** Secure random numbers that skip combinations many
   people play (all birthdays, sequences, evenly spaced patterns, slip rows, past
   winners). This does not change your odds of winning. It lowers the chance of
   sharing a jackpot if you do win.
3. **Statistical picks from the draw history.** Four strategies:
   - `balanced`: only combinations shaped like typical past draws (total in the
     middle 80% of past sums, the usual odd/even and low/high splits)
   - `hot`: numbers drawn more often recently get a bigger chance
   - `cold`: numbers drawn less often recently get a bigger chance
   - `random`: plain random, the baseline
   `lottery-bot backtest` replays every past draw, picking each one using only the
   draws before it, and compares every strategy with pure chance. Every
   combination has the same odds in a fair draw; the backtest lets the data show it.
4. **Budget ledger with hard limits.** $15 of your own money per payday
   (1st-15th and 16th-end of month), unused money never carries over, and extra
   tickets can only be paid from winnings. Anything over budget is refused.

## Setup

```bash
git clone https://github.com/MouthPiece91/lottery_bot
cd lottery_bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
pytest -q
```

## Use

```bash
lottery-bot fetch            # official history from New York State Open Data
lottery-bot audit            # writes reports/powerball-audit.md and reports/megamillions-audit.md
lottery-bot payday           # this payday's picks (balanced) + budget left
lottery-bot payday --strategy hot
lottery-bot picks --strategy cold -n 3 --show-profile
lottery-bot backtest         # writes reports/<game>-backtest.md

lottery-bot buy megamillions
lottery-bot buy powerball
lottery-bot buy scratch --cost 8
lottery-bot win 4 --game scratch      # prize goes to the winnings pool
lottery-bot buy powerball             # paid from winnings, since the $15 is used
lottery-bot cashout 10                # take winnings home
lottery-bot status                    # all-time spent, won and net
```

If `fetch` cannot reach the site, download the CSVs yourself and import them:
[Powerball](https://data.ny.gov/api/v3/views/d6yy-54nr/export.csv?accessType=DOWNLOAD) and
[Mega Millions](https://data.ny.gov/api/v3/views/5xaw-6ayf/export.csv?accessType=DOWNLOAD), then
`lottery-bot import <file> --game powerball` (or `megamillions`).

## Notes

- Only draws under the current rules are analysed: Powerball since 2015-10-07,
  Mega Millions since 2025-04-08. Mega Millions therefore has a short history, so
  its audit can only detect large biases.
- Your ledger (`ledger.json`), downloaded data and reports stay on your computer;
  they are git-ignored.
- Prices are the base play. Power Play or other add-ons cost extra; record them with `--cost`.
