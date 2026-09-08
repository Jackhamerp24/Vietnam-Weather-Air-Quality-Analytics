"""Phase 6: pre-registered sensor-level weather-PM2.5 association statistics.

Read-only replay from the frozen Phase 5 EDA bundle. No database access,
no model training, no operational forecast claims.
"""

import hashlib
import json
import math
import random
from pathlib import Path

from vn_air.eda import EDA_POLICY, descriptive_correlation
from vn_air.ingestion.parsing import timestamp
from vn_air.quality import digest, finite

STATS_VERSION = "phase6_statistics_v2"
SEED = 20260908
REPLICATES = 2000
BLOCK_DAYS = (1, 2, 7)
PRIMARY_BLOCK_DAYS = 1
GATE_MIN_NONEMPTY = 30
GATE_MIN_ELIGIBLE = 20
PIVOT_TOL = 1e-8
MAX_SKIP_FRACTION = 0.05
PRIMARY_EXPOSURES = (("H1", "wind_speed_10m"), ("H2", "relative_humidity_2m"))
SECONDARY_EXPOSURES = ("temperature_2m", "precipitation", "surface_pressure", "cloud_cover", "shortwave_radiation")
DESCRIPTIVE_ONLY_EXPOSURES = ("apparent_temperature", "wind_direction_10m")
SENSORS = {"cmt8": "CMT8", "oceanpark": "OceanPark"}
REFERENCE_SENSOR = "cmt8"
WEATHER_CASES = ("pairwise_complete", "complete_weather", "not_applicable")
FROZEN_BUNDLE_SHA256 = "92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63"
FROZEN_WINDOW = {"cutoff": "2026-09-06T20:59:00.669630Z",
                 "start": "2026-06-08T00:00:00Z", "end": "2026-09-06T00:00:00Z"}
EXPECTED_DATE_START = "2026-06-08"
EXPECTED_DATE_END = "2026-09-06"
EXPECTED_DATE_COUNT = 91
FROZEN_COUNTS = {"accepted_rows": 4191, "absent_rows": 129, "accepted_cmt8": 2154,
                 "accepted_oceanpark": 2037, "complete_weather_cmt8": 2033,
                 "complete_weather_oceanpark": 1916, "shared_accepted_hours": 2035}
MAX_BUNDLE_BYTES = 40_000_000
STATS_POLICY = {
    "inputs": "Replay of the frozen Phase 5 EDA bundle; no database access, no re-extraction",
    "response": "Primary scale log1p(PM2.5) on accepted rows only; raw PM2.5 as labelled sensitivity; no imputation",
    "adjustment_set": "sensor fixed effect (pooled/shared fits), Vietnam local-hour fixed effects, weekday fixed effects, centered linear day_index",
    "reference_levels": "local hour 0 and Monday are reference; empty levels dropped deterministically before rank check",
    "standardization": "Exposure standardized on the eligible rows of each fit; means and scales recorded in the manifest",
    "estimand": "Adjusted change in the response per one analysis-window standard deviation of the exposure (sensor indicator for H3)",
    "weather_cases": "pairwise_complete: accepted response plus finite exposure only; complete_weather: additionally finite values for every weather variable observed in the bundle rows; not_applicable: H3 site contrast without an exposure term",
    "uncertainty": "Moving-block bootstrap over Vietnam local calendar days; percentile 95% interval; gaps preserved inside blocks",
    "blocks": "Block = contiguous local calendar dates (1/2/7 days); moving starts; pooled and shared fits resample dates jointly for both sensors",
    "draw_policy": "Each replicate draws divmod(n_dates, block_days) full-length moving windows plus one remainder-length window when the remainder is nonzero, so every replicate spans exactly n_dates study dates (91 here)",
    "replicates": "2000 per fit; CPython Mersenne Twister seeded 20260908, one generator, fits in fixed enumeration order, replicates outer, draws inner",
    "p_value": "Two-sided bootstrap tail statistic 2*min(P(beta<=0), P(beta>=0)) as (count+1)/(usable+1); only when block gates pass",
    "gates": "Inferential output requires >=30 non-empty and >=20 eligible non-overlapping independent partitions of the ordered local calendar dates anchored at the first frozen study date; overlapping moving windows are resampling candidates only (candidate_windows) and never the gate",
    "rank_policy": "Full-sample rank deficiency stops the run; rank-deficient replicates are discarded, and the run stops above a 5% discard fraction",
    "inference_labels": "inferential only for Holm/BH-adjusted declared-family members; exploratory for gate-passing unadjusted fits; descriptive_only when the gate fails or the output is descriptive",
    "multiple_testing": "Holm over the two primary p-values (H1 pooled, H2 pooled); Benjamini-Hochberg over the five declared secondary p-values; other p-values unadjusted and exploratory",
    "extreme_rule": "Sensitivity only: accepted rows above the within-sensor Tukey fence Q3+3*IQR are excluded in a labelled refit; no deletion or relabeling",
    "scope": "Sensor-level associations over the frozen window; no city-wide exposure, causal effect, forecast skill or health claim",
}
LIMITATIONS = [
    "Two non-reference low-cost sensor sites over one 90-day window; no city-wide exposure, seasonal or population inference.",
    "Associations are adjusted for temporal structure only; residual confounding, sensor bias and calibration uncertainty remain.",
    "ERA5 is retrospective reanalysis at model resolution; it is not a site measurement and its retrieval time is not historical availability.",
    "CAMS and provider forecasts are excluded from these measured-target models.",
    "Bootstrap blocks are approximately independent; serial dependence beyond the block length may remain.",
    "Overlapping moving windows are resampling candidates, not independent evidence units; the gate uses non-overlapping date partitions.",
    "Seven-day block sensitivity fits have 13 independent partitions and are descriptive-only under the 30-partition gate by construction.",
    "Site-specific, raw-scale, block-length, complete-weather and extreme-value results are unadjusted exploratory sensitivity output.",
    "No causal effect, forecast skill, health guidance or model-performance claim is supported.",
]


class RankDeficient(ValueError):
    pass


def sig(value, digits=12):
    return None if value is None else float(f"{value:.{digits}g}")


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def mean_stdev(values):
    if len(values) < 2:
        raise ValueError("Standard deviation needs at least two values")
    m = sum(values) / len(values)
    return m, math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def holm(pvalues):
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted, running = [0.0] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def benjamini_hochberg(pvalues):
    count = len(pvalues)
    order = sorted(range(count), key=lambda i: pvalues[i])
    adjusted, running = [0.0] * count, 1.0
    for rank in range(count - 1, -1, -1):
        i = order[rank]
        running = min(running, count * pvalues[i] / (rank + 1))
        adjusted[i] = min(1.0, running)
    return adjusted


def is_weather_complete(row):
    return all(finite(value) for value in row["exposure"].values())


def weather_variable_names(bundle):
    names = set()
    for row in bundle["dataset"]["rows"]:
        names.update(row["weather"])
    return sorted(names)


def partition_chunks(dates, block_days):
    """Non-overlapping chunks of at most block_days dates anchored at the first date."""
    return [dates[start:start + block_days] for start in range(0, len(dates), block_days)]


def draw_plan(n_dates, block_days):
    """Exact replicate span: full-length windows plus one remainder-length window."""
    full, remainder = divmod(n_dates, block_days)
    return full, remainder


def inference_label(gate_pass, adjusted):
    if not gate_pass:
        return "descriptive_only"
    return "inferential" if adjusted else "exploratory"


def load_bundle(path):
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("Oversize Phase 5 bundle")
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle["bundle_sha256"] != digest({k: v for k, v in bundle.items() if k != "bundle_sha256"}):
        raise ValueError("Phase 5 bundle integrity mismatch")
    if bundle["bundle_sha256"] != FROZEN_BUNDLE_SHA256:
        raise ValueError("Phase 5 bundle hash differs from the Phase 6 frozen boundary")
    manifest = bundle["manifest"]
    if manifest["eda_version"] != "phase5_eda_v1" or manifest["policy"] != EDA_POLICY:
        raise ValueError("Unreviewed Phase 5 selection policy in bundle")
    for key, frozen in FROZEN_WINDOW.items():
        if timestamp(manifest[key]) != timestamp(frozen):
            raise ValueError(f"Phase 5 bundle {key} differs from the Phase 6 frozen boundary")
    return bundle


def verify_phase4_file(bundle, path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != bundle["manifest"]["phase4_artifact_sha256"]:
        raise ValueError("Phase 4 artifact hash differs from the Phase 5 bundle record")


def bundle_file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_analysis(bundle):
    locations = {}
    for sensor_id, meta in bundle["dataset"]["sensors"].items():
        if SENSORS.get(meta["location_id"]) != meta["name"]:
            raise ValueError("Unexpected sensor/location mapping")
        locations[sensor_id] = meta["location_id"]
    if set(locations.values()) != set(SENSORS):
        raise ValueError("Unexpected sensor set in bundle")
    analysis, accepted_ends = [], {}
    for row in bundle["dataset"]["rows"]:
        value = row["pm25"]
        usable = finite(value)
        if usable and value < 0:
            raise ValueError("Negative accepted PM2.5 in frozen bundle")
        analysis.append({"location": locations[row["sensor_id"]], "local_date": row["local_date"],
            "hour": row["local_hour"], "weekday": row["weekday"], "end": row["period_end"],
            "pm25": value if usable else None, "log1p": math.log1p(value) if usable else None,
            "exposure": {code: w["value"] for code, w in row["weather"].items()},
            "quality": row["quality"]})
        if usable:
            accepted_ends.setdefault(locations[row["sensor_id"]], set()).add(row["period_end"])
    dates = sorted({r["local_date"] for r in analysis})
    if dates[0] != EXPECTED_DATE_START or dates[-1] != EXPECTED_DATE_END or len(dates) != EXPECTED_DATE_COUNT:
        raise ValueError("Frozen local calendar date range changed")
    shared = set.intersection(*accepted_ends.values())
    accepted = [r for r in analysis if r["pm25"] is not None]
    reconciliation = {"accepted_rows": len(accepted), "absent_rows": len(bundle["dataset"]["rows"]) - len(accepted),
        "accepted_cmt8": sum(r["location"] == "cmt8" for r in accepted),
        "accepted_oceanpark": sum(r["location"] == "oceanpark" for r in accepted),
        "complete_weather_cmt8": sum(r["location"] == "cmt8" and is_weather_complete(r) for r in accepted),
        "complete_weather_oceanpark": sum(r["location"] == "oceanpark" and is_weather_complete(r) for r in accepted),
        "shared_accepted_hours": len(shared)}
    if reconciliation != FROZEN_COUNTS:
        raise ValueError("Frozen Phase 5 counts changed; create a new frozen evidence version")
    return {"rows": analysis, "dates": dates, "shared": shared, "reconciliation": reconciliation,
            "accepted": accepted}


def extreme_review(accepted):
    fences, flagged = {}, set()
    for location in SENSORS:
        values = [r["pm25"] for r in accepted if r["location"] == location]
        if not values:
            continue
        q1, q3 = percentile(values, 0.25), percentile(values, 0.75)
        fence = q3 + 3 * (q3 - q1)
        hits = [r for r in accepted if r["location"] == location and r["pm25"] > fence]
        fences[location] = {"q1": sig(q1), "q3": sig(q3), "fence": sig(fence), "flagged_hours": len(hits)}
        flagged.update((r["location"], r["end"]) for r in hits)
    return fences, flagged


def enumerate_fits():
    fits = []

    def add(hypothesis, exposure, scale, scope, block_days=1, exclude_extreme=False, role="primary",
            weather_case="pairwise_complete"):
        stem = f"{hypothesis}_{exposure}_" if hypothesis == "S" else f"{hypothesis}_"
        name = f"{stem}{scope}_{scale}_b{block_days}"
        if weather_case != "not_applicable":
            name += f"_{weather_case}"
        if exclude_extreme:
            name += "_excl_extreme"
        fits.append({"fit_id": name, "hypothesis": hypothesis, "role": role, "exposure": exposure,
                     "scale": scale, "scope": scope, "block_days": block_days,
                     "exclude_extreme": exclude_extreme, "weather_case": weather_case})

    for hypothesis, exposure in PRIMARY_EXPOSURES:
        for scope in ("pooled", "cmt8", "oceanpark"):
            add(hypothesis, exposure, "log1p", scope)
    add("H3", None, "log1p", "shared", weather_case="not_applicable")
    for exposure in SECONDARY_EXPOSURES:
        add("S", exposure, "log1p", "pooled", role="secondary")
    add("H1", "wind_speed_10m", "raw", "pooled", role="sensitivity")
    add("H2", "relative_humidity_2m", "raw", "pooled", role="sensitivity")
    add("H3", None, "raw", "shared", role="sensitivity", weather_case="not_applicable")
    for block_days in (2, 7):
        add("H1", "wind_speed_10m", "log1p", "pooled", block_days=block_days, role="sensitivity")
        add("H2", "relative_humidity_2m", "log1p", "pooled", block_days=block_days, role="sensitivity")
        add("H3", None, "log1p", "shared", block_days=block_days, role="sensitivity", weather_case="not_applicable")
    add("H1", "wind_speed_10m", "log1p", "pooled", exclude_extreme=True, role="sensitivity")
    add("H2", "relative_humidity_2m", "log1p", "pooled", exclude_extreme=True, role="sensitivity")
    add("H3", None, "log1p", "shared", exclude_extreme=True, role="sensitivity", weather_case="not_applicable")
    add("H1", "wind_speed_10m", "log1p", "pooled", role="sensitivity", weather_case="complete_weather")
    add("H2", "relative_humidity_2m", "log1p", "pooled", role="sensitivity", weather_case="complete_weather")
    for exposure in SECONDARY_EXPOSURES:
        add("S", exposure, "log1p", "pooled", role="sensitivity", weather_case="complete_weather")
    return fits


def fit_rows(analysis, spec, flagged):
    scope = spec["scope"]
    if scope in SENSORS:
        base = [r for r in analysis["rows"] if r["location"] == scope]
        expected = 2160
    elif scope == "shared":
        base = [r for r in analysis["rows"] if r["end"] in analysis["shared"]]
        expected = 2 * len(analysis["shared"])
    else:
        base = analysis["rows"]
        expected = 2 * 2160
    excluded = sum((r["location"], r["end"]) in flagged for r in base)
    if spec["exclude_extreme"]:
        base = [r for r in base if (r["location"], r["end"]) not in flagged]
    exposure = spec["exposure"]
    response = "log1p" if spec["scale"] == "log1p" else "pm25"

    def response_ok(row):
        return row[response] is not None

    def exposure_ok(row):
        return not exposure or finite(row["exposure"].get(exposure))

    if spec["weather_case"] == "complete_weather":
        eligible = [r for r in base if response_ok(r) and exposure_ok(r) and is_weather_complete(r)]
    else:
        eligible = [r for r in base if response_ok(r) and exposure_ok(r)]
    accepted_hours = sum(r["pm25"] is not None for r in base)
    coverage = {"expected_hours": expected, "accepted_hours": accepted_hours,
                "absent_hours": sum(r["quality"] == "absent" for r in base),
                "extreme_flagged_hours": excluded,
                "weather_complete_hours": sum(r["pm25"] is not None and is_weather_complete(r) for r in base),
                "eligible_hours": len(eligible),
                "coverage_percent": sig(100 * accepted_hours / expected)}
    return base, eligible, coverage


def build_design(eligible, spec, date_index):
    response = "log1p" if spec["scale"] == "log1p" else "pm25"
    exposure = spec["exposure"]
    if exposure:
        exposure_mean, exposure_sd = mean_stdev([r["exposure"][exposure] for r in eligible])
        if exposure_sd <= 0:
            raise ValueError(f"Constant exposure in {spec['fit_id']}")
    else:
        exposure_mean = exposure_sd = None
    day_values = [date_index[r["local_date"]] for r in eligible]
    day_center = sum(day_values) / len(day_values)
    hours = sorted({r["hour"] for r in eligible})
    weekdays = sorted({r["weekday"] for r in eligible})
    pooled = spec["scope"] in ("pooled", "shared")
    columns = ["intercept"] + (["sensor_oceanpark"] if pooled else []) \
        + [f"local_hour_{h}" for h in hours[1:]] + [f"weekday_{wd}" for wd in weekdays[1:]] \
        + ["day_index_centered"] + ([f"z_{exposure}"] if exposure else [])
    p = len(columns)
    if len(eligible) <= p:
        raise RankDeficient(f"Rank deficiency: {spec['fit_id']} has {len(eligible)} eligible rows <= {p} columns")
    design_rows = []
    for row, day_value in zip(eligible, day_values):
        x = [1.0]
        if pooled:
            x.append(0.0 if row["location"] == REFERENCE_SENSOR else 1.0)
        x.extend(1.0 if row["hour"] == h else 0.0 for h in hours[1:])
        x.extend(1.0 if row["weekday"] == wd else 0.0 for wd in weekdays[1:])
        x.append(day_value - day_center)
        if exposure:
            x.append((row["exposure"][exposure] - exposure_mean) / exposure_sd)
        design_rows.append((row[response], tuple(x)))
    return design_rows, columns, p, {"exposure_mean": sig(exposure_mean), "exposure_sd": sig(exposure_sd),
                                     "day_center": sig(day_center)}


def pair_indices(p):
    return [(i, j, i * p - i * (i + 1) // 2 + j) for i in range(p) for j in range(i, p)]


def prefix_grams(grams, dates, p):
    size = p * (p + 1) // 2
    acc = ([0.0] * size, [0.0] * p, 0)
    prefix = [acc]
    for day in dates:
        g, g_y, count = grams[day]
        prefix.append(([a + b for a, b in zip(acc[0], g)], [a + b for a, b in zip(acc[1], g_y)], acc[2] + count))
        acc = prefix[-1]
    return prefix


def packed_index(i, j, p):
    if j < i:
        i, j = j, i
    return i * p - i * (i + 1) // 2 + j


def solve_normal(gram, g_y, p):
    diagonal = [gram[packed_index(i, i, p)] for i in range(p)]
    if min(diagonal) <= 0:
        raise RankDeficient("Rank-deficient normal equations")
    scale = [1.0 / math.sqrt(value) for value in diagonal]
    matrix = [[gram[packed_index(i, j, p)] * scale[i] * scale[j] for j in range(p)] + [g_y[i] * scale[i]]
              for i in range(p)]
    for col in range(p):
        pivot_row = max(range(col, p), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot_row][col]) <= PIVOT_TOL:
            raise RankDeficient("Rank-deficient normal equations")
        if pivot_row != col:
            matrix[col], matrix[pivot_row] = matrix[pivot_row], matrix[col]
        pivot = matrix[col][col]
        for r in range(col + 1, p):
            factor = matrix[r][col] / pivot
            if factor:
                target, source = matrix[r], matrix[col]
                for k in range(col, p + 1):
                    target[k] -= factor * source[k]
    coefficients = [0.0] * p
    for i in range(p - 1, -1, -1):
        residual = matrix[i][p] - sum(matrix[i][j] * coefficients[j] for j in range(i + 1, p))
        coefficients[i] = residual / matrix[i][i]
    return [coefficients[i] * scale[i] for i in range(p)]


def fit_model(rng, spec, analysis, date_index, flagged):
    base, eligible, coverage = fit_rows(analysis, spec, flagged)
    design_rows, columns, p, standardization = build_design(eligible, spec, date_index)
    dates = analysis["dates"]
    n_dates = len(dates)
    size = p * (p + 1) // 2
    grams = {day: ([0.0] * size, [0.0] * p, 0) for day in dates}
    accepted_days, pairs = set(), pair_indices(p)
    for (y, x), row in zip(design_rows, eligible):
        g, g_y, count = grams[row["local_date"]]
        for i, j, k in pairs:
            g[k] += x[i] * x[j]
        for i in range(p):
            g_y[i] += x[i] * y
        grams[row["local_date"]] = (g, g_y, count + 1)
    for row in base:
        if row["pm25"] is not None:
            accepted_days.add(row["local_date"])
    prefix = prefix_grams(grams, dates, p)
    try:
        point = solve_normal(prefix[-1][0], prefix[-1][1], p)
    except RankDeficient as error:
        raise ValueError(f"Rank deficiency in full-sample fit {spec['fit_id']}") from error
    estimand = f"z_{spec['exposure']}" if spec["exposure"] else "sensor_oceanpark"
    estimand_index = columns.index(estimand)
    estimate = point[estimand_index]
    full_draws, remainder_days = draw_plan(n_dates, spec["block_days"])
    draw_lengths = [spec["block_days"]] * full_draws + ([remainder_days] if remainder_days else [])
    if sum(draw_lengths) != n_dates:
        raise ValueError(f"Bootstrap draw plan for {spec['fit_id']} does not span exactly {n_dates} dates")
    estimates, skipped = [], 0
    for _ in range(REPLICATES):
        gram, g_y, rows = [0.0] * size, [0.0] * p, 0
        for length in draw_lengths:
            start = rng.randrange(n_dates - length + 1)
            high, low = prefix[start + length], prefix[start]
            gram = [a + b - c for a, b, c in zip(gram, high[0], low[0])]
            g_y = [a + b - c for a, b, c in zip(g_y, high[1], low[1])]
            rows += high[2] - low[2]
        if rows <= p:
            skipped += 1
            continue
        try:
            estimates.append(solve_normal(gram, g_y, p)[estimand_index])
        except RankDeficient:
            skipped += 1
    if skipped > MAX_SKIP_FRACTION * REPLICATES:
        raise ValueError(f"Too many singular bootstrap replicates in {spec['fit_id']}")
    if not estimates:
        raise ValueError(f"No usable bootstrap replicates in {spec['fit_id']}")

    chunks = partition_chunks(dates, spec["block_days"])
    nonempty_independent = sum(any(day in accepted_days for day in chunk) for chunk in chunks)
    eligible_independent = sum(any(grams[day][2] > 0 for day in chunk) for chunk in chunks)
    candidate_windows = n_dates - spec["block_days"] + 1
    gate_pass = nonempty_independent >= GATE_MIN_NONEMPTY and eligible_independent >= GATE_MIN_ELIGIBLE
    result = {"fit_id": spec["fit_id"], "hypothesis": spec["hypothesis"], "role": spec["role"],
        "scope": spec["scope"], "exposure": spec["exposure"], "scale": spec["scale"],
        "weather_case": spec["weather_case"], "block_days": spec["block_days"],
        "exclude_extreme": spec["exclude_extreme"],
        "formula": _formula(spec), "estimand": estimand, "columns": p, "n": len(eligible),
        "coverage": coverage,
        "candidate_windows": candidate_windows,
        "nonempty_independent_blocks": nonempty_independent,
        "eligible_independent_blocks": eligible_independent,
        "nonempty_blocks": nonempty_independent,
        "eligible_blocks": eligible_independent,
        "full_draws": full_draws, "remainder_draws": 1 if remainder_days else 0,
        "sampled_dates_per_replicate": n_dates,
        "draws_per_replicate": len(draw_lengths),
        "replicates": REPLICATES, "skipped_replicates": skipped,
        "usable_replicates": len(estimates), "estimate": sig(estimate), "gate_pass": gate_pass,
        "inference": inference_label(gate_pass, False),
        "standardization": standardization}
    if gate_pass:
        tail = sum(1 for v in estimates if v >= 0) if estimate < 0 else sum(1 for v in estimates if v <= 0)
        result.update({"ci_low": sig(percentile(estimates, 0.025)), "ci_high": sig(percentile(estimates, 0.975)),
                       "p_value": sig(min(1.0, 2 * (tail + 1) / (len(estimates) + 1))) if estimate != 0 else 1.0,
                       "bootstrap_mean": sig(sum(estimates) / len(estimates)),
                       "bootstrap_sd": sig(mean_stdev(estimates)[1])})
    return result


def _formula(spec):
    response = "log1p_pm25" if spec["scale"] == "log1p" else "pm25"
    terms = ["intercept"]
    if spec["scope"] in ("pooled", "shared"):
        terms.append("sensor_oceanpark")
    terms.extend(["C(local_hour)", "C(weekday)", "day_index_centered"])
    if spec["exposure"]:
        terms.append(f"z_{spec['exposure']}")
    return response + " ~ " + " + ".join(terms)


def pairwise_correlations(analysis, weather_variables):
    """Descriptive per-sensor correlations; never inferential output."""
    output = []
    for location in sorted(SENSORS):
        rows = [r for r in analysis["accepted"] if r["location"] == location]
        complete = [r for r in rows if is_weather_complete(r)]
        for code in weather_variables:
            if code in DESCRIPTIVE_ONLY_EXPOSURES:
                continue
            for case, case_rows in (("pairwise_complete", rows), ("complete_weather", complete)):
                result = descriptive_correlation([r["pm25"] for r in case_rows],
                                                 [r["exposure"].get(code) for r in case_rows])
                output.append({"location": location, "exposure": code, "response": "pm25",
                               "weather_case": case, "n": result["n"], "pearson_r": sig(result["pearson_r"])})
    return output


def compute_statistics(bundle, bundle_sha256):
    analysis = build_analysis(bundle)
    weather_variables = weather_variable_names(bundle)
    fences, flagged = extreme_review(analysis["accepted"])
    date_index = {day: index for index, day in enumerate(analysis["dates"])}
    rng = random.Random(SEED)
    results = [fit_model(rng, spec, analysis, date_index, flagged) for spec in enumerate_fits()]
    by_id = {fit["fit_id"]: fit for fit in results}
    adjustments = {}
    adjusted_ids = set()
    primary_ids = ("H1_pooled_log1p_b1_pairwise_complete", "H2_pooled_log1p_b1_pairwise_complete")
    primary_ps = [by_id[fit_id].get("p_value") for fit_id in primary_ids]
    if all(value is not None for value in primary_ps):
        for fit_id, adjusted in zip(primary_ids, holm(primary_ps)):
            by_id[fit_id]["p_value_adjusted"] = sig(adjusted)
            by_id[fit_id]["adjustment"] = "Holm over the two primary hypotheses"
            adjusted_ids.add(fit_id)
        adjustments["primary"] = {"method": "Holm", "fit_ids": list(primary_ids),
            "input_p_values": primary_ps, "adjusted_p_values": [by_id[i]["p_value_adjusted"] for i in primary_ids]}
    secondary_ids = tuple(f"S_{exposure}_pooled_log1p_b1_pairwise_complete" for exposure in SECONDARY_EXPOSURES)
    secondary_ps = [by_id[fit_id].get("p_value") for fit_id in secondary_ids]
    if all(value is not None for value in secondary_ps):
        for fit_id, adjusted in zip(secondary_ids, benjamini_hochberg(secondary_ps)):
            by_id[fit_id]["p_value_adjusted"] = sig(adjusted)
            by_id[fit_id]["adjustment"] = "Benjamini-Hochberg over the five declared secondary exposures"
            adjusted_ids.add(fit_id)
        adjustments["secondary"] = {"method": "Benjamini-Hochberg", "fit_ids": list(secondary_ids),
            "input_p_values": secondary_ps, "adjusted_p_values": [by_id[i]["p_value_adjusted"] for i in secondary_ids]}
    for fit in results:
        if fit["fit_id"] in adjusted_ids:
            fit["inference"] = inference_label(True, True)
    root = Path(__file__).parent
    manifest = {"stats_version": STATS_VERSION, "cutoff": bundle["manifest"]["cutoff"],
        "start": bundle["manifest"]["start"], "end": bundle["manifest"]["end"],
        "phase5_bundle_sha256": bundle["bundle_sha256"], "phase5_bundle_file_sha256": bundle_sha256,
        "phase5_manifest_sha256": digest(bundle["manifest"]),
        "phase4_artifact_sha256": bundle["manifest"]["phase4_artifact_sha256"],
        "phase4_manifest_sha256": bundle["manifest"]["phase4_manifest_sha256"],
        "phase5_input_sha256": bundle["manifest"]["input_sha256"], "policy": STATS_POLICY,
        "seed": SEED, "replicates": REPLICATES, "block_days": list(BLOCK_DAYS),
        "weather_variables": weather_variables,
        "gate_thresholds": {"min_nonempty_blocks": GATE_MIN_NONEMPTY, "min_eligible_blocks": GATE_MIN_ELIGIBLE},
        "gate_method": ("Non-overlapping partitions of the ordered Vietnam local calendar dates anchored at the "
                        "first frozen study date: consecutive chunks of at most block_days dates with a final "
                        "shorter chunk. Moving windows are resampling candidates only and are recorded as "
                        "candidate_windows; they are never the gate."),
        "bootstrap_draw_policy": STATS_POLICY["draw_policy"],
        "implementation_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                  for name in ("statistics.py", "statistics_output.py")},
        "formulas": {fit["fit_id"]: fit["formula"] for fit in results},
        "standardization": {fit["fit_id"]: fit["standardization"] for fit in results},
        "bootstrap_draws": {fit["fit_id"]: {"full_draws": fit["full_draws"],
            "remainder_draws": fit["remainder_draws"], "draws_per_replicate": fit["draws_per_replicate"],
            "sampled_dates_per_replicate": fit["sampled_dates_per_replicate"]} for fit in results},
        "independent_block_counts": {fit["fit_id"]: {"nonempty_independent_blocks": fit["nonempty_independent_blocks"],
            "eligible_independent_blocks": fit["eligible_independent_blocks"],
            "candidate_windows": fit["candidate_windows"]} for fit in results},
        "extreme_review": fences, "adjustments": adjustments,
        "pairwise_correlations": pairwise_correlations(analysis, weather_variables),
        "reconciliation": analysis["reconciliation"]}
    return {"purpose": "Phase 6 pre-registered sensor-level weather-PM2.5 association statistics; no causal, city-wide, forecast or health claims",
            "manifest": manifest, "manifest_sha256": digest(manifest), "results": results,
            "limitations": LIMITATIONS}


def run_statistics(bundle, bundle_sha256):
    return compute_statistics(bundle, bundle_sha256)
