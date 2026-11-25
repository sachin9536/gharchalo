"""Shared-cab fare estimates (rough INR figures, not a real tariff)."""

from geo import haversine_km

CAB_RATE_INR_PER_KM = 13
CAB_MINIMUM_FARE = 800
ROAD_FACTOR = 1.25  # straight-line km -> road km
CAB_GROUP_SIZES = (2, 3, 4)


def road_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a, b) * ROAD_FACTOR


def cab_total_fare(km: float) -> int:
    return max(CAB_MINIMUM_FARE, int(round(km * CAB_RATE_INR_PER_KM / 5) * 5))


def cab_per_person(total: int, people: int) -> int:
    return int(round(total / people / 5) * 5)
