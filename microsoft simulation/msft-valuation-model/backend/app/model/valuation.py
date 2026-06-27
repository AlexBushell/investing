from __future__ import annotations

from typing import Any

import numpy as np

from app.model.assumptions import HistogramOutputConfig


def build_probability_distribution(
    values: np.ndarray,
    bucket_count: int,
    target_value: float,
    mode: str = "auto_percentile_trimmed",
    lower_trim: float = 0.01,
    upper_trim: float = 0.99,
    include_overflow_buckets: bool = True,
    fixed_min: float | None = None,
    fixed_max: float | None = None,
) -> dict[str, Any]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Cannot build distribution for empty values")

    confidence_level = 0.85
    confidence_floor_value = float(np.quantile(values, 1.0 - confidence_level))

    if mode == "auto_full_range":
        visual_min = float(values.min())
        visual_max = float(values.max())
    elif mode == "auto_percentile_trimmed":
        visual_min = float(np.quantile(values, lower_trim))
        visual_max = float(np.quantile(values, upper_trim))
    elif mode == "fixed_range":
        if fixed_min is None or fixed_max is None:
            raise ValueError("fixed_range requires fixed_min and fixed_max")
        visual_min = float(fixed_min)
        visual_max = float(fixed_max)
    else:
        raise ValueError(f"Unsupported bucket mode: {mode}")

    if visual_max <= visual_min:
        visual_max = visual_min + 1e-9

    edges = np.linspace(visual_min, visual_max, bucket_count + 1)
    middle_indices = np.digitize(values, edges, right=False) - 1
    middle_counts = np.zeros(bucket_count, dtype=int)

    left_tail_mask = values < visual_min
    right_tail_mask = values > visual_max
    middle_mask = ~(left_tail_mask | right_tail_mask)
    middle_indices = np.clip(middle_indices[middle_mask], 0, bucket_count - 1)
    for index in middle_indices:
        middle_counts[index] += 1

    total_count = values.size
    buckets: list[dict[str, Any]] = []
    running_probability = 0.0
    bucket_index = 0

    if include_overflow_buckets:
        left_count = int(left_tail_mask.sum())
        left_probability = left_count / total_count
        running_probability += left_probability
        buckets.append(
            {
                "bucket_index": bucket_index,
                "label": f"< {visual_min:.1%}",
                "lower_bound": None,
                "upper_bound": visual_min,
                "midpoint": None,
                "count": left_count,
                "probability": left_probability,
                "cumulative_probability": running_probability,
                "probability_exceeding_upper_bound": 1.0 - running_probability,
                "contains_target": target_value < visual_min,
            }
        )
        bucket_index += 1

    for offset in range(bucket_count):
        lower_bound = float(edges[offset])
        upper_bound = float(edges[offset + 1])
        count = int(middle_counts[offset])
        probability = count / total_count
        running_probability += probability
        buckets.append(
            {
                "bucket_index": bucket_index,
                "label": f"{lower_bound:.1%} to {upper_bound:.1%}",
                "lower_bound": lower_bound,
                "upper_bound": upper_bound,
                "midpoint": (lower_bound + upper_bound) / 2.0,
                "count": count,
                "probability": probability,
                "cumulative_probability": running_probability,
                "probability_exceeding_upper_bound": 1.0 - running_probability,
                "contains_target": lower_bound <= target_value < upper_bound,
            }
        )
        bucket_index += 1

    if include_overflow_buckets:
        right_count = int(right_tail_mask.sum())
        right_probability = right_count / total_count
        running_probability += right_probability
        buckets.append(
            {
                "bucket_index": bucket_index,
                "label": f"> {visual_max:.1%}",
                "lower_bound": visual_max,
                "upper_bound": None,
                "midpoint": None,
                "count": right_count,
                "probability": right_probability,
                "cumulative_probability": running_probability,
                "probability_exceeding_upper_bound": 0.0,
                "contains_target": target_value >= visual_max,
            }
        )

    if not include_overflow_buckets:
        outside_count = int(left_tail_mask.sum() + right_tail_mask.sum())
        if outside_count:
            adjustment = outside_count / total_count
            buckets[-1]["probability"] += adjustment
            buckets[-1]["count"] += outside_count
            cumulative = 0.0
            for bucket in buckets:
                cumulative += bucket["probability"]
                bucket["cumulative_probability"] = cumulative
                bucket["probability_exceeding_upper_bound"] = max(0.0, 1.0 - cumulative)

    return {
        "metric": "total_return_cagr",
        "bucket_count": bucket_count,
        "bucket_mode": mode,
        "target_cagr": target_value,
        "probability_above_target": float(np.mean(values >= target_value)),
        "probability_below_target": float(np.mean(values < target_value)),
        "confidence_floor": {
            "confidence_level": confidence_level,
            "value": confidence_floor_value,
            "probability_at_or_above": float(np.mean(values >= confidence_floor_value)),
            "label": f"{confidence_level:.0%} confidence floor",
        },
        "buckets": buckets,
    }


def build_distribution_from_config(values: np.ndarray, target_value: float, config: HistogramOutputConfig) -> dict[str, Any]:
    return build_probability_distribution(
        values=values,
        bucket_count=config.bucket_count,
        target_value=target_value,
        mode=config.bucket_mode,
        lower_trim=config.trim_percentiles.lower,
        upper_trim=config.trim_percentiles.upper,
        include_overflow_buckets=config.include_overflow_buckets,
        fixed_min=config.fixed_min,
        fixed_max=config.fixed_max,
    )
