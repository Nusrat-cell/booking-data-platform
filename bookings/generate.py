"""Synthetic event-travel bookings: the exports a booking platform would produce.

One day at a time, each day from its own seed, so a backfill and a day by day run give
the same data. Some problems are planted on purpose (see PLANTED).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

START = dt.date(2026, 6, 1)

EVENTS = [  # id, name, city, country, kind, ticket price per person (EUR)
    ("E01", "Phantasialand", "Bruehl", "DE", "theme park", 62),
    ("E02", "Europa-Park", "Rust", "DE", "theme park", 64),
    ("E03", "Disneyland Paris", "Paris", "FR", "theme park", 78),
    ("E04", "Efteling", "Kaatsheuvel", "NL", "theme park", 49),
    ("E05", "The Lion King", "Hamburg", "DE", "musical", 95),
    ("E06", "Hamilton", "Hamburg", "DE", "musical", 110),
    ("E07", "MJ The Musical", "Berlin", "DE", "musical", 98),
    ("E08", "Cirque du Soleil", "Vienna", "AT", "show", 105),
    ("E09", "Tomorrowland", "Boom", "BE", "festival", 230),
    ("E10", "Oktoberfest", "Munich", "DE", "festival", 40),
    ("E11", "Legoland", "Billund", "DK", "theme park", 59),
    ("E12", "Movie Park", "Bottrop", "DE", "theme park", 45),
]
CHANNELS = {  # channel: (share of visitors, conversion rate, daily spend EUR)
    "google_cpc": (0.30, 0.021, 900),
    "meta_ads": (0.22, 0.012, 650),
    "newsletter": (0.10, 0.045, 40),
    "organic": (0.20, 0.018, 0),
    "direct": (0.12, 0.030, 0),
    "affiliate": (0.06, 0.016, 160),
}
CURRENCIES = {"EUR": 1.0, "DKK": 0.134, "GBP": 1.16, "CHF": 1.06}
PLANTED = {
    "duplicate": "a booking line exported twice",
    "cancel": "a booking exported again as cancelled",
    "unknown_event": "a booking for an event id that does not exist",
    "bad_persons": "a booking with zero persons",
    "no_channel": "a visit with no channel",
    "fx_gap": "a CHF booking on a day with no CHF rate",
}


def _rng(day: dt.date, salt: str = "") -> random.Random:
    return random.Random(int(hashlib.sha256(f"{day}{salt}".encode()).hexdigest()[:12], 16))


def season(day: dt.date) -> float:
    return 1.0 + 0.35 * (day.weekday() in (4, 5)) + 0.25 * (day.month in (7, 8)) + 0.2 * (day.month == 10)


def generate_day(day: dt.date, root: Path) -> dict:
    """Write one day of files under root/landing/<date>/ and return row counts."""
    rng = _rng(day)
    out = root / "landing" / day.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    visitors = int(1800 * season(day) * rng.uniform(0.9, 1.1))
    touches, bookings, n = [], [], 0
    names, weights = list(CHANNELS), [CHANNELS[c][0] for c in CHANNELS]
    for v in range(visitors):
        vid = f"v{day:%y%m%d}-{v}"
        ch = rng.choices(names, weights)[0]
        ts = dt.datetime.combine(day, dt.time(0)) + dt.timedelta(seconds=rng.randint(0, 86399))
        touches.append({"visitor_id": vid, "ts": ts.isoformat(), "channel": ch, "campaign": f"{ch}_{day:%Y%m}"})
        if rng.random() < CHANNELS[ch][1]:
            ev = rng.choice(EVENTS)
            persons = rng.choice([1, 2, 2, 2, 3, 4, 4])
            nights = rng.choice([1, 1, 2, 2, 3])
            cur = rng.choices(list(CURRENCIES), [80, 8, 8, 4])[0]
            hotel = round(persons * nights * rng.uniform(38, 70), 2)
            gross_eur = persons * ev[5] + hotel
            gross = round(gross_eur / CURRENCIES[cur], 2)
            n += 1
            if rng.random() < 0.55:  # earlier visits of the same person, other channels
                for _ in range(rng.randint(1, 3)):
                    other = rng.choices(names, weights)[0]
                    back = ts - dt.timedelta(days=rng.randint(1, 12), seconds=rng.randint(0, 80000))
                    touches.append({"visitor_id": vid, "ts": back.isoformat(), "channel": other, "campaign": f"{other}_{back:%Y%m}"})
            bookings.append({
                "booking_id": f"B{day:%y%m%d}{n:04d}", "visitor_id": vid,
                "booked_at": (ts + dt.timedelta(minutes=rng.randint(3, 240))).isoformat(),
                "event_id": ev[0], "persons": persons, "nights": nights, "currency": cur,
                "gross_amount": gross, "hotel_cost_eur": round(hotel * rng.uniform(0.76, 0.88), 2),
                "ticket_cost_eur": round(persons * ev[5] * rng.uniform(0.82, 0.92), 2), "status": "confirmed",
                "exported_at": f"{day}T23:00:00"})
    # planted problems
    if bookings:
        bookings.append(dict(bookings[0]))                                       # duplicate
        c = dict(bookings[1 % len(bookings)]); c.update(status="cancelled", exported_at=f"{day}T23:30:00")
        bookings.append(c)                                                       # cancel
        u = dict(bookings[2 % len(bookings)]); u.update(booking_id=u["booking_id"] + "X", event_id="E99")
        bookings.append(u)                                                       # unknown event
        z = dict(bookings[3 % len(bookings)]); z.update(booking_id=z["booking_id"] + "Z", persons=0)
        bookings.append(z)                                                       # zero persons
    if touches:
        touches[0]["channel"] = ""                                               # no channel
    spend = [{"day": day.isoformat(), "channel": c, "spend_eur": round(CHANNELS[c][2] * season(day) * rng.uniform(0.85, 1.15), 2)}
             for c in CHANNELS if CHANNELS[c][2]]
    _csv(out / "touchpoints.csv", touches)
    _csv(out / "bookings.csv", bookings)
    _csv(out / "ad_spend.csv", spend)
    rates = {k: v for k, v in CURRENCIES.items() if k != "EUR"}
    if day.day == 15:
        rates.pop("CHF")                                                         # fx gap
    _csv(out / "fx_rates.csv", [{"day": day.isoformat(), "currency": k, "eur_per_unit": v} for k, v in rates.items()])
    (out / "_SUCCESS").write_text(json.dumps({"bookings": len(bookings), "touchpoints": len(touches)}))
    return {"touchpoints": len(touches), "bookings": len(bookings)}


def write_events(root: Path) -> None:
    _csv(root / "landing" / "events.csv", [
        {"event_id": e[0], "name": e[1], "city": e[2], "country": e[3], "kind": e[4], "ticket_price_eur": e[5]} for e in EVENTS])


def _csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
