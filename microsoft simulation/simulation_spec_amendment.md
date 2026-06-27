# Amendment — Probability Histogram with Confidence Overlay

Replace the separate histogram and CDF chart requirements with a single combined probability distribution chart.

## 1. Objective

The simulation output should include a configurable probability histogram over the simulated 10-year CAGR distribution.

The histogram should use a configured number of buckets, defaulting to 20.

Each bucket should show:

* bucket lower bound
* bucket upper bound
* midpoint
* count of simulations in bucket
* probability mass in bucket
* cumulative probability up to and including bucket
* probability of exceeding the bucket upper bound

The frontend should render:

```text
bar chart = probability mass per bucket
overlay line = cumulative confidence level
```

The cumulative line should rise from left to right.

Interpretation:

```text
At this CAGR bucket, the cumulative confidence level is the probability that the simulated 10-year CAGR is less than or equal to the bucket upper bound.
```

For hurdle-rate investing, also display:

```text
Probability of exceeding target CAGR = 1 - CDF(target CAGR)
```

---

## 2. Scenario configuration

Add this to the scenario JSON:

```json
{
  "output": {
    "histogram": {
      "bucket_count": 20,
      "bucket_mode": "auto_percentile_trimmed",
      "trim_percentiles": {
        "lower": 0.01,
        "upper": 0.99
      },
      "include_overflow_buckets": true,
      "x_metric": "total_return_cagr",
      "x_axis_format": "percent",
      "bar_metric": "probability",
      "overlay_metric": "cumulative_probability"
    }
  }
}
```

Supported `bucket_mode` values:

```text
auto_full_range
auto_percentile_trimmed
fixed_range
```

### 2.1 `auto_full_range`

Use full observed simulation range:

```python
min_value = min(cagr_values)
max_value = max(cagr_values)
```

This captures all outcomes but can produce unhelpful charts if there are extreme outliers.

### 2.2 `auto_percentile_trimmed`

Default mode.

Use a trimmed visual range:

```python
min_value = percentile(cagr_values, lower_trim)
max_value = percentile(cagr_values, upper_trim)
```

Default:

```text
lower_trim = 1st percentile
upper_trim = 99th percentile
```

If `include_overflow_buckets` is true, include two additional buckets:

```text
< lower_trim bucket
> upper_trim bucket
```

This keeps the chart readable while still accounting for tail outcomes.

### 2.3 `fixed_range`

Allow user-defined histogram range:

```json
{
  "bucket_mode": "fixed_range",
  "fixed_min": -0.10,
  "fixed_max": 0.20,
  "bucket_count": 20
}
```

Meaning:

```text
-10% CAGR to +20% CAGR, split into 20 buckets
```

---

## 3. Backend output contract

Update `/api/simulate` response.

Replace or supplement the old `histogram` and `cdf` fields with:

```json
{
  "distribution": {
    "metric": "total_return_cagr",
    "bucket_count": 20,
    "bucket_mode": "auto_percentile_trimmed",
    "target_cagr": 0.12,
    "probability_above_target": 0.0,
    "probability_below_target": 0.0,
    "buckets": [
      {
        "bucket_index": 0,
        "label": "< -2.0%",
        "lower_bound": null,
        "upper_bound": -0.02,
        "midpoint": null,
        "count": 123,
        "probability": 0.00615,
        "cumulative_probability": 0.00615,
        "probability_exceeding_upper_bound": 0.99385,
        "contains_target": false
      },
      {
        "bucket_index": 1,
        "label": "-2.0% to -0.5%",
        "lower_bound": -0.02,
        "upper_bound": -0.005,
        "midpoint": -0.0125,
        "count": 402,
        "probability": 0.0201,
        "cumulative_probability": 0.02625,
        "probability_exceeding_upper_bound": 0.97375,
        "contains_target": false
      }
    ]
  }
}
```

Definitions:

```text
probability = count / simulation_count

cumulative_probability =
  sum(probability of all buckets up to and including current bucket)

probability_exceeding_upper_bound =
  1 - cumulative_probability
```

`contains_target` should be true for the bucket where:

```python
lower_bound <= target_cagr < upper_bound
```

For overflow buckets:

```python
lower_bound = None
```

or:

```python
upper_bound = None
```

depending on whether it is the left-tail or right-tail bucket.

---

## 4. Backend histogram algorithm

Implement:

```python
def build_probability_distribution(
    values: np.ndarray,
    bucket_count: int,
    target_value: float,
    mode: str = "auto_percentile_trimmed",
    lower_trim: float = 0.01,
    upper_trim: float = 0.99,
    include_overflow_buckets: bool = True,
) -> ProbabilityDistribution:
    ...
```

Algorithm:

```python
values = np.asarray(values)
values = values[np.isfinite(values)]

if mode == "auto_full_range":
    visual_min = values.min()
    visual_max = values.max()

elif mode == "auto_percentile_trimmed":
    visual_min = np.quantile(values, lower_trim)
    visual_max = np.quantile(values, upper_trim)

elif mode == "fixed_range":
    visual_min = fixed_min
    visual_max = fixed_max

edges = np.linspace(visual_min, visual_max, bucket_count + 1)
```

If overflow buckets are enabled:

```python
left_tail = values[values < visual_min]
middle = values[(values >= visual_min) & (values <= visual_max)]
right_tail = values[values > visual_max]
```

Build:

```text
left overflow bucket
N normal buckets
right overflow bucket
```

If overflow buckets are disabled, values outside the visual range should still be included in probability calculations separately so total probability is not silently lost. Prefer enabling overflow buckets by default.

The sum of bucket probabilities must equal 1.0, allowing for tiny floating-point tolerance.

---

## 5. Target CAGR handling

The chart must clearly mark the configured target CAGR.

Default:

```json
{
  "target_cagr": 0.12
}
```

The backend should calculate:

```python
probability_above_target = np.mean(cagr_values >= target_cagr)
probability_below_target = np.mean(cagr_values < target_cagr)
```

Return both values in the summary and distribution objects.

Also return:

```json
{
  "target_marker": {
    "value": 0.12,
    "label": "12% target CAGR",
    "probability_above": 0.0,
    "probability_below": 0.0
  }
}
```

---

## 6. Frontend chart requirements

Create component:

```text
ProbabilityHistogramWithConfidenceOverlay.tsx
```

Props:

```typescript
type DistributionBucket = {
  bucketIndex: number;
  label: string;
  lowerBound: number | null;
  upperBound: number | null;
  midpoint: number | null;
  count: number;
  probability: number;
  cumulativeProbability: number;
  probabilityExceedingUpperBound: number;
  containsTarget: boolean;
};

type ProbabilityDistribution = {
  metric: string;
  bucketCount: number;
  bucketMode: string;
  targetCagr: number;
  probabilityAboveTarget: number;
  probabilityBelowTarget: number;
  buckets: DistributionBucket[];
};

type Props = {
  distribution: ProbabilityDistribution;
};
```

Render using Recharts `ComposedChart`:

```text
Bar = probability
Line = cumulativeProbability
ReferenceLine = targetCagr bucket / target marker
Left Y-axis = bucket probability
Right Y-axis = cumulative confidence level
X-axis = CAGR bucket label
```

Formatting:

```text
probability bars shown as %
cumulative confidence shown as %
CAGR bucket labels shown as %
tooltip shows:
  bucket range
  probability in bucket
  cumulative confidence
  probability exceeding bucket
  simulation count
```

Example tooltip:

```text
CAGR range: 8.0% to 9.5%
Probability in bucket: 7.4%
Confidence <= upper bound: 61.2%
Probability > upper bound: 38.8%
Simulations: 1,480
```

The target bucket should be visually highlighted.

The chart title should be:

```text
10-year CAGR probability distribution
```

Subtitle:

```text
Bars show probability by return bucket. Line shows cumulative confidence level.
```

---

## 7. UI controls

Add controls:

```text
Bucket count: number input / slider
Default: 20
Min: 5
Max: 100

Bucket mode:
- auto full range
- auto percentile trimmed
- fixed range

Trim percentiles:
- lower trim
- upper trim

Fixed min CAGR
Fixed max CAGR

Show overflow buckets: true/false
Show cumulative confidence overlay: true/false
Show probability exceeding overlay: true/false
```

Default settings:

```json
{
  "bucket_count": 20,
  "bucket_mode": "auto_percentile_trimmed",
  "lower_trim": 0.01,
  "upper_trim": 0.99,
  "include_overflow_buckets": true,
  "show_cumulative_confidence_overlay": true,
  "show_probability_exceeding_overlay": false
}
```

---

## 8. Optional second overlay

Support an optional inverse overlay:

```text
probability_exceeding_upper_bound
```

This line falls from left to right.

It answers:

```text
What is the probability of achieving a CAGR above this bucket?
```

Default this off, because it can clutter the chart.

However, it is useful for hurdle-rate analysis.

For example:

```text
At 12% CAGR, probability exceeding = 18%
```

---

## 9. Acceptance criteria

The feature is complete when:

1. User can configure bucket count.
2. Default bucket count is 20.
3. Histogram probabilities sum to 100%.
4. Cumulative confidence line rises from left to right.
5. Target CAGR is clearly marked.
6. Tooltip shows bucket probability and cumulative probability.
7. Dashboard shows probability of exceeding target CAGR.
8. Overflow buckets work correctly.
9. User can switch between full-range, percentile-trimmed and fixed-range buckets.
10. Chart updates when assumptions are changed and simulation is rerun.
11. Backend tests verify probability mass sums to 1.0.
12. Backend tests verify cumulative probability is monotonic increasing.
13. Backend tests verify probability above target matches raw simulation results.
