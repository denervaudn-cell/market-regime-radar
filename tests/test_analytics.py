"""Independent references for the restored descriptive research calculations."""

import json
import math
from datetime import UTC, date, datetime, timedelta
from statistics import stdev

import pytest

from radar.analytics import (
	FX_PAIRS,
	TITLES,
	_analogue_candidates,
	_analogue_features,
	_contributions,
	_correlations,
	_fx_composites,
	_Inputs,
	_percentile,
	_rates,
	_risk_at,
	_sector_values,
	_volatility,
	_zscore,
	market_analytics,
)
from radar.data import Observation
from radar.engine import score_sectors
from radar.mock import generate_mock_dataset

NOW = datetime(2025, 1, 18, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def dataset():
	return generate_mock_dataset(date(2025, 1, 17), seed=8042)


@pytest.fixture(scope="module")
def result(dataset):
	return market_analytics(dataset, NOW)


def changed_series(dataset, name, *, rows=None, **updates):
	"""Vary a validated fixture's observations without retesting content hashing."""
	series = dataset.series[name]
	if rows is not None:
		updates["observations"] = tuple(rows)
	series = {**dataset.series, name: series.model_copy(update=updates)}
	return dataset.model_copy(update={"series": series})


def metric(section, label):
	return next(item["value"] for item in section["metrics"] if item["label"] == label)


def test_full_mock_produces_all_ten_real_calculated_sections(result):
	assert result["ok"] is True
	assert result["status"] == "ready"
	assert set(result["sections"]) == set(TITLES)
	assert all(section["status"] == "ready" for section in result["sections"].values())
	assert len(result["inputs"]) >= 40
	assert result["input_issues"] == {}
	json.dumps(result, allow_nan=False)
	for section in result["sections"].values():
		assert section["summary"]
		for table in section["tables"]:
			assert all(len(row) == len(table["columns"]) for row in table["rows"])
		for chart in section["charts"]:
			assert all(
				set(point) == {"date", "value"}
				for series in chart["series"]
				for point in series["points"]
			)


def test_risk_scores_are_additive_bounded_and_not_probabilities(dataset, result):
	data = _Inputs(dataset, NOW)
	for horizon in (1, 5, 20):
		risk = _risk_at(data, data.index, horizon)
		assert sum(factor["weight"] for factor in risk["factors"]) == pytest.approx(1)
		assert risk["score"] == pytest.approx(
			sum(factor["contribution"] for factor in risk["factors"])
		)
		assert -100 <= risk["score"] <= 100
		assert risk["strength"] == abs(risk["score"])
	assert "not a forecast probability" in result["sections"]["risk"]["summary"]


def test_realized_volatility_matches_independent_log_return_reference(dataset):
	data = _Inputs(dataset, NOW)
	levels = [row.value for row in dataset.series["SPY_TR"].observations]
	for window in (5, 10, 20, 60):
		returns = [
			math.log(current / previous)
			for previous, current in zip(levels[-window - 1 : -1], levels[-window:], strict=True)
		]
		assert data.rv(window) == pytest.approx(stdev(returns) * math.sqrt(252) * 100)
	vol = _volatility(data)
	assert metric(vol, "IV−RV20 premium") == pytest.approx(
		data.at("VIXCLS") - data.rv(20), abs=1e-6
	)
	assert metric(vol, "IV/RV20") == pytest.approx(data.at("VIXCLS") / data.rv(20), abs=1e-6)


def test_return_analytics_ignore_quoted_price_splits(dataset):
	rows = list(dataset.series["SPY"].observations)
	rows[-1] = rows[-1].model_copy(update={"value": rows[-1].value / 2})
	altered = changed_series(dataset, "SPY", rows=rows)
	assert _Inputs(dataset, NOW).rv(20) == _Inputs(altered, NOW).rv(20)
	assert _Inputs(dataset, NOW).delta("SPY_TR") == _Inputs(altered, NOW).delta("SPY_TR")


def test_rate_spreads_and_decomposition_use_native_percent_units(dataset):
	data = _Inputs(dataset, NOW)
	rates = _rates(data)
	assert metric(rates, "2s10s slope") == pytest.approx(
		data.at("DGS10") - data.at("DGS2"), abs=1e-6
	)
	assert metric(rates, "2×5Y−2Y−10Y curvature") == pytest.approx(
		2 * data.at("DGS5") - data.at("DGS2") - data.at("DGS10"), abs=1e-6
	)
	assert metric(rates, "10Y nominal−real−breakeven residual") == pytest.approx(0, abs=1e-6)
	assert metric(rates, "5Y5Y forward inflation") == pytest.approx(data.at("T5YIFR"), abs=1e-6)


def test_curve_does_not_join_different_observation_dates(dataset):
	altered = changed_series(dataset, "DGS2", rows=dataset.series["DGS2"].observations[:-1])
	data = _Inputs(altered, NOW)
	assert data.at("DGS2") is not None  # Individually labelled recent observation remains visible.
	assert data.curve[-1] is None
	rates = _rates(data)
	assert metric(rates, "2s10s slope") is None
	assert metric(rates, "Curve level") is None
	assert rates["status"] == "partial"


def test_correlations_require_identical_intervals_and_adequate_samples(dataset):
	data = _Inputs(dataset, NOW)
	assert data.corr("SPY_TR", "SPY_TR", 20) == pytest.approx(1)
	rows = list(dataset.series["TLT_TR"].observations)
	rows.pop(-5)
	altered = changed_series(dataset, "TLT_TR", rows=rows)
	missing = _Inputs(altered, NOW)
	assert sum(value is None for value in missing.change("TLT_TR")[-20:]) == 2
	assert missing.corr("SPY_TR", "TLT_TR", 20) is not None
	rows = rows[:-15] + rows[-3:]
	missing = _Inputs(changed_series(dataset, "TLT_TR", rows=rows), NOW)
	assert missing.corr("SPY_TR", "TLT_TR", 20) is None


def test_constant_returns_have_no_spurious_correlation_or_iv_ratio(dataset):
	rows = [
		row.model_copy(update={"value": 100.0}) for row in dataset.series["SPY_TR"].observations
	]
	data = _Inputs(changed_series(dataset, "SPY_TR", rows=rows), NOW)
	assert data.corr("SPY_TR", "SPY_TR", 20) is None
	assert data.rv(20) == 0
	assert metric(_volatility(data), "IV/RV20") is None
	assert metric(_correlations(data), "Equity/bond 20D") is None
	assert _volatility(data)["status"] == "partial"
	assert _correlations(data)["status"] == "partial"


def test_mismatched_volatility_observation_dates_do_not_publish_premiums(dataset):
	altered = changed_series(dataset, "VIXCLS", rows=dataset.series["VIXCLS"].observations[:-1])
	volatility = _volatility(_Inputs(altered, NOW))
	assert metric(volatility, "VIX implied volatility") is not None
	assert metric(volatility, "Realized volatility 20D") is not None
	assert metric(volatility, "IV−RV20 premium") is None
	assert metric(volatility, "IV/RV20") is None
	assert metric(volatility, "MOVE/VIX") is None
	assert volatility["status"] == "partial"


def test_restored_history_panels_are_consistent_with_current_measures(dataset, result):
	sections = result["sections"]
	risk_chart = sections["risk"]["charts"][0]
	assert all(len(series["points"]) == 252 for series in risk_chart["series"])
	for series, horizon in zip(risk_chart["series"], ("1D", "1W", "1M"), strict=True):
		assert series["points"][-1]["value"] == metric(sections["risk"], f"{horizon} risk score")
	acceleration = next(
		table
		for table in sections["changes"]["tables"]
		if table["title"] == "Five-session signal acceleration"
	)
	spy = next(row for row in acceleration["rows"] if row[0] == "SPY")
	data = _Inputs(dataset, NOW)
	assert spy[-1] == pytest.approx(
		100 * (data.delta("SPY_TR") - data.delta("SPY_TR", index=data.index - 1)), abs=1e-6
	)
	gap_chart = next(
		chart for chart in sections["correlations"]["charts"] if "break history" in chart["title"]
	)
	assert gap_chart["series"][0]["points"][-1]["value"] == metric(
		sections["correlations"], "20D−60D difference"
	)
	vrp_chart = next(
		chart for chart in sections["volatility"]["charts"] if "premium" in chart["title"]
	)
	assert len(vrp_chart["series"][0]["points"]) == 252
	assert vrp_chart["series"][0]["points"][-1]["value"] == metric(
		sections["volatility"], "IV−RV20 premium"
	)
	assert metric(sections["volatility"], "3M−1M term slope") == pytest.approx(
		data.at("VIX3M") - data.at("VIXCLS"), abs=1e-6
	)
	comparison = next(
		table
		for table in sections["analogues"]["tables"]
		if table["title"].startswith("What matched")
	)
	assert len(comparison["rows"]) == 6
	assert all(row[3] == pytest.approx(row[1] - row[2], abs=2e-6) for row in comparison["rows"])


def test_percentile_ties_and_zscore_minimum_sample_are_explicit():
	assert _percentile(1, [1.0] * 60) == 50
	assert _percentile(2, [1.0] * 60) == 100
	assert _percentile(1, [1.0] * 59) is None
	assert _zscore(1, [1.0] * 60) == 0
	assert _zscore(2, [1.0] * 60) is None


def test_future_release_and_late_revision_cannot_rewrite_past_state(dataset):
	name = "DFII10"
	rows = list(dataset.series[name].observations)
	index = 500
	old = rows[index]
	revision = old.model_copy(
		update={"value": old.value + 20, "available_at": NOW + timedelta(days=2)}
	)
	rows.append(revision)
	rows.sort(key=lambda row: (row.date, row.available_at))
	data = _Inputs(changed_series(dataset, name, rows=rows), NOW)
	assert data.at(name, index) == old.value
	assert data.at(name) == _Inputs(dataset, NOW).at(name)


def test_economic_date_after_ny_cutoff_is_retained_until_its_day(dataset):
	rows = list(dataset.series["DGS10"].observations)
	# The validated schema permits UTC midnight Tuesday, which is Monday in New York.
	index = next(i for i, row in enumerate(rows[100:], start=100) if row.date.weekday() == 1)
	rows[index] = Observation(
		date=rows[index].date,
		value=99.0,
		available_at=datetime.combine(rows[index].date, datetime.min.time(), UTC),
	)
	data = _Inputs(changed_series(dataset, "DGS10", rows=rows), NOW)
	assert data.at("DGS10", index - 1) != 99
	assert data.at("DGS10", index) == 99


def test_late_revisions_do_not_replace_more_recent_economic_dates(dataset):
	rows = list(dataset.series["DGS10"].observations)
	rows.append(rows[-20].model_copy(update={"value": 99.0, "available_at": rows[-1].available_at}))
	rows.sort(key=lambda row: (row.date, row.available_at))
	data = _Inputs(changed_series(dataset, "DGS10", rows=rows), NOW)
	assert data.at("DGS10") == dataset.series["DGS10"].observations[-1].value


def test_sector_scores_and_factor_contributions_share_the_engine_formula(dataset):
	data = _Inputs(dataset, NOW)
	ranked, state, momentum = _sector_values(data)
	assert ranked == score_sectors(state, momentum)
	assert len(ranked) == 11
	for row in ranked:
		assert 50 + sum(
			_contributions(row["symbol"], state, momentum[row["symbol"]]).values()
		) == pytest.approx(row["score"])
	assert all(-1 <= value <= 1 for value in state.values())


def test_fx_dollar_orientation_is_consistent_for_base_and_quote_currency(dataset):
	altered = dataset
	for name in FX_PAIRS:
		rows = list(altered.series[name].observations)
		factor = 1.2 if name.startswith("USD") else 0.8 if name.endswith("USD") else 1.0
		rows[-1] = rows[-1].model_copy(update={"value": rows[-1].value * factor})
		altered = changed_series(altered, name, rows=rows)
	data = _Inputs(altered, NOW)
	dollar, risk = _fx_composites(data, data.index)
	assert dollar == pytest.approx(100)
	assert risk < -20
	wrong_units = _Inputs(changed_series(dataset, "EURUSD", unit="EUR/USD"), NOW)
	assert wrong_units.at("EURUSD") is None
	assert "orientation" in wrong_units.errors["EURUSD"]


def test_analogue_dates_are_nonoverlapping_with_complete_eligible_windows(dataset):
	data = _Inputs(dataset, NOW)
	selected = _analogue_candidates(data)
	assert 1 <= len(selected) <= 8
	assert all(row["index"] + 20 < data.index for row in selected)
	assert all(
		abs(a["index"] - b["index"]) > 20 for i, a in enumerate(selected) for b in selected[i + 1 :]
	)
	assert all(0 < row["similarity"] <= 100 for row in selected)
	assert [row["distance"] for row in selected] == sorted(row["distance"] for row in selected)


def test_analogue_features_and_selection_do_not_read_forward_outcomes(dataset, monkeypatch):
	data = _Inputs(dataset, NOW)
	index = 800
	baseline = _analogue_features(data, index)
	rows = list(dataset.series["SPY_TR"].observations)
	for i in range(index + 1, len(rows)):
		rows[i] = rows[i].model_copy(update={"value": rows[i].value * 1.5})
	altered = _Inputs(changed_series(dataset, "SPY_TR", rows=rows), NOW)
	assert _analogue_features(altered, index) == baseline

	def reject_outcome_access(*args, **kwargs):
		raise AssertionError("Candidate selection must not read forward outcome helpers")

	monkeypatch.setattr(data, "delta", reject_outcome_access)
	assert _analogue_candidates(data)


def test_missing_extended_inputs_remain_null_and_partial(dataset):
	series = {
		key: value
		for key, value in dataset.series.items()
		if key not in {"VIX3M", "T5YIFR", "AUDJPY", "TLT_TR"}
	}
	result = market_analytics(dataset.model_copy(update={"series": series}), NOW)
	assert result["status"] == "partial"
	assert result["sections"]["risk"]["status"] == "unavailable"
	assert metric(result["sections"]["volatility"], "VIX9D/VIX3M") is None
	assert metric(result["sections"]["rates"], "5Y5Y forward inflation") is None
	assert metric(result["sections"]["fx"], "Risk FX score") is None
	assert "AUDJPY" in result["input_issues"]
	json.dumps(result, allow_nan=False)


def test_stale_and_unavailable_snapshots_never_claim_current_success(dataset):
	stale = market_analytics(dataset, datetime(2025, 1, 22, 23, tzinfo=UTC))
	assert stale["status"] == "stale"
	assert stale["ok"] is False
	assert all(
		section["summary"].startswith("STALE SNAPSHOT") for section in stale["sections"].values()
	)
	future = market_analytics(dataset, datetime(2025, 1, 17, 18, tzinfo=UTC))
	assert future["status"] == "unavailable"
	assert all(not section["metrics"] for section in future["sections"].values())
	with pytest.raises(ValueError, match="timezone"):
		market_analytics(dataset, datetime(2025, 1, 18))
