"""Portable CSV/JSON and static scientific SVG figures; no network resources."""

import csv
import hashlib
import html
import json
from datetime import date, datetime, timezone

from vn_air.quality import digest, finite

COLORS = ("#2563a6", "#bd5618", "#168276")


def chart_svg(title, x_label, y_label, series, *, note="", date_axis=False,
              scatter=False, y_domain=None, expected_step=None):
    """Plot numeric x coordinates on one shared scale; nulls break lines."""
    width, height, left, top, right, bottom = 960, 460, 82, 94, 34, 70
    all_x = [x for values in series.values() for x, _ in values]
    points = [(x, y) for values in series.values() for x, y in values if finite(y)]
    xmin, xmax = (min(all_x), max(all_x)) if all_x else (0, 1)
    if xmin == xmax:
        xmin, xmax = xmin - .5, xmax + .5
    ymin, ymax = y_domain or ((min(y for _, y in points), max(y for _, y in points)) if points else (0, 1))
    if ymin == ymax:
        ymin, ymax = ymin - .5, ymax + .5
    if y_domain is None:
        padding = (ymax - ymin) * .06
        ymin, ymax = ymin - padding, ymax + padding

    def sx(value):
        return left + (width - left - right) * (value - xmin) / (xmax - xmin)

    def sy(value):
        return top + (height - top - bottom) * (ymax - value) / (ymax - ymin)

    def label(x, y, value, size=14, anchor="start"):
        return f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" font-size="{size}">{html.escape(str(value))}</text>'

    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f'<title>{html.escape(title)}</title><desc>{html.escape(note)}</desc>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="Arial, sans-serif" fill="#243340">',
        label(left, 28, title, 20), label(left, 51, note, 13),
        f'<defs><clipPath id="plot"><rect x="{left}" y="{top}" width="{width-left-right}" height="{height-top-bottom}"/></clipPath></defs>']
    for i in range(6):
        value = ymin + (ymax - ymin) * i / 5
        y = sy(value)
        chunks.extend([f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#dae0e4"/>',
                       label(left - 12, y + 5, f"{value:.3g}", anchor="end")])
        value = xmin + (xmax - xmin) * i / 5
        x = sx(value)
        tick = date.fromordinal(round(value)).strftime("%d %b") if date_axis else f"{value:.3g}"
        chunks.extend([f'<line x1="{x:.2f}" y1="{height-bottom}" x2="{x:.2f}" y2="{height-bottom+6}" stroke="#80909c"/>',
                       label(x, height - bottom + 26, tick, anchor="middle")])
    chunks.extend([f'<rect x="{left}" y="{top}" width="{width-left-right}" height="{height-top-bottom}" fill="none" stroke="#80909c"/>',
        label((left + width - right) / 2, height - 16, x_label, anchor="middle"),
        f'<text transform="translate(20 {(top+height-bottom)/2}) rotate(-90)" text-anchor="middle" font-size="14">{html.escape(y_label)}</text>'])
    for index, (name, values) in enumerate(series.items()):
        color = COLORS[index % len(COLORS)]
        lx = left + index * 250
        chunks.extend([f'<line x1="{lx}" y1="74" x2="{lx+24}" y2="74" stroke="{color}" stroke-width="2"/>', label(lx + 32, 79, name)])
        if scatter:
            chunks.append('<g clip-path="url(#plot)">')
            chunks.extend(f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="1.8" fill="{color}" opacity=".22"/>' for x, y in values if finite(x) and finite(y))
            chunks.append('</g>')
        else:
            path, previous = [], None
            for x, y in values:
                if not finite(y):
                    previous = None
                    continue
                move = previous is None or (expected_step is not None and x - previous > expected_step * 1.01)
                path.append(f'{"M" if move else "L"}{sx(x):.2f},{sy(y):.2f}')
                previous = x
            chunks.append(f'<path clip-path="url(#plot)" d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="1.7"/>')
    if not points:
        chunks.append(label(width / 2, height / 2, "No eligible values", anchor="middle"))
    return "".join(chunks) + "</g></svg>\n"


def figures(dataset, summary):
    sensors = summary["sensors"]
    names = {sid: s["name"] for sid, s in sensors.items()}
    measured = {sid: [r for r in dataset["rows"] if r["sensor_id"] == sid] for sid in sensors}

    def days(value):
        moment = datetime.fromisoformat(value)
        return moment.date().toordinal() + (moment.hour * 3600 + moment.minute * 60) / 86400

    outputs = {}
    outputs["hourly_pm25.svg"] = chart_svg("Measured PM2.5: hourly intervals", "UTC interval start, 2026", "PM2.5 (ug/m3)",
        {names[sid]: [(days(r["period_start"]), r["pm25"]) for r in rows] for sid, rows in measured.items()},
        note="OpenAQ / AirGradient; accepted values only. Lines stop at absent hours.", date_axis=True, expected_step=1/24)
    outputs["daily_pm25.svg"] = chart_svg("Measured PM2.5: coverage-qualified days", "Vietnam local date, 2026", "Daily mean (ug/m3)",
        {s["name"]: [(date.fromisoformat(r["local_date"]).toordinal(), r["qualified_mean"]) for r in s["daily"]] for s in sensors.values()},
        note="Only full local dates with at least 18/24 accepted hours; no interpolation.", date_axis=True, expected_step=1)
    outputs["daily_coverage.svg"] = chart_svg("Coverage of measured sensor hours", "Vietnam local date, 2026", "Accepted / expected (%)",
        {s["name"]: [(date.fromisoformat(r["local_date"]).toordinal(), r["coverage_percent"]) for r in s["daily"]] for s in sensors.values()},
        note="Edge dates cover 17 and 7 expected hours; interior dates cover 24 hours.", date_axis=True, y_domain=(0, 100))
    outputs["diurnal_pm25.svg"] = chart_svg("Measured PM2.5: time-of-day profile", "Vietnam interval-start hour (UTC+7)", "Mean PM2.5 (ug/m3)",
        {s["name"]: [(r["local_hour"], r["mean"]) for r in s["diurnal"]] for s in sensors.values()},
        note="Observed-hour means; sample counts and quartiles in diurnal.csv. No confidence bands.")
    ecdf = {}
    for sid, rows in measured.items():
        values = sorted(r["pm25"] for r in rows if finite(r["pm25"]))
        ecdf[f'{names[sid]} (n={len(values)})'] = [(v, (i+1)/len(values)) for i, v in enumerate(values)]
    outputs["pm25_distribution.svg"] = chart_svg("Measured PM2.5: empirical distributions", "PM2.5 (ug/m3)", "Cumulative fraction", ecdf,
        note="Full available sensor records; descriptive distributions, not population estimates.", y_domain=(0, 1))
    outputs["lag_correlation.svg"] = chart_svg("PM2.5 correlation at elapsed-hour lags", "Lag (hours)", "Pairwise Pearson r",
        {s["name"]: [(r["lag_hours"], r["pearson_r"]) for r in s["lag_correlations"] if s["lag_correlations"]] for s in sensors.values()},
        note="Exact-time pairs; gaps are not shifted away. No significance or forecast-skill claim.", y_domain=(-1, 1), expected_step=1)
    outputs["cams_context.svg"] = chart_svg("CAMS Global PM2.5: modeled context", "Vietnam local date, 2026", "Modeled daily mean (ug/m3)",
        {lid: [(date.fromisoformat(r["local_date"]).toordinal(), r["qualified_mean"]) for r in s["daily"]] for lid, s in summary["cams_modeled_context"].items()},
        note="City-point grid output, selected retrospective captures; NOT sensor ground truth.", date_axis=True)
    for code, spec in dataset["weather_variables"].items():
        if code == "wind_direction_10m":
            continue
        series = {}
        for sid, rows in measured.items():
            pairs = [(r["weather"][code]["value"], r["pm25"]) for r in rows if finite(r["pm25"]) and finite(r["weather"][code]["value"])]
            series[f'{names[sid]} (n={len(pairs)})'] = pairs
        outputs[f"weather_{code}.svg"] = chart_svg(f"PM2.5 and ERA5: {code.replace('_', ' ')}", f"ERA5 {code} ({spec['unit']})", "Measured PM2.5 (ug/m3)", series,
            note="All pairwise-complete hours; retrospective association, unadjusted for confounding.", scatter=True)
    return outputs


def flatten_weather(row):
    output = {k: v for k, v in row.items() if k != "weather"}
    for code, record in row["weather"].items():
        output.update({f"{code}_{key}": value for key, value in record.items()})
    return output


def write_csv(path, rows):
    fields = sorted({k for r in rows for k in r})
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        # Formula-safe text in portable CSV; numbers and blank/nulls remain typed.
        writer.writerows({k: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for k, v in row.items()} for row in rows)


def write_outputs(output_dir, bundle):
    from vn_air.eda import summarize
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise ValueError("Output must be a new directory with existing parent")
    # Recompute from data on replay rather than copying a cached summary.
    computed = summarize(bundle["dataset"])
    if digest(computed) != digest(bundle["summary"]):
        raise ValueError("EDA summary does not match its dataset")
    summary = {"purpose": "Phase 5 descriptive EDA; no inferential, causal or model-performance claims",
        "manifest": bundle["manifest"], "manifest_sha256": digest(bundle["manifest"]),
        "bundle_sha256": bundle["bundle_sha256"], "summary": computed,
        "limitations": ["Two non-reference sensor sites, not city means; Da Nang modeled-only.",
            "Missing and rejected values are retained; analysis uses accepted values only.",
            "ERA5 and CAMS are retrospective model output, not operationally available features.",
            "Correlations are unadjusted and serially dependent; no p-values or causal interpretation.",
            "Full audited period explored. Reserve new data for a future untouched model holdout."]}
    plots = figures(bundle["dataset"], computed)
    output_dir.mkdir(mode=0o700)
    # SUCCESS manifest is written last. A partial directory is not a completed run.
    for name, content in (("eda_summary.json", summary), ("eda_bundle.json", bundle)):
        with (output_dir / name).open("x", encoding="utf-8") as handle:
            json.dump(content, handle, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            handle.write("\n")
    write_csv(output_dir / "hourly_pm25_weather_grid.csv", [flatten_weather(r) for r in bundle["dataset"]["rows"]])
    write_csv(output_dir / "cams_modeled_pm25.csv", bundle["dataset"]["cams_modeled_pm25"])
    write_csv(output_dir / "snapshot_provenance.csv", list(bundle["dataset"]["snapshot_provenance"].values()))
    for field in ("daily", "diurnal", "weekday", "lag_correlations", "weather_associations"):
        write_csv(output_dir / f"{field}.csv", [{"sensor_id": sid, **row} for sid, s in computed["sensors"].items() for row in s[field]])
    for name, svg in plots.items():
        with (output_dir / name).open("x", encoding="utf-8") as handle:
            handle.write(svg)
    attribution = "OpenAQ; AirGradient; Thomas Versteeg (CMT8); Open-Meteo; ERA5/Copernicus C3S; CAMS Global. CC BY 4.0."
    with (output_dir / "README.md").open("x", encoding="utf-8") as handle:
        handle.write("# Frozen Phase 5 EDA\n\n" + attribution + "\n\n")
        handle.write("Source data normalized, selected and aggregated; no imputation. See ../phase_5.md for findings and limits.\n\n")
        for name in plots:
            handle.write(f"![{name[:-4].replace('_', ' ')}]({name})\n\n")
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output_dir.iterdir())}
    with (output_dir / "SUCCESS.json").open("x", encoding="utf-8") as handle:
        json.dump({"bundle_sha256": bundle["bundle_sha256"], "files_sha256": files}, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return {"output_dir": str(output_dir), "bundle_sha256": bundle["bundle_sha256"], "file_count": len(files)+1}
