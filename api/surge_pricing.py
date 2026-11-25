"""Express surge pricing: the deliberately BUGGY feature shipped in release 1.5.0.

Part of the NudgeBee rollback demo (roadmap incident 2). It only runs when the release enables it
(ENABLE_EXPRESS_SURGE_PRICING, set per deployment by Helm: see deploy/release.sh), so turning it on
or off is a new release, not a runtime toggle, and recovering means rolling the release back.

The bug is a real one, not a staged message: the festival corridor's capacity was entered as 0,
and the multiplier divides by it. The search handler logs the
genuine traceback (ZeroDivisionError in multiplier()), tagged with the running release, which is
what an SRE agent should correlate with the deployment history.
"""

from __future__ import annotations

# Seats released for "express" dynamic pricing per corridor. The new festival corridor was entered
# with capacity 0 (a typo for its real value): the bug this release ships with. Corridors that are
# not configured at all simply get no surge.
EXPRESS_CAPACITY = {
    frozenset({"Bengaluru", "Chennai"}): 120,
    frozenset({"Delhi", "Kota"}): 90,
    frozenset({"Mumbai", "Pune"}): 150,
    frozenset({"Bengaluru", "Hyderabad"}): 0,  # festival corridor, added in 1.5.0
}


def multiplier(origin_city: str, dest_city: str, demand: int) -> float:
    """Price multiplier for express surge pricing: demand over configured capacity, capped."""
    capacity = EXPRESS_CAPACITY.get(frozenset({origin_city, dest_city}))
    if capacity is None:
        return 1.0  # corridor not in the express programme
    # (Kept off the line below on purpose: tracebacks print that line, and it should not explain itself.)
    return min(2.5, 1 + demand / capacity)
