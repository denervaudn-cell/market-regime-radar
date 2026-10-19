"""Independent sensitivity, bounded-grid and regime classification checks."""

import pytest

from radar.engine import BacktestParams, classify_regime
from radar.studies import run_studies
from tests.engine_fixtures import flat_dataset


@pytest.fixture(scope="module")
def study():
	return run_studies(
		flat_dataset(),
		BacktestParams(
			start="2020-01-01", end="2020-05-15", mode="compare", cost_bps=0, short_borrow_bps=0
		),
	)


def test_robustness_is_complete_real_grid_with_frequency_correct_statistics(study):
	assert {(row["top_n"], row["rebalance"]) for row in study["robustness"]} == {
		(top_n, frequency)
		for top_n in (1, 3, 5)
		for frequency in ("weekly", "monthly", "quarterly")
	}
	for row in study["robustness"]:
		assert row["stats"]["total_return"] == 0
		assert row["stats"]["return_frequency"] == row["rebalance"]
		assert row["period"]["complete_periods"] > 0


def test_cost_sensitivity_has_actual_trading_drag_not_static_values(study):
	rows = study["cost_sensitivity"]
	assert [row["cost_bps"] for row in rows] == [0, 10, 25, 50]
	returns = [row["stats"]["total_return"] for row in rows]
	assert returns[0] == 0
	assert all(left > right for left, right in zip(returns, returns[1:]))
	assert study["strategy"]["id"] == "ranked3"
	assert study["regime_performance"][0]["periods"] == 4
	assert study["regime_performance"][0]["hit_rate"] == 0


def test_short_period_unavailable_frequency_remains_an_explicit_grid_row():
	response = run_studies(
		flat_dataset(), BacktestParams(start="2020-01-01", end="2020-02-15", rebalance="weekly")
	)
	quarterly = [row for row in response["robustness"] if row["rebalance"] == "quarterly"]
	assert len(quarterly) == 3
	assert all(row["status"] == "unavailable" and row["stats"] is None for row in quarterly)
	assert all(row["error"]["code"] == "insufficient_periods" for row in quarterly)


@pytest.mark.parametrize(
	"vol,credit,inflation,expected",
	[
		(0.5, -1, 1, "stress"),
		(-1, 0.5, 1, "stress"),
		(0, 0, 0.5, "inflation"),
		(-0.1, -0.1, 0, "low_stress"),
		(0, 0, 0, "balanced"),
	],
)
def test_regime_rules_have_explicit_boundaries_and_precedence(vol, credit, inflation, expected):
	assert (
		classify_regime(
			{"vol": vol, "credit": credit, "inflation": inflation, "rates": 0, "curve": 0}
		)
		== expected
	)
