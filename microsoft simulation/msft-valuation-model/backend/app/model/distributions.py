from __future__ import annotations

import math

import numpy as np

from app.model.assumptions import DistributionSpec


def sample_pert(
    min_value: float,
    mode_value: float,
    max_value: float,
    size: int,
    rng: np.random.Generator,
    lamb: float = 4.0,
) -> np.ndarray:
    if min_value == max_value:
        return np.full(size, min_value, dtype=float)
    alpha = 1.0 + lamb * (mode_value - min_value) / (max_value - min_value)
    beta = 1.0 + lamb * (max_value - mode_value) / (max_value - min_value)
    samples = rng.beta(alpha, beta, size=size)
    return min_value + samples * (max_value - min_value)


def sample_pert_integer(
    min_value: int,
    mode_value: int,
    max_value: int,
    size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    samples = sample_pert(float(min_value), float(mode_value), float(max_value), size, rng)
    rounded = np.rint(samples).astype(int)
    return np.clip(rounded, min_value, max_value)


def sample_distribution(spec: DistributionSpec, size: int, rng: np.random.Generator) -> np.ndarray:
    if spec.type == "fixed":
        value = spec.value if spec.value is not None else spec.mode
        return np.full(size, float(value), dtype=float)
    if spec.type == "pert":
        return sample_pert(spec.min, spec.mode, spec.max, size, rng)
    if spec.type == "pert_integer":
        return sample_pert_integer(int(spec.min), int(spec.mode), int(spec.max), size, rng).astype(float)
    if spec.type == "derived":
        if spec.formula == "1 - short_lived_asset_share":
            raise ValueError("derived values must be resolved by the caller")
    raise ValueError(f"Unsupported distribution type: {spec.type}")


def interpolate_linear(start: float, end: np.ndarray, steps: int) -> np.ndarray:
    fractions = np.linspace(1 / steps, 1.0, steps)
    return start + np.outer(end - start, fractions)


def stable_percentile(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q / 100.0, method="linear"))


def expected_pert_mean(spec: DistributionSpec, lamb: float = 4.0) -> float:
    if spec.type == "fixed":
        return float(spec.value if spec.value is not None else spec.mode)
    if spec.type in {"pert", "pert_integer"}:
        return (spec.min + lamb * spec.mode + spec.max) / (lamb + 2)
    raise ValueError("Expected value only supported for fixed and pert distributions")


def clamp(values: np.ndarray, low: float | None = None, high: float | None = None) -> np.ndarray:
    result = values
    if low is not None:
        result = np.maximum(result, low)
    if high is not None:
        result = np.minimum(result, high)
    return result


def safe_divide(numerator: np.ndarray, denominator: np.ndarray, fallback: float = 0.0) -> np.ndarray:
    out = np.full_like(numerator, fallback, dtype=float)
    mask = np.abs(denominator) > 1e-12
    out[mask] = numerator[mask] / denominator[mask]
    return out


def geometric_cagr(ending_value: np.ndarray, starting_value: float, horizon_years: int) -> np.ndarray:
    ratio = np.maximum(ending_value / starting_value, 1e-12)
    return np.power(ratio, 1.0 / horizon_years) - 1.0
