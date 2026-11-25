"""Waitlist confirmation chance: a transparent rule of thumb on SIMULATED data.

This is NOT a prediction model and is never presented as one. It encodes two facts every Indian
railway traveller relies on, with numbers chosen to look sensible:

  * a longer waitlist is less likely to clear (seats free up one cancellation at a time);
  * more days left before travel means more cancellations still to come.

    chance = exp(-waitlist / scale),  scale = coach_scale(class) * (1 + 0.12 * min(days_left, 10))

Sleeper coaches have more berths (more cancellations to absorb a waitlist) than 3A, so SL gets the
larger scale. Example: WL 46 in SL two days out -> about 59%; the same in 3A -> about 40%.
"""

from __future__ import annotations

import math

COACH_SCALE = {"SL": 70.0, "3A": 40.0}
DEFAULT_SCALE = 50.0
DAYS_WEIGHT = 0.12
MAX_DAYS = 10


def confirm_chance(waitlist: int, travel_class: str, days_until_travel: int | None) -> float | None:
    """0..1, or None when there is no waitlist to clear."""
    if waitlist <= 0:
        return None
    days = min(max(days_until_travel or 0, 0), MAX_DAYS)
    scale = COACH_SCALE.get(travel_class, DEFAULT_SCALE) * (1 + DAYS_WEIGHT * days)
    return round(math.exp(-waitlist / scale), 2)


def band(chance: float) -> str:
    """The words shown next to the number."""
    if chance >= 0.7:
        return "high"
    if chance >= 0.4:
        return "medium"
    return "low"
