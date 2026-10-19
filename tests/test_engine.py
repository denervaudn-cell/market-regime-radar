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
		{"rebalance": "weekly"},
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
