"""Bounded sensitivity and regime studies over one immutable input snapshot."""

from radar.data import DataError, Dataset
from radar.engine import (
	MODEL_VERSION,
	BacktestParams,
	_History,
	_prepare,
	_simulate,
	_validate_finite_result,
)


def run_studies(dataset: Dataset, params: BacktestParams) -> dict:
	"""Evaluate nine ranked-basket variants and four fee scenarios.

	History indexing is shared and each frequency is prepared once. Failed variants
	remain explicit rows; they never borrow a valid result from a different period.
	The grid is descriptive in-sample sensitivity, not parameter selection evidence.
	"""
	history = _History(dataset)
	prepared = {}
	errors = {}
	for frequency in ("weekly", "monthly", "quarterly"):
		try:
			prepared[frequency] = _prepare(
				dataset, params.model_copy(update={"rebalance": frequency}), history
			)
		except DataError as error:
			errors[frequency] = {"code": error.code, "message": str(error)}
	robustness = []
	for frequency in ("weekly", "monthly", "quarterly"):
		for top_n in (1, 3, 5):
			row = {"top_n": top_n, "rebalance": frequency}
			if frequency in errors:
				robustness.append(
					{**row, "status": "unavailable", "error": errors[frequency], "stats": None}
				)
				continue
			variant = params.model_copy(
				update={"rebalance": frequency, "top_n": top_n, "mode": "ranked3"}
			)
			result = _simulate(prepared[frequency], variant, "ranked3")
			robustness.append(
				{
					**row,
					"status": result["status"],
					"stats": result["stats"],
					"period": prepared[frequency]["period"],
				}
			)
	if params.rebalance in errors:
		raise DataError(errors[params.rebalance]["code"], errors[params.rebalance]["message"])
	mode = "ranked3" if params.mode == "compare" else params.mode
	base = prepared[params.rebalance]
	sensitivity = []
	for cost in (0, 10, 25, 50):
		result = _simulate(
			base, params.model_copy(update={"cost_bps": float(cost), "mode": mode}), mode
		)
		sensitivity.append({"cost_bps": cost, "status": result["status"], "stats": result["stats"]})
	selected = _simulate(base, params.model_copy(update={"mode": mode}), mode)
	response = {
		"ok": True,
		"dataset_id": dataset.dataset_id,
		"model_version": MODEL_VERSION,
		"params": params.model_dump(mode="json"),
		"period": base["period"],
		"strategy": selected["strategy"],
		"robustness": robustness,
		"cost_sensitivity": sensitivity,
		"regime_performance": selected["diagnostics"]["regime_performance"],
		"methodology": [
			"Robustness grid always evaluates ranked +100%/-100% baskets: Top 1/3/5 by weekly/monthly/quarterly schedule.",
			"Each frequency uses its own first and last complete execution cycle, explicitly reported; compare actual dates before comparing metrics.",
			"Cost sensitivity uses the selected strategy, or ranked basket when comparing all strategies, with unchanged funding and borrow assumptions.",
			"Regimes use only decision-time normalized states: stress if volatility or credit >=0.5; otherwise inflation if inflation >=0.5; otherwise low stress if both volatility and credit <0; otherwise balanced.",
			"Regime hit rate means strategy net return exceeds SPY over a complete cycle. Small samples and parameter search are not evidence of out-of-sample validity.",
		],
	}
	_validate_finite_result(response)
	return response
