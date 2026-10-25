import json
import random
from datetime import date, timedelta

import pytest

from lottery_bot import data
from lottery_bot.audit import run_audit, simulate, to_markdown
from lottery_bot.cli import main
from lottery_bot.games import MEGA_MILLIONS, POWERBALL
from lottery_bot.ledger import BudgetRefused, Ledger, cents, period_of
from lottery_bot.picks import generate, popularity_flags


# ---------------- games ---------------- #

def test_jackpot_odds_match_published_figures():
    assert POWERBALL.jackpot_odds == 292_201_338
    assert MEGA_MILLIONS.jackpot_odds == 290_472_336


# ---------------- data parsing (formats taken from data.ny.gov column samples) ---------------- #

def test_parse_powerball_json_row():
    d = data.parse_row({"draw_date": "2025-11-15T00:00:00.000", "winning_numbers": "09 29 40 44 54 07",
                        "multiplier": "2"}, POWERBALL)
    assert d == data.Draw(date(2025, 11, 15), (9, 29, 40, 44, 54), 7)


def test_parse_mega_millions_csv_with_unpadded_mega_ball():
    text = "Draw Date,Winning Numbers,Mega Ball,Multiplier\n10/21/2025,56 66 67 68 69,9,\n"
    (d,) = data.parse_text(text, MEGA_MILLIONS)
    assert d == data.Draw(date(2025, 10, 21), (56, 66, 67, 68, 69), 9)


def test_era_filter_drops_old_rules_and_rejects_impossible_numbers():
    old = data.Draw(date(2025, 4, 4), (1, 2, 3, 4, 5), 25)  # old Mega Ball pool went to 25
    new = data.Draw(date(2025, 4, 8), (1, 2, 3, 4, 5), 24)
    assert data.current_era([old, new], MEGA_MILLIONS) == [new]
    with pytest.raises(data.DataError):
        data.current_era([data.Draw(date(2025, 5, 1), (1, 2, 3, 4, 5), 25)], MEGA_MILLIONS)


# ---------------- audit ---------------- #

def _draws(whites, specials, start=date(2016, 1, 1)):
    return [data.Draw(start + timedelta(days=3 * i), w, s) for i, (w, s) in enumerate(zip(whites, specials))]


def test_fair_draws_pass():
    w, s = simulate(POWERBALL, 600, random.Random(1))
    report = run_audit(_draws(w, s), POWERBALL, sims=200)
    assert not any(t.suspicious for t in report.results)
    assert "CONSISTENT WITH RANDOM" in report.verdict


def test_audit_catches_a_rigged_number():
    rng = random.Random(2)
    w, s = simulate(POWERBALL, 600, rng)
    rigged = []
    for d in w:  # force 7 into 30% of draws (fair rate is about 7%)
        if 7 not in d and rng.random() < 0.25:
            d = tuple(sorted((7,) + d[1:]))
        rigged.append(d)
    report = run_audit(_draws(rigged, s), POWERBALL, sims=200)
    freq = next(t for t in report.results if t.name == "white_frequency")
    assert freq.suspicious
    assert "SUSPICIOUS" in to_markdown(report)


def test_audit_catches_repeating_numbers():
    rng = random.Random(3)
    w, s = simulate(POWERBALL, 400, rng)
    sticky = [w[0]]
    for d in w[1:]:  # carry two numbers over from the previous draw every time
        keep = set(sticky[-1][:2])
        rest = [x for x in d if x not in keep][:3]
        while len(rest) < 3:
            x = rng.randint(1, 69)
            if x not in keep and x not in rest:
                rest.append(x)
        sticky.append(tuple(sorted(keep | set(rest))))
    report = run_audit(_draws(sticky, s), POWERBALL, sims=200)
    assert next(t for t in report.results if t.name == "repeat_from_previous").suspicious


def test_audit_refuses_tiny_samples():
    w, s = simulate(MEGA_MILLIONS, 10, random.Random(4))
    with pytest.raises(ValueError):
        run_audit(_draws(w, s, date(2025, 5, 1)), MEGA_MILLIONS)


# ---------------- picks ---------------- #

@pytest.mark.parametrize("whites,expected", [
    ((3, 7, 12, 19, 28), "birthday"),
    ((10, 11, 12, 40, 55), "consecutive"),
    ((5, 15, 25, 35, 45), "evenly spaced"),
    ((40, 41, 43, 47, 66), "same ten-block"),
])
def test_popular_patterns_are_flagged(whites, expected):
    assert any(expected in f for f in popularity_flags(whites))


def test_generated_picks_are_valid_unique_and_unpopular():
    past = {(4, 18, 33, 47, 60)}
    picks = generate(POWERBALL, 50, past=past, rng=random.Random(5))
    assert len({p.whites for p in picks}) == 50
    for p in picks:
        assert len(set(p.whites)) == 5 and all(1 <= x <= 69 for x in p.whites)
        assert 1 <= p.special <= 26
        assert popularity_flags(p.whites, past) == []


# ---------------- ledger ---------------- #

def test_periods_split_at_the_15th():
    assert period_of(date(2026, 10, 15)) == (date(2026, 10, 1), date(2026, 10, 15))
    assert period_of(date(2026, 2, 16)) == (date(2026, 2, 16), date(2026, 2, 28))


def test_default_payday_plan_fits_15_dollars(tmp_path):
    led = Ledger(tmp_path / "l.json")
    d = date(2026, 10, 15)
    led.buy("megamillions", d)
    led.buy("powerball", d)
    led.buy("scratch", d, cents("8"))
    assert led.status(d).budget_left == 0
    with pytest.raises(BudgetRefused):
        led.buy("powerball", d)


def test_extra_tickets_only_from_winnings_and_budget_resets(tmp_path):
    led = Ledger(tmp_path / "l.json")
    d = date(2026, 10, 30)
    led.buy("scratch", d, cents("15"))
    led.win(cents("4"), d, "scratch")
    assert led.buy("powerball", d)["source"] == "winnings"
    s = led.status(d)
    assert s.winnings_pool == 200 and s.own_money_spent == 1500 and s.net == 400 - 1500
    with pytest.raises(BudgetRefused):
        led.buy("megamillions", d)  # $5 > $2 left in winnings
    # Next payday: fresh $15, unused money never carries over.
    assert led.status(date(2026, 11, 1)).budget_left == 1500


def test_cashout_limited_to_pool(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.win(cents("10"), date(2026, 10, 30))
    with pytest.raises(BudgetRefused):
        led.cashout(cents("11"), date(2026, 10, 30))
    led.cashout(cents("10"), date(2026, 10, 30))
    assert led.status(date(2026, 10, 30)).winnings_pool == 0


def test_amounts_validated():
    with pytest.raises(ValueError):
        cents("-1")
    with pytest.raises(ValueError):
        cents("1.005")


# ---------------- CLI end to end ---------------- #

def test_cli_import_audit_and_budget(tmp_path, capsys):
    w, s = simulate(MEGA_MILLIONS, 120, random.Random(6))
    rows = [{"draw_date": (date(2025, 4, 8) + timedelta(days=3 * i)).isoformat() + "T00:00:00.000",
             "winning_numbers": " ".join(f"{x:02d}" for x in d), "mega_ball": str(m)}
            for i, (d, m) in enumerate(zip(w, s))]
    f = tmp_path / "mm.json"
    f.write_text(json.dumps(rows))
    base = ["--data-dir", str(tmp_path / "data"), "--ledger", str(tmp_path / "ledger.json"), "--date", "2026-10-31"]
    assert main(base + ["import", str(f), "--game", "megamillions"]) == 0
    assert main(base + ["audit", "--game", "megamillions", "--sims", "100", "--out", str(tmp_path / "r")]) == 0
    assert (tmp_path / "r" / "megamillions-audit.md").exists()
    assert main(base + ["buy", "megamillions"]) == 0
    assert main(base + ["buy", "scratch", "--cost", "11"]) == 1  # $10 left: refused
    assert "Refused" in capsys.readouterr().err


# ---------------- statistical strategies ---------------- #

from lottery_bot.strategies import History, backtest, expected_three_plus, stat_pick


def _hist(n=300, seed=8):
    w, s = simulate(POWERBALL, n, random.Random(seed))
    return _draws(w, s)


def test_balanced_picks_match_historical_shape():
    h = History.from_draws(POWERBALL, _hist())
    lo, hi = h.sum_band()
    for _ in range(50):
        p = stat_pick(h, "balanced", random.Random())
        assert lo <= sum(p.whites) <= hi and h.shape_ok(p.whites)
        assert not popularity_flags(p.whites, h.past)
        assert 1 <= p.special <= POWERBALL.special_max


def test_hot_strategy_favours_frequent_numbers():
    draws = _hist(200)
    # make 7 very "hot" in the recent window
    draws = [data.Draw(d.draw_date, tuple(sorted({7, *d.whites[1:]})) if 7 not in d.whites else d.whites, d.special)
             for d in draws]
    h = History.from_draws(POWERBALL, draws, window=100)
    rng = random.Random(9)
    hot = sum(7 in stat_pick(h, "hot", rng).whites for _ in range(400))
    cold = sum(7 in stat_pick(h, "cold", rng).whites for _ in range(400))
    assert hot > cold


def test_backtest_uses_only_past_data_and_reports_chance_levels():
    draws = _hist(200)
    r = backtest(draws, POWERBALL, picks_per_draw=3, warmup=50)
    assert r.draws_tested == 150
    assert {row.strategy for row in r.rows} == {"balanced", "hot", "cold", "random"}
    assert abs(r.expected_white_matches - 25 / 69) < 1e-9
    for row in r.rows:  # on fair draws every strategy should sit near chance
        assert abs(row.avg_white_matches - r.expected_white_matches) < 0.08


def test_three_plus_probability():
    # P(match >=3 of 5 from 69) = (C(5,3)C(64,2)+C(5,4)C(64,1)+1)/C(69,5)
    from math import comb
    exp = (comb(5, 3) * comb(64, 2) + comb(5, 4) * 64 + 1) / comb(69, 5)
    assert abs(expected_three_plus(POWERBALL) - exp) < 1e-15
