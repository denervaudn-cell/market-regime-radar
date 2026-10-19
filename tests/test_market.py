"""Reference cases for date joins, missingness, freshness and honest publication."""

from datetime import UTC, date, datetime

import pytest

from radar.data import Dataset, dataset_content_id, exchange_sessions
from radar.market import ASSETS, market_snapshot

NOW = datetime(2025, 1, 18, 12, tzinfo=UTC)


def market_raw():
	calendar = exchange_sessions(date(2024, 5, 1), date(2025, 2, 28))
	days = [day for day in calendar if day <= date(2025, 1, 17)]
	series = {}
	for symbol in ASSETS:
		price = 100
		rows = []
		for index, day in enumerate(days):
			change = (0.01 if index % 2 else -0.004) * (-1 if symbol == "QQQ" else 1)
			price *= 1 + change
			rows.append(
				{"date": day.isoformat(), "available_at": f"{day}T22:00:00Z", "value": price}
			)
		series[symbol] = {
			"id": symbol,
			"source": "synthetic test only",
			"unit": "USD",
			"currency": "USD",
			"price_basis": "close",
			"observations": rows,
		}
	for symbol in ASSETS:
		series[f"{symbol}_TR"] = {
			**series[symbol],
			"id": f"{symbol}_TR",
			"price_basis": "total_return_net",
			"unit": "index",
			"observations": [dict(row) for row in series[symbol]["observations"]],
		}
	for key, value in {
		"DGS2": 4,
		"DGS5": 4.2,
		"DGS10": 4.4,
		"DGS30": 4.7,
		"DFII10": 2,
		"T10YIE": 2.4,
		"VIXCLS": 20,
		"BAMLH0A0HYM2": 4,
	}.items():
		series[key] = {
			"id": key,
			"source": "synthetic test only",
			"unit": "index" if key == "VIXCLS" else "percent",
			"price_basis": "index" if key == "VIXCLS" else "rate",
			"observations": [
				{
					"date": days[-1].isoformat(),
					"available_at": f"{days[-1]}T22:00:00Z",
					"value": value,
				}
			],
		}
	return {
		"generated_at": "2025-01-17T23:00:00Z",
		"as_of": "2025-01-17",
		"calendar": [day.isoformat() for day in calendar],
		"series": series,
	}


def validated(raw):
	raw["dataset_id"] = dataset_content_id(raw)
	return Dataset.model_validate(raw)


def test_complete_market_has_observed_inputs_but_no_invented_risk_score():
	result = market_snapshot(validated(market_raw()), NOW)
	assert result["status"] == "ready"
	assert result["ok"] is True
	assert result["metadata"]["expected_session"] == "2025-01-17"
	assert result["assets"][0]["latest"] > 0
	assert result["risk_bias"]["score"] is None
	assert result["risk_bias"]["status"] == "unavailable"
	assert [factor["id"] for factor in result["risk_bias"]["factors"]] == [
		"SPY",
		"VIXCLS",
		"BAMLH0A0HYM2",
	]
	assert result["panels"]["fx"]["status"] == "unavailable"
	assert result["panels"]["robustness"]["status"] == "unavailable"
	assert result["panels"]["sector_ranking"]["status"] == "unavailable"
	assert all(row["source"] == "synthetic test only" for row in result["assets"])


def test_returns_are_correlated_on_identical_daily_intervals():
	raw = market_raw()
	result = market_snapshot(validated(raw), NOW)
	assert result["correlation"]["sample_sizes"][0][1] == 20
	assert result["correlation"]["matrix"][0][1] == pytest.approx(-1)
	# A missing intermediate day invalidates both adjacent daily intervals.
	del raw["series"]["QQQ_TR"]["observations"][-5]
	result = market_snapshot(validated(raw), NOW)
	assert result["correlation"]["sample_sizes"][0][1] == 18
	assert result["correlation"]["matrix"][0][1] == pytest.approx(-1)
	assert result["assets"][1]["change_20d"] is None


def test_non_overlapping_dates_and_small_samples_have_no_correlation():
	raw = market_raw()
	raw["series"]["QQQ_TR"]["observations"] = raw["series"]["QQQ_TR"]["observations"][:30]
	result = market_snapshot(validated(raw), NOW)
	assert result["correlation"]["matrix"][0][1] is None
	assert result["correlation"]["sample_sizes"][0][1] == 0
	assert result["assets"][1]["status"] == "stale"
	raw = market_raw()
	raw["series"]["QQQ_TR"]["observations"] = raw["series"]["QQQ_TR"]["observations"][-10:]
	result = market_snapshot(validated(raw), NOW)
	assert result["correlation"]["matrix"][0][1] is None
	assert result["correlation"]["sample_sizes"][0][1] == 9


def test_holiday_and_weekend_freshness_uses_exchange_calendar():
	dataset = validated(market_raw())
	# Martin Luther King Day, Monday 20 January, is not an exchange session.
	assert market_snapshot(dataset, datetime(2025, 1, 20, 23, tzinfo=UTC))["status"] == "ready"
	assert market_snapshot(dataset, datetime(2025, 1, 21, 14, tzinfo=UTC))["status"] == "ready"
	result = market_snapshot(dataset, datetime(2025, 1, 21, 22, tzinfo=UTC))
	assert result["status"] == "stale"
	assert result["metadata"]["expected_session"] == "2025-01-21"


def test_fresh_generated_at_does_not_mask_old_observations():
	raw = market_raw()
	raw["generated_at"] = "2025-01-24T23:00:00Z"
	raw["as_of"] = "2025-01-24"
	result = market_snapshot(validated(raw), datetime(2025, 1, 25, 12, tzinfo=UTC))
	assert result["status"] == "stale"
	assert result["assets"][0]["as_of"] == "2025-01-17"
	assert result["risk_bias"]["factors"] == []


def test_future_generation_and_exhausted_calendar_are_unavailable():
	dataset = validated(market_raw())
	assert (
		market_snapshot(dataset, datetime(2025, 1, 17, 22, tzinfo=UTC))["status"] == "unavailable"
	)
	assert market_snapshot(dataset, datetime(2025, 3, 1, 12, tzinfo=UTC))["status"] == "unavailable"
	with pytest.raises(ValueError):
		market_snapshot(dataset, datetime(2025, 1, 18))


def test_quoted_close_and_total_return_are_never_interchanged():
	raw = market_raw()
	raw["series"]["SPY"]["price_basis"] = "total_return_net"
	raw["series"]["SPY"]["unit"] = "index"
	result = market_snapshot(validated(raw), NOW)
	assert result["assets"][0]["status"] == "unavailable"
	assert result["correlation"]["matrix"][0][1] == pytest.approx(-1)
	assert not any(factor["id"] == "SPY" for factor in result["risk_bias"]["factors"])


def test_curve_spread_joins_observation_date_and_optional_fx_is_genuine():
	raw = market_raw()
	result = market_snapshot(validated(raw), NOW)
	slope = next(row for row in result["panels"]["yield_curve"]["items"] if "slope" in row["label"])
	assert slope["value"] == pytest.approx(0.4)
	assert slope["unit"] == "percentage_points"
	raw["series"]["DGS2"]["observations"][0]["date"] = "2025-01-16"
	raw["series"]["EURUSD"] = {
		"id": "EURUSD",
		"source": "synthetic FX test",
		"price_basis": "fx",
		"unit": "USD/EUR",
		"observations": [
			{"date": "2025-01-17", "available_at": "2025-01-17T23:00:00Z", "value": 1.04}
		],
	}
	result = market_snapshot(validated(raw), NOW)
	assert not any("slope" in row["label"] for row in result["panels"]["yield_curve"]["items"])
	assert result["panels"]["fx"]["items"][0]["value"] == 1.04


def test_missing_series_has_no_synthetic_success_or_default_values():
	raw = market_raw()
	del raw["series"]["SPY"]
	result = market_snapshot(validated(raw), NOW)
	assert result["ok"] is False
	assert result["status"] == "unavailable"
	assert result["assets"][0]["latest"] is None
	assert result["risk_bias"]["score"] is None


def test_split_and_dividend_do_not_create_false_price_return_signals():
	raw = market_raw()
	# An independently constructed split: quote halves, invested wealth stays flat.
	for row in raw["series"]["SPY_TR"]["observations"]:
		row["value"] = 100
	raw["series"]["SPY"]["observations"][-2]["value"] = 100
	raw["series"]["SPY"]["observations"][-1]["value"] = 50
	result = market_snapshot(validated(raw), NOW)
	spy = result["assets"][0]
	assert spy["latest"] == 50
	assert spy["change_1d"] == 0
	assert spy["change_20d"] == 0
	assert spy["percentile"] == 50
	assert spy["z_1d"] is None
	assert result["correlation"]["matrix"][0][1] is None
	# A cash distribution lowers the quote while dividend-reinvested wealth grows.
	raw["series"]["SPY"]["observations"][-1]["value"] = 99
	raw["series"]["SPY_TR"]["observations"][-1]["value"] = 101
	spy = market_snapshot(validated(raw), NOW)["assets"][0]
	assert spy["latest"] == 99
	assert spy["change_1d"] == pytest.approx(0.01)


def test_missing_or_mixed_total_return_never_falls_back_to_quotes():
	raw = market_raw()
	del raw["series"]["SPY_TR"]
	result = market_snapshot(validated(raw), NOW)
	assert result["assets"][0]["latest"] is not None
	assert result["assets"][0]["change_1d"] is None
	assert result["status"] == "unavailable"
	raw = market_raw()
	raw["series"]["SPY_TR"]["price_basis"] = "total_return_gross"
	result = market_snapshot(validated(raw), NOW)
	assert all(asset["change_1d"] is None for asset in result["assets"])
	assert result["metadata"]["return_basis"] == "unavailable"
