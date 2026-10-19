"""Financial regression cases with hand-derived independent expectations."""

import json
import math
from datetime import date

import pytest
from pydantic import ValidationError

from radar.data import DataError
from radar.engine import (
	SECTORS,
	BacktestParams,
	performance_statistics,
	run_backtest,
	score_sectors,
	target_weights,
)
from tests.engine_fixtures import dataset_from_payload, fixture_payload, flat_dataset


@pytest.fixture(scope="module")
def flat():
	return flat_dataset()


def params(**overrides):
	return BacktestParams(
		start="2020-01-01", end="2020-05-15", cost_bps=0, short_borrow_bps=0, **overrides
	)


def result(dataset, **overrides):
	return run_backtest(dataset, params(**overrides))["results"][overrides.get("mode", "extreme1")]


def _fixed_ranking(monkeypatch, rankings):
	calls = iter(rankings)
	last = rankings[-1]

	def scorer(_state, _momentum):
		return [
			{"symbol": symbol, "score": 100 - index}
			for index, symbol in enumerate(next(calls, last))
		]

	monkeypatch.setattr("radar.engine.score_sectors", scorer)


def test_modes_are_distinct_signed_contracts_and_worst_short_is_heaviest(flat):
	ranked = list(SECTORS)
	assert target_weights("extreme1", ranked) == {"XLB": 2, "XLY": -2}
	assert target_weights("longonly3", ranked) == {"XLB": 1, "XLC": 0.65, "XLE": 0.45}
	assert target_weights("ranked3", ranked) == {
		"XLB": 0.5,
		"XLC": 0.25,
		"XLE": 0.25,
		"XLY": -0.5,
		"XLV": -0.25,
		"XLU": -0.25,
	}
	response = run_backtest(flat, params(mode="compare"))
	assert set(response["results"]) == {"extreme1", "ranked3", "longonly3"}
	for mode, row in response["results"].items():
		assert row["strategy"]["id"] == mode
		assert row["equity_curve"][-1]["strategy"] == 100
	assert response["results"]["longonly3"]["strategy"]["gross"] == 2.1


def test_zero_costs_and_zero_macro_rates_are_not_defaults(flat):
	response = run_backtest(flat, params())
	assert response["params"]["cost_bps"] == 0
	assert response["params"]["short_borrow_bps"] == 0
	assert response["results"]["extreme1"]["stats"]["total_return"] == 0
	assert response["results"]["extreme1"]["stats"]["sharpe"] is None


@pytest.mark.parametrize(
	"override",
	[
		{"cost_bps": float("inf")},
		{"cost_bps": True},
		{"cost_bps": "10"},
		{"short_borrow_bps": -1},
		{"mode": "unknown"},
		{"topN": 2.5},
		{"start": "2020-01"},
		{"start": 20200101},
		{"start": "2020-02-30"},
		{"start": "2020-01-01T00:00:00"},
		{"rebalance": "daily"},
		{"top_n": 0},
		{"top_n": 6},
		{"top_n": True},
		{"top_n": 3.0},
		{"top_n": "3"},
	],
)
def test_invalid_parameters_fail_before_engine(override):
	with pytest.raises(ValidationError):
		BacktestParams.model_validate({"start": "2020-01-01", **override})


def test_entry_cost_is_40bps_for_200_long_and_200_short(flat):
	response = run_backtest(
		flat, BacktestParams(start="2020-01-01", end="2020-05-15", cost_bps=10, short_borrow_bps=0)
	)
	rows = response["results"]["extreme1"]["holdings"]
	assert rows[0]["turnover"] == 4
	assert rows[0]["trading_cost"] == pytest.approx(0.004)
	assert rows[0]["period_return"] == pytest.approx(-0.004)
	assert rows[-1]["liquidation_cost"] > 0


def test_short_only_switches_are_charged(monkeypatch, flat):
	first = list(SECTORS)
	second = [symbol for symbol in first if symbol != "XLV"] + ["XLV"]
	_fixed_ranking(monkeypatch, [first, second])
	rows = result(flat)["holdings"]
	# Closing the old 200 short and opening a different 200 short trades 400% of NAV.
	assert rows[1]["turnover"] == 4
	assert rows[1]["weights"] == {"XLB": 2, "XLV": -2}


def test_same_names_with_changed_rank_weights_trade(monkeypatch, flat):
	first = list(SECTORS)
	second = first.copy()
	second[0], second[1] = second[1], second[0]
	second[-1], second[-2] = second[-2], second[-1]
	_fixed_ranking(monkeypatch, [first, second])
	rows = result(flat, mode="ranked3")["holdings"]
	# Two long changes of 25%, plus two short changes of 25%, total100%.
	assert rows[1]["turnover"] == pytest.approx(1)


def test_drifted_signed_positions_determine_rebalance_turnover(monkeypatch):
	payload = fixture_payload()
	for row in payload["series"]["XLB_TR"]["observations"]:
		if row["date"] >= "2020-01-03":
			row["value"] = 110
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	rows = result(dataset_from_payload(payload))["holdings"]
	# 200 long ->220; -200 short unchanged; NAV120. Targets240/-240:20+40=60.
	assert rows[0]["period_return"] == pytest.approx(0.2)
	assert rows[1]["turnover"] == pytest.approx(60 / 120)


def test_execution_lag_does_not_capture_jump_before_first_fill(monkeypatch):
	payload = fixture_payload()
	for row in payload["series"]["XLB_TR"]["observations"]:
		if row["date"] >= "2020-01-02":
			row["value"] = 110
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	response = run_backtest(dataset_from_payload(payload), params())
	assert response["period"]["first_decision"] == "2019-12-31"
	assert response["period"]["first_execution"] == "2020-01-02"
	assert response["results"]["extreme1"]["stats"]["total_return"] == 0


def test_future_macro_revision_cannot_rewrite_old_decision(flat):
	baseline = result(flat)["holdings"][0]
	payload = fixture_payload()
	rows = payload["series"]["DFII10"]["observations"]
	rows.append({"date": "2019-12-31", "value": 30, "available_at": "2020-01-15T22:00:00Z"})
	rows.sort(key=lambda row: (row["date"], row["available_at"]))
	actual = result(dataset_from_payload(payload))["holdings"][0]
	assert actual["state"] == baseline["state"]
	assert actual["scores"] == baseline["scores"]


def test_macro_release_after_cutoff_is_not_assumed_known():
	payload = fixture_payload()
	for row in payload["series"]["DFII10"]["observations"]:
		if "2019-12-20" <= row["date"] <= "2019-12-31":
			row["available_at"] = "2020-01-02T22:00:00Z"
	with pytest.raises(DataError) as error:
		result(dataset_from_payload(payload))
	assert error.value.code == "missing_macro_history"
	assert error.value.details["series"] == "DFII10"


def test_missing_daily_holding_price_blocks_instead_of_skipping_month():
	payload = fixture_payload()
	payload["series"]["XLC_TR"]["observations"] = [
		row for row in payload["series"]["XLC_TR"]["observations"] if row["date"] != "2020-02-12"
	]
	with pytest.raises(DataError) as error:
		result(dataset_from_payload(payload))
	assert error.value.code == "missing_history"
	assert error.value.details["date"] == "2020-02-12"


def test_missing_calendar_month_is_rejected():
	payload = fixture_payload()
	payload["calendar"] = [day for day in payload["calendar"] if not day.startswith("2020-02")]
	with pytest.raises((ValidationError, DataError)):
		result(dataset_from_payload(payload))


@pytest.mark.parametrize("invalid", [0, "", None])
def test_missing_and_nonpositive_return_indices_are_not_zeros(invalid):
	payload = fixture_payload()
	payload["series"]["XLB_TR"]["observations"][0]["value"] = invalid
	with pytest.raises(ValidationError):
		dataset_from_payload(payload)


def test_mixed_net_and_gross_dividend_conventions_block():
	payload = fixture_payload()
	payload["series"]["XLB_TR"]["price_basis"] = "total_return_gross"
	with pytest.raises(DataError) as error:
		result(dataset_from_payload(payload))
	assert error.value.code == "return_basis_mismatch"


def test_warmup_is_separate_from_evaluation_and_open_month_excluded(flat):
	response = run_backtest(
		flat, BacktestParams(start="2020-01-01", cost_bps=0, short_borrow_bps=0)
	)
	assert response["period"]["warmup_start"] < "2020-01-01"
	assert response["period"]["first_execution"] == "2020-01-02"
	assert response["period"]["first_return"] == "2020-02-03"
	assert response["period"]["last_complete_return"] == "2021-04-01"
	assert response["period"]["complete_periods"] == 15
	assert response["period"]["excluded_partial"] is True


def test_insufficient_warmup_does_not_silently_move_evaluation(flat):
	with pytest.raises(DataError) as error:
		run_backtest(flat, BacktestParams(start="2019-01-01"))
	assert error.value.code == "insufficient_warmup"


def test_funding_and_borrow_use_actual_calendar_days(monkeypatch):
	payload = fixture_payload()
	for row in payload["series"]["DFF"]["observations"]:
		row["value"] = 10
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	response = run_backtest(
		dataset_from_payload(payload),
		BacktestParams(start="2020-01-01", end="2020-05-15", cost_bps=0, short_borrow_bps=500),
	)
	row = response["results"]["extreme1"]["holdings"][0]
	days = (date.fromisoformat(row["end_date"]) - date.fromisoformat(row["execution_date"])).days
	assert days == 32
	assert row["funding_cost"] == pytest.approx(0.10 * 32 / 365)
	assert row["borrow_cost"] == pytest.approx(2 * 0.05 * 32 / 365)
	assert row["period_return"] == pytest.approx(-0.20 * 32 / 365)


def test_sharpe_uses_arithmetic_excess_returns_not_cagr():
	returns = [0.2, -0.2] * 6
	equity = [100.0]
	for value in returns:
		equity.append(equity[-1] * (1 + value))
	stats = performance_statistics(returns, [0] * 12, [0] * 12, equity, 366, 0)
	assert stats["cagr"] < 0
	assert stats["sharpe"] == pytest.approx(0, abs=1e-15)
	assert stats["annualized_volatility"] > 0
	assert stats["max_drawdown_monthly"] == pytest.approx(min(equity) / max(equity) - 1)


def test_cash_reference_changes_sharpe_and_zero_variance_is_typed():
	stats = performance_statistics([0.01, 0.03], [0.02, 0.02], [0, 0], [100, 101, 104.03], 60, 0)
	assert stats["sharpe"] == pytest.approx(0, abs=1e-14)
	constant = performance_statistics([0, 0], [0, 0], [0, 0], [100, 100, 100], 60, 0)
	assert constant["sharpe"] is None
	assert constant["metric_status"]["sharpe"] == "zero_excess_return_variance"


def test_ruin_stops_at_first_daily_close_and_never_recovers(monkeypatch):
	payload = fixture_payload()
	for row in payload["series"]["XLB_TR"]["observations"]:
		if row["date"] == "2020-01-03":
			row["value"] = 40
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	actual = result(dataset_from_payload(payload))
	assert actual["status"] == "ruined"
	assert actual["terminal_date"] == "2020-01-03"
	assert len(actual["holdings"]) == 1
	assert actual["equity_curve"][-1]["strategy"] == 0
	assert actual["stats"]["total_return"] == -1
	assert actual["stats"]["max_drawdown_monthly"] == -1
	assert actual["stats"]["cagr"] is None
	assert actual["stats"]["metric_status"]["cagr"] == "terminal_insolvency"
	assert actual["stats"]["periods"] == 0
	json.dumps(actual, allow_nan=False)


def test_legacy_coefficient_signs_are_explicitly_preserved():
	zero = {name: 0 for name in ("rates", "curve", "inflation", "vol", "credit")}
	momentum = dict.fromkeys(SECTORS, 0)
	rates = {row["symbol"]: row["score"] for row in score_sectors({**zero, "rates": 1}, momentum)}
	vol = {row["symbol"]: row["score"] for row in score_sectors({**zero, "vol": 1}, momentum)}
	# Hand expansion: XLK50-1*(-1)*18+(-1)*.25*8=66; XLF50-.8*18+.8*.25*8=37.2.
	assert rates["XLK"] == 66
	assert rates["XLF"] == pytest.approx(37.2)
	assert vol["XLV"] == 43
	assert vol["XLY"] == 55


def test_cagr_uses_actual_elapsed_days():
	stats = performance_statistics([0.1], [0], [0], [100, 110], 32, 0)
	assert stats["cagr"] == pytest.approx(math.pow(1.1, 365.25 / 32) - 1)


def test_ranked_short_weights_have_asymmetric_financial_effect(monkeypatch):
	payload = fixture_payload()
	for symbol, price in (("XLY", 110), ("XLU", 80)):
		for row in payload["series"][f"{symbol}_TR"]["observations"]:
			if row["date"] >= "2020-01-03":
				row["value"] = price
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	row = result(dataset_from_payload(payload), mode="ranked3")["holdings"][0]
	# Worst-ranked50% short loses5%; third-worst25% short gains5%.
	assert row["period_return"] == pytest.approx(0)
	assert row["short_contribution"] == pytest.approx(0)


@pytest.mark.parametrize("key", ["start", "end"])
def test_future_evaluation_dates_are_invalid_before_loading(key):
	with pytest.raises(ValidationError, match="future"):
		BacktestParams.model_validate({"start": "2020-01-01", key: "9999-12-31"})


def test_specification_matrix_and_modes_match_canonical_engine():
	from pathlib import Path

	from radar.engine import EXPOSURES, MODEL_VERSION

	with (Path(__file__).parents[1] / "engine-spec.json").open() as file:
		specification = json.load(file)
	assert specification["model_version"] == MODEL_VERSION
	assert {
		symbol: tuple(values) for symbol, values in specification["scoring"]["exposures"].items()
	} == EXPOSURES
	assert specification["scoring"]["status"] == "unvalidated_legacy_research"
	for mode, definition in specification["strategies"].items():
		assert (
			list(target_weights(mode, list(SECTORS)).values()) == definition["signed_rank_weights"]
		)


def test_funding_uses_actual_early_close_not_later_same_day_release(monkeypatch):
	payload = fixture_payload()
	for row in payload["series"]["DFF"]["observations"]:
		if row["date"] == "2020-11-27":
			# Thanksgiving Friday closes13:00NY; this15:00NY release is too late.
			row["value"] = 36.5
			row["available_at"] = "2020-11-27T20:00:00Z"
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	actual = run_backtest(
		dataset_from_payload(payload),
		BacktestParams(start="2020-11-01", end="2021-02-15", cost_bps=0, short_borrow_bps=0),
	)
	first = actual["results"]["extreme1"]["holdings"][0]
	# The new rate is first eligible Monday30th close, for one day toDec1;
	# it must not be retrospectively charged for the three-day holiday weekend.
	assert first["funding_cost"] == pytest.approx(0.365 / 365)


def test_optional_old_history_cannot_block_complete_twelve_month_warmup():
	payload = fixture_payload()
	for name in ("DGS2", "DGS10", "DFII10", "T10YIE", "VIXCLS", "BAMLH0A0HYM2"):
		payload["series"][name]["observations"] = [
			row for row in payload["series"][name]["observations"] if row["date"] >= "2018-12-01"
		]
	actual = run_backtest(dataset_from_payload(payload), params())
	assert actual["period"]["initial_normalization_months"] == 12
	assert actual["period"]["warmup_start"] == "2018-12-31"
	assert actual["period"]["first_execution"] == "2020-01-02"


def test_missing_mandatory_warmup_month_blocks_instead_of_compressing():
	payload = fixture_payload()
	payload["series"]["DFII10"]["observations"] = [
		row
		for row in payload["series"]["DFII10"]["observations"]
		if not row["date"].startswith("2019-06")
	]
	with pytest.raises(DataError) as error:
		run_backtest(dataset_from_payload(payload), params())
	assert error.value.code == "missing_macro_history"


@pytest.mark.parametrize("top_n", [1, 2, 3, 4, 5])
def test_ranked_top_n_keeps_disjoint_unit_gross_legs(top_n):
	weights = target_weights("ranked3", list(SECTORS), top_n)
	assert len(weights) == 2 * top_n
	assert sum(max(value, 0) for value in weights.values()) == pytest.approx(1)
	assert sum(min(value, 0) for value in weights.values()) == pytest.approx(-1)
	assert weights[SECTORS[0]] == (1 if top_n == 1 else 0.5)
	assert weights[SECTORS[-1]] == (-1 if top_n == 1 else -0.5)
	assert target_weights("extreme1", list(SECTORS), top_n) == {"XLB": 2, "XLY": -2}


@pytest.mark.parametrize(
	("frequency", "first_decision", "first_execution", "first_return", "scale"),
	[
		("weekly", "2020-01-03", "2020-01-06", "2020-01-13", 52),
		("monthly", "2019-12-31", "2020-01-02", "2020-02-03", 12),
		("quarterly", "2019-12-31", "2020-01-02", "2020-04-01", 4),
	],
)
def test_schedule_next_session_and_frequency_statistics(
	flat, frequency, first_decision, first_execution, first_return, scale
):
	actual = run_backtest(flat, params(rebalance=frequency, mode="ranked3", top_n=5))
	assert actual["period"]["first_decision"] == first_decision
	assert actual["period"]["first_execution"] == first_execution
	assert actual["period"]["first_return"] == first_return
	row = actual["results"]["ranked3"]
	assert row["stats"]["periods_per_year"] == scale
	assert row["stats"]["return_frequency"] == frequency
	assert len(row["holdings"][0]["weights"]) == 10
	assert row["benchmark_stats"]["total_return"] == 0


def test_frequency_scaling_is_not_always_monthly():
	monthly = performance_statistics(
		[0.1, -0.05, 0.2], [0.01] * 3, [0] * 3, [100, 110, 104.5, 125.4], 90, 1
	)
	weekly = performance_statistics(
		[0.1, -0.05, 0.2], [0.01] * 3, [0] * 3, [100, 110, 104.5, 125.4], 90, 1, periods_per_year=52
	)
	assert weekly["sharpe"] / monthly["sharpe"] == pytest.approx(math.sqrt(52 / 12))
	assert weekly["annualized_volatility"] / monthly["annualized_volatility"] == pytest.approx(
		math.sqrt(52 / 12)
	)
	assert weekly["cagr"] == monthly["cagr"]


def test_calendar_year_returns_rolling_excess_and_daily_drawdown_are_actual_marks():
	from radar.engine import _daily_research

	daily = [
		{"date": "2019-12-31", "strategy": 100, "benchmark": 100},
		{"date": "2020-01-02", "strategy": 120, "benchmark": 110},
		{"date": "2020-01-03", "strategy": 90, "benchmark": 105},
		{"date": "2020-12-31", "strategy": 121, "benchmark": 120},
		{"date": "2021-01-04", "strategy": 133.1, "benchmark": 126},
	]
	calendar = [date.fromisoformat(row["date"]) for row in daily] + [date(2021, 12, 31)]
	actual = _daily_research(daily, calendar)
	year = actual["annual_returns"][1]
	assert year["strategy"] == pytest.approx(0.21)
	assert year["benchmark"] == pytest.approx(0.20)
	assert year["excess"] == pytest.approx(0.01)
	assert year["partial"] is False
	assert actual["annual_returns"][0]["partial"] is True
	assert actual["annual_returns"][-1]["partial"] is True
	assert min(row["strategy"] for row in actual["drawdown_curve"]) == -0.25
	assert actual["rolling_excess"][0]["date"] == "2020-12-31"
	assert actual["rolling_excess"][0]["value"] == pytest.approx(0.01)


def test_weekly_decisions_do_not_train_on_future_month_end_macro():
	payload = fixture_payload()
	baseline = run_backtest(dataset_from_payload(payload), params(rebalance="weekly"))["results"][
		"extreme1"
	]["holdings"][0]
	for row in payload["series"]["DFII10"]["observations"]:
		if row["date"] >= "2020-01-15":
			row["value"] = 50
	actual = run_backtest(dataset_from_payload(payload), params(rebalance="weekly"))["results"][
		"extreme1"
	]["holdings"][0]
	assert actual["state"] == baseline["state"]
	assert actual["scores"] == baseline["scores"]


def test_realized_attribution_reconciles_after_costs_and_ranking_diagnostics(monkeypatch):
	payload = fixture_payload()
	for symbol, value in (("XLB", 110), ("XLY", 95)):
		for row in payload["series"][f"{symbol}_TR"]["observations"]:
			if row["date"] >= "2020-01-03":
				row["value"] = value
	_fixed_ranking(monkeypatch, [list(SECTORS)])
	actual = run_backtest(
		dataset_from_payload(payload),
		BacktestParams(start="2020-01-01", end="2020-05-15", cost_bps=10, short_borrow_bps=50),
	)["results"]["extreme1"]
	diagnostics = actual["diagnostics"]
	contributions = {row["symbol"]: row for row in diagnostics["attribution"]}
	assert contributions["XLB"]["long_contribution"] == pytest.approx(0.2)
	assert contributions["XLY"]["short_contribution"] == pytest.approx(0.1)
	assert sum(row["total_contribution"] for row in contributions.values()) - sum(
		diagnostics["cost_contributions"].values()
	) == pytest.approx(actual["stats"]["total_return"])
	assert diagnostics["rank_persistence"] == 1
	assert diagnostics["top_retention"] == 1
	assert diagnostics["top_beats_bottom_rate"] == 0.25
	assert diagnostics["average_top_return"] == pytest.approx(0.1 / 4)
	assert diagnostics["average_bottom_return"] == pytest.approx(-0.05 / 4)
	assert diagnostics["average_top_bottom_spread"] == pytest.approx(0.15 / 4)
	assert diagnostics["ranking_return_frequency"] == "monthly"
	assert diagnostics["positive_net_spread_rate"] == 0.25
	assert diagnostics["average_holding_days"] == 120
	assert diagnostics["regime_performance"][0]["periods"] == 4


def test_ranking_return_averages_exclude_incomplete_cycles():
	from radar.engine import _ranking_diagnostics

	rows = []
	for start, end, top, bottom, complete in (
		("2020-01-06", "2020-01-13", 0.1, -0.04, True),
		("2020-01-13", "2020-01-21", -0.02, 0.06, True),
		("2020-01-21", "2020-01-22", -0.6, 0.7, False),
	):
		rows.append(
			{
				"execution_date": start,
				"end_date": end,
				"top_return": top,
				"bottom_return": bottom,
				"complete": complete,
				"regime": "balanced",
				"period_return": top - bottom,
				"benchmark_return": 0,
				"weights": {"XLB": 1, "XLY": -1},
				"scores": [{"symbol": symbol} for symbol in SECTORS],
			}
		)
	diagnostics = _ranking_diagnostics(rows)
	assert diagnostics["average_top_return"] == pytest.approx(0.04)
	assert diagnostics["average_bottom_return"] == pytest.approx(0.01)
	assert diagnostics["average_top_bottom_spread"] == pytest.approx(0.03)
	assert diagnostics["top_beats_bottom_rate"] == 0.5


def test_score_components_are_points_and_sum_to_the_preserved_score():
	from radar.engine import sector_score_components

	state = {"rates": 0.2, "curve": -0.1, "inflation": 0.3, "vol": 0.8, "credit": -0.6}
	momentum = {symbol: 0.15 for symbol in SECTORS}
	for row in score_sectors(state, momentum):
		assert (
			50 + sum(sector_score_components(state, 0.15, row["symbol"]).values()) == row["score"]
		)


def test_chart_sampling_retains_endpoints_and_extreme_losses():
	from radar.engine import _sample_chart

	points = [
		{"date": str(index), "strategy": -(index % 47) / 100, "benchmark": -(index % 53) / 100}
		for index in range(2000)
	]
	points[987]["strategy"] = -0.99
	actual = _sample_chart(points, ("strategy", "benchmark"))
	assert len(actual) <= 400
	assert actual[0] == points[0]
	assert actual[-1] == points[-1]
	assert min(row["strategy"] for row in actual) == -0.99
