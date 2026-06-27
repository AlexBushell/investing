import numpy as np

from app.model.assumptions import Scenario
from app.model.simulation import load_default_scenario
from app.model.financials import simulate_financials


def test_financial_identities_hold_for_small_run() -> None:
    scenario = Scenario.model_validate(load_default_scenario())
    rng = np.random.default_rng(42)
    arrays = simulate_financials(scenario, 250, rng)

    assert arrays.revenue.shape == (250, scenario.simulation.horizon_years)
    assert np.all(arrays.revenue >= 0.0)
    assert np.all(arrays.share_count > 0.0)
    assert np.all(np.isfinite(arrays.fcf))
    assert np.allclose(arrays.eps, arrays.net_income / arrays.share_count, atol=1e-8)
    assert np.allclose(arrays.fcf, arrays.net_income + arrays.depreciation - arrays.total_capex, atol=1e-8)
    assert np.all(arrays.terminal_pe > 0.0)
    assert np.all(arrays.terminal_fcf_multiple > 0.0)
    share_count_ratios = arrays.share_count[:, 1:] / arrays.share_count[:, :-1]
    assert np.all(share_count_ratios >= 0.97 - 1e-8)
