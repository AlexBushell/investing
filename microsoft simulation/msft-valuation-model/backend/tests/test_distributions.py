import numpy as np

from app.model.assumptions import DistributionSpec
from app.model.distributions import sample_distribution, sample_pert, sample_pert_integer


def test_pert_samples_stay_in_range() -> None:
    rng = np.random.default_rng(42)
    values = sample_pert(1.0, 2.0, 4.0, 5000, rng)
    assert np.all(values >= 1.0)
    assert np.all(values <= 4.0)


def test_pert_sample_mean_tracks_mode_bias() -> None:
    rng = np.random.default_rng(42)
    values = sample_pert(0.0, 0.8, 1.0, 10000, rng)
    assert values.mean() > 0.55


def test_fixed_distribution_returns_constant() -> None:
    rng = np.random.default_rng(42)
    spec = DistributionSpec(type="fixed", value=3.14)
    values = sample_distribution(spec, 100, rng)
    assert np.all(values == 3.14)


def test_integer_pert_returns_integers_in_range() -> None:
    rng = np.random.default_rng(42)
    values = sample_pert_integer(3, 5, 7, 1000, rng)
    assert np.all(values >= 3)
    assert np.all(values <= 7)
    assert np.all(values == np.rint(values))
