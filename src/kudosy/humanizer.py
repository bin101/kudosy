"""Human-like timing helpers — pure, deterministic when RNG is injected.

All functions accept an explicit ``rng: random.Random`` instance so tests
can seed it and get reproducible results.
"""

from __future__ import annotations

import random as _random_module

_MIN_INTERVAL_MINUTES = 5.0


def compute_jitter(
    interval_min: float,
    jitter_min: float,
    rng: _random_module.Random | None = None,
) -> float:
    """Return the next scheduler interval with a random ±jitter offset.

    The result is always ≥ ``_MIN_INTERVAL_MINUTES`` (5 minutes) to avoid
    accidentally scheduling a runaway tight loop.

    Args:
        interval_min: Base interval in minutes (e.g. 60).
        jitter_min:   Maximum jitter in minutes (e.g. 15). 0 → no jitter.
        rng:          Optional seeded Random instance for deterministic tests.
                      Uses ``random`` module globals when None.

    Returns:
        Actual next-run interval in minutes (float).
    """
    if rng is None:
        rng = _random_module.Random()
    if jitter_min <= 0:
        return float(interval_min)
    offset = rng.uniform(-jitter_min, jitter_min)
    result = interval_min + offset
    return max(_MIN_INTERVAL_MINUTES, result)


def compute_delay(
    min_s: float,
    max_s: float,
    rng: _random_module.Random | None = None,
) -> float:
    """Return a random delay in seconds in [min_s, max_s].

    Args:
        min_s: Minimum delay in seconds (≥ 0).
        max_s: Maximum delay in seconds (≥ min_s).
        rng:   Optional seeded Random instance for deterministic tests.

    Returns:
        Delay in seconds (float).

    Raises:
        ValueError: When min_s > max_s.
    """
    if min_s > max_s:
        raise ValueError(f"min_s ({min_s}) must be ≤ max_s ({max_s})")
    if rng is None:
        rng = _random_module.Random()
    return rng.uniform(min_s, max_s)
