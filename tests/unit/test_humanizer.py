"""Unit tests for humanizer.py — pure, RNG-injected delay/jitter functions."""

import random

import pytest

from kudosy.humanizer import compute_delay, compute_jitter


class TestComputeJitter:
    """compute_jitter(interval_min, jitter_min, rng) → next interval in minutes."""

    def test_zero_jitter_returns_interval(self) -> None:
        rng = random.Random(0)
        result = compute_jitter(60, 0, rng)
        assert result == pytest.approx(60.0)

    def test_result_within_bounds(self) -> None:
        rng = random.Random(42)
        for _ in range(100):
            r = compute_jitter(60, 15, rng)
            assert 45.0 <= r <= 75.0

    def test_minimum_is_five_minutes(self) -> None:
        # Even if interval - jitter < 5, result must be >= 5
        rng = random.Random(0)
        # interval=6, jitter=10 → range would be -4..16, clamp to 5..16
        for _ in range(200):
            r = compute_jitter(6, 10, rng)
            assert r >= 5.0

    def test_large_jitter_stays_bounded(self) -> None:
        rng = random.Random(99)
        for _ in range(100):
            r = compute_jitter(30, 25, rng)
            # upper bound = 30 + 25 = 55
            assert r <= 55.0

    def test_exact_minimum_interval(self) -> None:
        rng = random.Random(7)
        # interval already at minimum
        for _ in range(50):
            r = compute_jitter(5, 5, rng)
            assert r >= 5.0


class TestComputeDelay:
    """compute_delay(min_s, max_s, rng) → delay in seconds."""

    def test_result_within_bounds(self) -> None:
        rng = random.Random(1)
        for _ in range(200):
            d = compute_delay(3.0, 25.0, rng)
            assert 3.0 <= d <= 25.0

    def test_zero_min_allowed(self) -> None:
        rng = random.Random(2)
        for _ in range(100):
            d = compute_delay(0.0, 10.0, rng)
            assert 0.0 <= d <= 10.0

    def test_min_equals_max_returns_exact(self) -> None:
        rng = random.Random(3)
        for _ in range(10):
            d = compute_delay(5.0, 5.0, rng)
            assert d == pytest.approx(5.0)

    def test_invalid_min_greater_than_max_raises(self) -> None:
        rng = random.Random(4)
        with pytest.raises(ValueError, match="min_s"):
            compute_delay(10.0, 5.0, rng)

    def test_deterministic_with_seed(self) -> None:
        d1 = compute_delay(1.0, 100.0, random.Random(42))
        d2 = compute_delay(1.0, 100.0, random.Random(42))
        assert d1 == pytest.approx(d2)
