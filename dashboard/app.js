/* Vietnam Air Observatory — local, read-only presentation of frozen evidence.
 * Source text enters the DOM through textContent or the escapeHTML boundary.
 * No fitting, imputation, remote assets, or historical-availability inference.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
  const h = escapeHTML;
  const number = (value, digits = 1) => finite(value)
    ? value.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
  const integer = (value) => number(value, 0);
  const percent = (value) => finite(value) ? `${number(value)}%` : "—";
  const text = (id, value) => { if ($(id)) $(id).textContent = value; };
  const unique = (values) => [...new Set(values.filter((v) => v !== null && v !== undefined && v !== ""))];
  const human = (value) => String(value ?? "Not recorded").replace(/_/g, " ");
  const sum = (rows, key) => rows.reduce((total, row) => total + (finite(row[key]) ? row[key] : 0), 0);
  const DAY = 86400000;
  const HOUR = 3600000;
  const TZ = "Asia/Ho_Chi_Minh";
  const NAV = {
    overview: "Overview", "air-quality": "Air quality", "weather-context": "Weather context",
    "model-diagnostics": "Model diagnostics", "methods-provenance": "Methods & provenance",
  };
  // CAMS uses city-context keys, never measured station identities. These color
  // indices remain stable when a city is selected alone or rows change order.
  const CAMS_LOCATIONS = Object.freeze({
    hcmc: { label: "Ho Chi Minh City", colorIndex: 0 },
    hanoi: { label: "Hanoi", colorIndex: 1 },
    da_nang: { label: "Da Nang", colorIndex: 2 },
  });
  const icons = {
    alert: '<path d="M12 4 21 20H3z"/><path d="M12 9v5M12 17.5h.01"/>',
    chart: '<path d="M4 4v16h16M7 14l4-5 4 3 5-7"/>',
    table: '<rect x="4" y="5" width="16" height="14" rx="1"/><path d="M4 10h16M9 5v14"/>',
    download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
    station: '<path d="M18 10c0 4.5-6 10-6 10S6 14.5 6 10a6 6 0 1 1 12 0Z"/><circle cx="12" cy="10" r="2"/>',
    clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
    check: '<path d="m5 12 4 4L19 6"/><path d="M20 12v7H4V4h10"/>',
    layers: '<path d="m3 8 9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
    weather: '<circle cx="8" cy="8" r="3"/><path d="M8 2v1M2 8h1M3.5 3.5l1 1M6 19h11a3 3 0 0 0 .4-6 4.5 4.5 0 0 0-8.7-1A3.5 3.5 0 0 0 6 19Z"/>',
    document: '<path d="M6 3h9l3 3v15H6zM14 3v4h4M9 11h6M9 15h6"/>',
    moon: '<path d="M20.5 15.3A7.8 7.8 0 0 1 8.7 3.5 8.2 8.2 0 1 0 20.5 15.3Z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
  };
  const icon = (name) => `<span class="inline-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icons[name] || icons.document}</svg></span>`;
  const badge = (value, tone = "") => `<span class="badge${tone ? ` badge-${tone}` : ""}">${h(value)}</span>`;
  const notice = (title, body) => `<div class="notice">${icon("alert")}<div class="notice-body"><strong>${h(title)}</strong> ${body}</div></div>`;
  const empty = (title = "No evidence in this scope", message = "Choose another station or date range. Missing values are not filled.") =>
    `<div class="empty-state">${icon("chart")}<strong>${h(title)}</strong><p>${h(message)}</p></div>`;
  const heading = (title, subtitle, actions = "") => `<div class="card-head"><div><h3>${h(title)}</h3><p class="card-subtitle">${h(subtitle)}</p></div>${actions ? `<div class="card-actions">${actions}</div>` : ""}</div>`;
  const facts = (rows) => `<dl class="fact-list">${rows.map(([label, value]) => `<div class="fact-row"><dt>${h(label)}</dt><dd>${h(value)}</dd></div>`).join("")}</dl>`;

  let data = null;
  let loading = false;
  const state = {
    view: "overview", sensor: "all", start: "", end: "", weather: "", camsLocation: "all",
    model: { sensor: "all", horizon: "all", split: "test", feature: "all", scope: "all", family: "all", transform: "all" },
    stats: { role: "primary", scope: "all", block: "1", scale: "log1p", weather: "pairwise_complete", extreme: "all" },
  };

  function localDateLabel(isoDate, year = false) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(isoDate || "")) return "—";
    return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}), timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));
  }
  function timeLabel(value, includeTime = true) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "—";
    return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", ...(includeTime ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}), timeZone: TZ }).format(date);
  }
  function bounds() {
    const dates = unique([...data.daily, ...data.hourly].map((row) => row.local_date)).sort();
    return { start: dates[0] || data.meta.window.local_start.slice(0, 10), end: dates.at(-1) || data.meta.window.local_end.slice(0, 10) };
  }
  function frozenLabel() {
    const b = bounds();
    return `${localDateLabel(b.start)} – ${localDateLabel(b.end, true)}`;
  }
  function scopeLabel() { return `${localDateLabel(state.start)} – ${localDateLabel(state.end, true)} · Vietnam local dates`; }
  function sensorName(id) {
    return data.sensors.find((sensor) => sensor.id === id || sensor.location_id === id)?.name || (id === "pooled" ? "Pooled sensors" : human(id));
  }
  function selectedSensors() { return data.sensors.filter((sensor) => state.sensor === "all" || sensor.id === state.sensor); }
  function sensorColor(sensor) { return sensor.location_id === "oceanpark" ? 1 : 0; }
  function scoped(rows) { return rows.filter((row) => (state.sensor === "all" || row.sensor_id === state.sensor) && row.local_date >= state.start && row.local_date <= state.end); }
  function stationScoped(rows) { return rows.filter((row) => state.sensor === "all" || row.sensor_id === state.sensor); }
  function camsLocationMeta(id) {
    return Object.hasOwn(CAMS_LOCATIONS, id) ? CAMS_LOCATIONS[id] : { label: "Unrecognized modeled location", colorIndex: 2 };
  }
  function camsScoped(rows) {
    return rows.filter((row) => row.local_date >= state.start && row.local_date <= state.end && (state.camsLocation === "all" || row.location_id === state.camsLocation));
  }
  function accepted(row) { return row.quality === "accepted" && finite(row.pm25); }
  function qualified(row) { return row.full_local_day === true && row.expected_hours === 24 && row.accepted_hours >= 18 && finite(row.qualified_mean) ? row.qualified_mean : null; }
  function datePoints(start = state.start, end = state.end) {
    const points = [];
    for (let stamp = Date.parse(`${start}T00:00:00Z`); stamp <= Date.parse(`${end}T00:00:00Z`); stamp += DAY) points.push(stamp);
    return points;
  }
  function weatherMeta(code) {
    return data.weather_variables.find((variable) => variable.code === code) || { code, label: human(code), unit: "unit not recorded", temporal_support: "not recorded", source: "ERA5_reanalysis" };
  }
  function weatherSupport(variable) {
    if (variable.temporal_support === "preceding_hour_mean") return "Preceding-hour mean, aligned to measured interval end";
    if (variable.temporal_support === "preceding_hour_sum") return "Preceding-hour sum, aligned to measured interval end";
    if (["instantaneous", "instant"].includes(variable.temporal_support)) return "Instantaneous value, aligned to measured interval start";
    return `${human(variable.temporal_support)} · see frozen registry`;
  }

  // Quote every CSV cell and neutralize formula-like strings. Numeric negatives
  // remain numeric; null stays blank, rather than becoming a fabricated zero.
  function csvCell(value) {
    if (value === null || value === undefined || (typeof value === "number" && !finite(value))) return '""';
    let cell = typeof value === "object" ? JSON.stringify(value) : String(value);
    if (typeof value !== "number" && /^[\s\u0000-\u001f]*[=+\-@]/.test(cell)) cell = `'${cell}`;
    return `"${cell.replace(/"/g, '""')}"`;
  }
  function downloadCSV(id, rows, columns) {
    const csv = [columns.map((column) => csvCell(column.label)).join(","), ...rows.map((row) => columns.map((column) => csvCell(column.value(row))).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `vietnam-air-${id}.csv`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const column = (label, value, options = {}) => ({ label, value, ...options });
  const numericColumn = (label, value, digits = 2) => column(label, value, { numeric: true, format: (v) => number(v, digits) });
  function makeTable(host, id, rows, columns, caption, pageSize = 20) {
    let page = 0;
    function draw() {
      const pages = Math.max(1, Math.ceil(rows.length / pageSize));
      page = Math.min(page, pages - 1);
      const pageRows = rows.slice(page * pageSize, (page + 1) * pageSize);
      host.innerHTML = `<div class="data-table-wrapper" tabindex="0" role="region" aria-label="${h(caption)}"><table class="data-table" id="${id}-table"><caption>${h(caption)}</caption><thead><tr>${columns.map((c) => `<th scope="col"${c.numeric ? ' class="number"' : ""}>${h(c.label)}</th>`).join("")}</tr></thead><tbody>${pageRows.map((row) => `<tr>${columns.map((c) => `<td${c.numeric ? ' class="number"' : ""}>${c.html ? c.html(row) : h(c.format ? c.format(c.value(row)) : c.value(row) ?? "—")}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${columns.length}">No records match these filters. No values have been substituted.</td></tr>`}</tbody></table></div><div class="pager"><span id="${id}-page-status" aria-live="polite">${rows.length ? `${integer(page * pageSize + 1)}–${integer(Math.min((page + 1) * pageSize, rows.length))} of ${integer(rows.length)} records` : "0 records"} · page ${page + 1}/${pages}</span><div class="pager-buttons"><button id="${id}-prev" type="button" class="button"${page === 0 ? " disabled" : ""}>Previous</button><button id="${id}-next" type="button" class="button"${page === pages - 1 ? " disabled" : ""}>Next</button></div></div>`;
      $(`${id}-prev`).addEventListener("click", () => { page -= 1; draw(); $(`${id}-${page === 0 ? "next" : "prev"}`).focus(); });
      $(`${id}-next`).addEventListener("click", () => { page += 1; draw(); $(`${id}-${page === pages - 1 ? "prev" : "next"}`).focus(); });
    }
    draw();
  }
  function exportButton(id) { return `<button type="button" class="button" id="${id}-export">${icon("download")}CSV</button>`; }
  function tablePanel(hostId, id, title, subtitle, rows, columns, options = {}) {
    const host = $(hostId);
    host.innerHTML = heading(title, subtitle, exportButton(id)) + (options.before || "") + `<div id="${id}-table-host"></div>` + (options.after || "");
    makeTable($(`${id}-table-host`), id, rows, columns, options.caption || subtitle, options.pageSize || 12);
    $(`${id}-export`).addEventListener("click", () => downloadCSV(id, rows, columns));
  }

  function lineChart(host, id, series, options) {
    const points = series.flatMap((item) => item.points).filter((point) => finite(point.x));
    const values = points.filter((point) => finite(point.y)).map((point) => point.y);
    if (!values.length) { host.innerHTML = empty(options.emptyTitle || "No qualified values to plot", options.empty || "The selected scope has no qualifying values. Gaps and partial boundary days remain in the data table."); return; }
    const width = options.compact ? 620 : 840;
    const height = options.compact ? 285 : 320;
    const pad = { left: 46, right: 19, top: 21, bottom: 44 };
    let xmin = options.xmin ?? Math.min(...points.map((point) => point.x));
    let xmax = options.xmax ?? Math.max(...points.map((point) => point.x));
    if (xmin === xmax) { xmin -= (options.gap || 1) / 2; xmax += (options.gap || 1) / 2; }
    const rawMin = options.zero ? 0 : Math.min(...values);
    const rawMax = Math.max(...values);
    const spread = Math.max(rawMax - rawMin, Math.abs(rawMax) * .1, 1);
    const magnitude = 10 ** Math.floor(Math.log10(spread / 4));
    const factor = (spread / 4) / magnitude;
    const step = (factor <= 1 ? 1 : factor <= 2 ? 2 : factor <= 5 ? 5 : 10) * magnitude;
    const ymin = options.zero ? 0 : Math.floor(rawMin / step) * step;
    const ymax = Math.max(ymin + step, Math.ceil(rawMax / step) * step);
    const x = (value) => pad.left + ((value - xmin) / (xmax - xmin)) * (width - pad.left - pad.right);
    const y = (value) => height - pad.bottom - ((value - ymin) / (ymax - ymin)) * (height - pad.top - pad.bottom);
    let grid = "";
    for (let value = ymin; value <= ymax + step * .01; value += step) {
      grid += `<line class="grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${y(value)}" y2="${y(value)}"/><text x="${pad.left - 10}" y="${y(value) + 3}" text-anchor="end">${h(number(value, step < 1 ? 1 : 0))}</text>`;
    }
    const ticks = options.ticks || Array.from({ length: 5 }, (_, i) => xmin + (xmax - xmin) * i / 4);
    grid += ticks.map((value, index) => `<text x="${x(value)}" y="${height - 20}" text-anchor="${index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle"}">${h(options.tick(value))}</text>`).join("");
    const paths = series.map((item, index) => {
      const color = item.colorIndex ?? index % 3;
      let path = "";
      let last = null;
      let dots = "";
      for (const point of item.points) {
        if (!finite(point.y)) { last = null; continue; }
        const connect = last !== null && (!options.gap || point.x - last <= options.gap * 1.01);
        path += `${connect ? "L" : "M"}${x(point.x).toFixed(2)},${y(point.y).toFixed(2)} `;
        if (item.points.length < 110 || options.pointsOnly) dots += `<circle class="point-${color}" cx="${x(point.x)}" cy="${y(point.y)}" r="${options.pointsOnly ? 1.7 : 2}"/>`;
        last = point.x;
      }
      return `${options.pointsOnly ? "" : `<path class="series series-${color}" d="${path.trim()}"/>`}${dots}`;
    }).join("");
    host.innerHTML = `<svg class="data-chart chart-interactive" id="${id}-svg" viewBox="0 0 ${width} ${height}" role="img" tabindex="0" aria-label="${h(options.title)}. ${h(options.unit)}. Use left and right arrow keys to inspect values; a data table is available below." aria-describedby="${id}-note"><title>${h(options.title)}</title><desc>Null values are gaps, not zeros. Separate paths preserve missing intervals. ${h(options.description || "")}</desc><text x="${pad.left}" y="11">${h(options.unit)}</text>${grid}${paths}<line id="${id}-cursor" class="grid-line" x1="0" x2="0" y1="${pad.top}" y2="${height - pad.bottom}" visibility="hidden"/></svg><div class="chart-tooltip" id="${id}-tooltip" aria-live="polite">Hover or use arrow keys to inspect · ${h(options.xLabel)}</div>`;
    const inspectKeys = unique(points.map((point) => point.x)).sort((a, b) => a - b);
    const lookup = series.map((item) => new Map(item.points.map((point) => [point.x, point.y])));
    let inspected = 0;
    const svg = $(`${id}-svg`);
    const showPoint = () => {
      const key = inspectKeys[inspected];
      text(`${id}-tooltip`, `${options.detail(key)} · ${series.map((item, i) => `${item.label}: ${number(lookup[i].get(key))} ${options.unit}`).join(" · ")}`);
      const cursor = $(`${id}-cursor`);
      cursor.setAttribute("x1", x(key)); cursor.setAttribute("x2", x(key)); cursor.setAttribute("visibility", "visible");
    };
    svg.addEventListener("pointermove", (event) => {
      const rectangle = svg.getBoundingClientRect();
      const pointX = (event.clientX - rectangle.left) / rectangle.width * width;
      const value = xmin + (pointX - pad.left) / (width - pad.left - pad.right) * (xmax - xmin);
      let best = Infinity;
      inspectKeys.forEach((key, i) => { if (Math.abs(key - value) < best) { best = Math.abs(key - value); inspected = i; } });
      showPoint();
    });
    svg.addEventListener("focus", showPoint);
    svg.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Home") inspected = 0;
      else if (event.key === "End") inspected = inspectKeys.length - 1;
      else inspected = Math.max(0, Math.min(inspectKeys.length - 1, inspected + (event.key === "ArrowRight" ? 1 : -1)));
      showPoint();
    });
  }
  function chartPanel(hostId, id, title, subtitle, series, rows, columns, options) {
    const host = $(hostId);
    host.innerHTML = heading(title, subtitle, `<button class="button" type="button" id="${id}-show-chart" aria-pressed="true">${icon("chart")}Chart</button><button class="button" type="button" id="${id}-show-table" aria-pressed="false">${icon("table")}Table</button>${exportButton(id)}`)
      + (options.controls || "")
      + `<div id="${id}-chart"><div class="chart-legend">${series.map((item, index) => `<span class="legend-entry"><span class="legend-line ${["", "teal", "amber"][item.colorIndex ?? index % 3]}" aria-hidden="true"></span>${h(item.label)}</span>`).join("")}</div><div class="chart-frame" id="${id}-frame"></div></div><p class="chart-note" id="${id}-note">${h(options.note)}</p><details class="data-disclosure" id="${id}-data"><summary id="${id}-data-toggle">Inspect ${h(title.toLowerCase())} data table (${integer(rows.length)} rows)</summary><div id="${id}-table-host"></div></details>`;
    lineChart($(`${id}-frame`), id, series, { ...options, title });
    makeTable($(`${id}-table-host`), id, rows, columns, options.caption || subtitle, options.pageSize || 20);
    const mode = (isTable) => {
      $(`${id}-chart`).hidden = isTable;
      $(`${id}-data`).open = isTable;
      $(`${id}-show-chart`).setAttribute("aria-pressed", String(!isTable));
      $(`${id}-show-table`).setAttribute("aria-pressed", String(isTable));
    };
    $(`${id}-show-chart`).addEventListener("click", () => mode(false));
    $(`${id}-show-table`).addEventListener("click", () => mode(true));
    $(`${id}-data`).addEventListener("toggle", () => {
      if (!$(`${id}-data`).open && $(`${id}-chart`).hidden) mode(false);
    });
    $(`${id}-export`).addEventListener("click", () => downloadCSV(id, rows, columns));
  }

  const dailyColumns = () => [column("Station", (r) => sensorName(r.sensor_id)), column("Vietnam local date", (r) => r.local_date), numericColumn("Qualified mean (µg/m³)", qualified), numericColumn("Accepted hours", (r) => r.accepted_hours, 0), numericColumn("Expected hours", (r) => r.expected_hours, 0), column("Full local day", (r) => r.full_local_day ? "Yes" : "No · boundary day"), numericColumn("Coverage (%)", (r) => r.coverage_percent, 1), column("Qualification", (r) => finite(qualified(r)) ? "Qualified" : !r.full_local_day ? "Partial boundary day · not plotted" : "Insufficient accepted hours · gap")];
  const dailyChartOptions = (note) => ({
    unit: "µg/m³", zero: true, gap: DAY, tick: (stamp) => localDateLabel(new Date(stamp).toISOString().slice(0, 10)),
    detail: (stamp) => localDateLabel(new Date(stamp).toISOString().slice(0, 10), true), xLabel: "Vietnam local day", note,
    xmin: Date.parse(`${state.start}T00:00:00Z`), xmax: Date.parse(`${state.end}T00:00:00Z`),
  });
  function dailySeries(rows) {
    return selectedSensors().map((sensor) => {
      const lookup = new Map(rows.filter((row) => row.sensor_id === sensor.id).map((row) => [row.local_date, qualified(row)]));
      return { label: sensor.name, colorIndex: sensorColor(sensor), points: datePoints().map((stamp) => ({ x: stamp, y: lookup.get(new Date(stamp).toISOString().slice(0, 10)) ?? null })) };
    });
  }
  function stationCard(rows) {
    const selected = selectedSensors();
    $("station-coverage-card").innerHTML = heading("Station evidence", "Accepted hours in the selected scope", badge("OpenAQ", "blue")) + selected.map((sensor, i) => {
      const daily = rows.filter((row) => row.sensor_id === sensor.id);
      const count = sum(daily, "accepted_hours");
      const expected = sum(daily, "expected_hours");
      const coverage = expected ? 100 * count / expected : null;
      return `<div class="station ${i === 1 || sensor.location_id === "oceanpark" ? "teal" : ""}"><div class="station-title"><div><div class="station-name"><span class="station-marker" aria-hidden="true"></span><h4>${h(sensor.name)}</h4></div><p class="station-region">${h(sensor.region)}</p></div>${badge("Sensor-level")}</div><div class="station-reading"><strong>${finite(coverage) ? number(coverage) : "—"}<span>${finite(coverage) ? "%" : ""}</span></strong><span>accepted coverage</span></div><div class="metric-line" aria-hidden="true"><span style="width:${finite(coverage) ? Math.max(0, Math.min(100, coverage)) : 0}%"></span></div><div class="station-foot"><span>${integer(count)} / ${integer(expected)} hours</span><span>${integer(expected - count)} absent / excluded</span></div></div>`;
    }).join("") + '<p class="station-bottom">These are two monitored sites, not city averages. Da Nang has modeled context only.</p>';
  }
  function sourceRows() {
    return `<div class="source-row"><span class="source-icon">${icon("station")}</span><div><h4>OpenAQ · measured PM2.5</h4><p>Accepted sensor observations. Gaps and excluded periods are retained; no modeled substitution.</p></div></div><div class="source-row"><span class="source-icon teal">${icon("weather")}</span><div><h4>ERA5 · retrospective weather</h4><p>Context at station coordinates. Retrieval time does not establish historical availability.</p></div></div><div class="source-row"><span class="source-icon amber">${icon("layers")}</span><div><h4>CAMS · modeled air quality</h4><p>A separate modeled context series, never a measured target or ground truth.</p></div></div>`;
  }
  function renderOverview() {
    const rows = scoped(data.daily);
    const acceptedHours = sum(rows, "accepted_hours");
    const expected = sum(rows, "expected_hours");
    const qualifiedDays = rows.filter((row) => finite(qualified(row))).length;
    const completeDays = rows.filter((row) => row.full_local_day).length;
    const cards = [
      ["Monitored stations", selectedSensors().length, "", "Sensor-level evidence, not city averages", "station", 100, ""],
      ["Accepted sensor-hours", acceptedHours, "", `${integer(expected)} expected hours in selected scope`, "check", expected ? acceptedHours / expected * 100 : 0, ""],
      ["Qualified station-days", qualifiedDays, "", `${integer(completeDays)} full station-days · ≥18 accepted hours`, "clock", completeDays ? qualifiedDays / completeDays * 100 : 0, "teal"],
      ["Absent / excluded hours", expected - acceptedHours, "", "Preserved as missing; never interpolated", "layers", expected ? (expected - acceptedHours) / expected * 100 : 0, ""],
    ];
    $("overview-metrics").innerHTML = cards.map(([label, value, unit, foot, glyph, width, tone]) => `<article class="metric ${tone}"><div class="metric-top"><span>${h(label)}</span>${icon(glyph)}</div><div class="metric-value">${integer(value)}${unit ? `<span class="metric-unit">${h(unit)}</span>` : ""}</div><p class="metric-foot">${h(foot)}</p><div class="metric-line" aria-hidden="true"><span style="width:${Math.max(0, Math.min(100, width))}%"></span></div></article>`).join("");
    $("overview-limitations").innerHTML = notice("Frozen research snapshot.", 'Descriptive observations and limited diagnostics only. No live monitoring, health guidance, causal inference, or forecast-skill claim. <a href="#methods-provenance">Read the evidence boundary →</a>');
    chartPanel("overview-trend-card", "daily-trend", "Daily concentration", `OpenAQ · ${scopeLabel()}`, dailySeries(rows), rows, dailyColumns(), dailyChartOptions(`${data.meta.daily_policy} The partial local days at the UTC window boundaries are not plotted as full days. Lines break at nulls.`));
    stationCard(rows);
    $("overview-source-card").innerHTML = heading("Three sources, distinct roles", "Source separation is part of the analysis contract") + sourceRows();
    $("overview-scope-card").innerHTML = heading("Know the scope", "A bounded view of the evidence") + facts([
      ["Selected local dates", `${state.start} → ${state.end}`], ["Timezone", "Asia/Ho_Chi_Minh · UTC+07:00"], ["Target unit", "PM2.5 · µg/m³"], ["Daily qualification", "Full local day · ≥18 accepted hours"], ["Statistical / model outputs", "Fixed-window; unaffected by these dates"],
    ]) + '<p class="footer-note">The next evidence step is a prospective collection period. Historical backfill cannot establish as-issued availability.</p><a class="button button-secondary" href="#model-diagnostics">Inspect model diagnostics →</a>';
  }

  function renderAir() {
    const diurnal = stationScoped(data.diurnal);
    const series = selectedSensors().map((sensor) => ({ label: sensor.name, colorIndex: sensorColor(sensor), points: Array.from({ length: 24 }, (_, hour) => ({ x: hour, y: diurnal.find((row) => row.sensor_id === sensor.id && row.local_hour === hour)?.mean ?? null })) }));
    chartPanel("air-diurnal-card", "diurnal", "Within-day profile", `Fixed full-window Phase 5 summary · ${frozenLabel()}`, series, diurnal,
      [column("Station", (r) => sensorName(r.sensor_id)), numericColumn("Vietnam local hour", (r) => r.local_hour, 0), numericColumn("Mean PM2.5 (µg/m³)", (r) => r.mean), numericColumn("Accepted observations", (r) => r.n, 0)],
      { unit: "µg/m³", zero: true, gap: 1, compact: true, ticks: [0, 6, 12, 18, 23], tick: (hour) => `${String(hour).padStart(2, "0")}:00`, detail: (hour) => `${String(hour).padStart(2, "0")}:00 Vietnam time`, xLabel: "Vietnam local hour · UTC+07:00", note: "Precomputed diurnal means use the full frozen window. Date filters do not recalculate this chart; the station filter does apply. These are descriptive means, not inferential outputs." });
    renderStatistics();
    const hourly = scoped(data.hourly).sort((a, b) => a.period_start.localeCompare(b.period_start) || a.sensor_id.localeCompare(b.sensor_id));
    const hourlySeries = selectedSensors().map((sensor) => ({ label: sensor.name, colorIndex: sensorColor(sensor), points: hourly.filter((row) => row.sensor_id === sensor.id).map((row) => ({ x: Date.parse(row.period_start), y: accepted(row) ? row.pm25 : null })) }));
    chartPanel("air-hourly-card", "hourly-pm", "Hourly measured PM2.5", `OpenAQ · ${scopeLabel()}`, hourlySeries, hourly,
      [column("Station", (r) => sensorName(r.sensor_id)), column("Vietnam local date", (r) => r.local_date), numericColumn("Local start hour", (r) => r.local_hour, 0), column("Interval start (UTC)", (r) => r.period_start), column("Exclusive end (UTC)", (r) => r.period_end), numericColumn("Accepted PM2.5 (µg/m³)", (r) => accepted(r) ? r.pm25 : null), column("Quality", (r) => r.quality)],
      { unit: "µg/m³", zero: true, gap: HOUR, tick: (stamp) => timeLabel(stamp, false).replace(/ 2026$/, ""), detail: (stamp) => `${timeLabel(stamp)} ICT · interval start`, xLabel: "Interval start · Vietnam local time", note: "Every selected hourly row is retained, with no smoothing or downsampling. Only accepted PM2.5 is plotted. Nulls and missing one-hour intervals break the line. OpenAQ intervals are [start, end), exclusive at the end.", pageSize: 24 });
    tablePanel("air-coverage-card", "daily-coverage", "Daily qualification ledger", `Selected date scope · ${scopeLabel()} · qualified means only`, scoped(data.daily), dailyColumns(), { pageSize: 12 });
  }

  function optionHTML(values, selected, label = human) {
    return values.map((value) => `<option value="${h(value)}"${String(value) === String(selected) ? " selected" : ""}>${h(label(value))}</option>`).join("");
  }
  function renderStatistics() {
    const results = data.statistics.results;
    const fields = [
      ["role", "Role", ["all", ...unique(results.map((row) => row.role))]],
      ["scope", "Fit scope", ["all", ...unique(results.map((row) => row.scope))]],
      ["block", "Block days", ["all", ...unique(results.map((row) => row.block_days))]],
      ["scale", "Scale", ["all", ...unique(results.map((row) => row.scale))]],
      ["weather", "Weather cases", ["all", ...unique(results.map((row) => row.weather_case))]],
      ["extreme", "Extreme review", ["all", "included", "excluded"]],
    ];
    const selected = results.filter((row) =>
      (state.stats.role === "all" || row.role === state.stats.role) &&
      (state.stats.scope === "all" || row.scope === state.stats.scope) &&
      (state.stats.block === "all" || String(row.block_days) === state.stats.block) &&
      (state.stats.scale === "all" || row.scale === state.stats.scale) &&
      (state.stats.weather === "all" || row.weather_case === state.stats.weather) &&
      (state.stats.extreme === "all" || row.exclude_extreme === (state.stats.extreme === "excluded")));
    $("air-stats-card").innerHTML = heading("Pre-registered associations", "Fixed Phase 6 corrected results · independent of all descriptive date/station filters", exportButton("statistics"))
      + `<div class="inline-controls">${fields.map(([key, label, values]) => `<label class="control-label">${h(label)}<select id="stats-${key}-filter">${optionHTML(values, state.stats[key])}</select></label>`).join("")}</div><p class="card-subtitle">Weather coefficients are per one analysis-window SD, not per physical unit. Only recorded Holm/BH-adjusted p-values are shown. Intervals and sensitivity estimates are reproduced, never re-fit.</p><div id="statistics-table-host" class="data-disclosure"></div>`;
    const columns = [
      column("Fit", (r) => r.fit_id, { html: (r) => `<span class="cell-main">${h(r.hypothesis)} · ${h(human(r.exposure || r.estimand))}</span><span class="cell-detail">${h(r.scope)} · ${h(r.scale)} · ${h(r.block_days)}-day blocks</span>` }),
      numericColumn("Estimate", (r) => r.estimate, 3),
      column("Recorded interval", (r) => finite(r.ci_low) && finite(r.ci_high) ? `${number(r.ci_low, 3)} to ${number(r.ci_high, 3)}` : null),
      column("Adjusted p", (r) => r.p_value_adjusted, { numeric: true, format: (v) => finite(v) ? (v < .0001 ? v.toExponential(2) : number(v, 4)) : "—" }),
      column("Inference", (r) => r.inference === "inferential" && !finite(r.p_value_adjusted) ? "No adjusted inference recorded" : r.inference, { html: (r) => `${badge(r.inference === "inferential" && !finite(r.p_value_adjusted) ? "No adjusted inference recorded" : human(r.inference), r.inference === "inferential" && finite(r.p_value_adjusted) ? "blue" : "")}<span class="cell-detail">${h(r.adjustment || "No adjusted inferential p recorded")}</span>` }),
      numericColumn("n", (r) => r.n, 0), numericColumn("Eligible independent blocks", (r) => r.eligible_independent_blocks, 0),
      numericColumn("Nonempty independent blocks", (r) => r.nonempty_independent_blocks, 0),
      column("Weather / review", (r) => `${r.weather_case}; exclude_extreme=${r.exclude_extreme}`, { html: (r) => `${h(human(r.weather_case))}<span class="cell-detail">Extreme rule ${r.exclude_extreme ? "applied" : "not applied"}</span>` }),
      column("Formula / fit identity", (r) => `${r.fit_id}: ${r.formula}`, { html: (r) => `<details><summary>Fit details</summary><p class="cell-detail">${h(r.fit_id)}</p><p class="cell-detail">${h(r.formula)}</p><p class="cell-detail">Estimand: ${h(r.estimand)}. Standardization: ${h(JSON.stringify(r.standardization))}. Coverage: ${h(JSON.stringify(r.coverage))}.</p></details>` }),
    ];
    makeTable($("statistics-table-host"), "statistics", selected, columns, `Fixed ${frozenLabel()} · recorded Phase 6 uncertainty · adjusted p only`, 6);
    fields.forEach(([key]) => $(`stats-${key}-filter`).addEventListener("change", (event) => { state.stats[key] = event.target.value; renderStatistics(); $(`stats-${key}-filter`).focus(); }));
    $("statistics-export").addEventListener("click", () => downloadCSV("statistics-fixed-window", selected, columns));
  }

  function renderWeather() {
    const variable = weatherMeta(state.weather);
    const hourly = scoped(data.hourly).sort((a, b) => a.period_start.localeCompare(b.period_start) || a.sensor_id.localeCompare(b.sensor_id));
    const series = selectedSensors().map((sensor) => ({ label: sensor.name, colorIndex: sensorColor(sensor), points: hourly.filter((row) => row.sensor_id === sensor.id).map((row) => ({ x: Date.parse(row.period_start), y: finite(row.weather[state.weather]) ? row.weather[state.weather] : null })) }));
    chartPanel("weather-hourly-card", "weather-hourly", variable.label, `ERA5 reanalysis · ${scopeLabel()}`, series, hourly,
      [column("Station", (r) => sensorName(r.sensor_id)), column("Vietnam local date", (r) => r.local_date), numericColumn("Local interval-start hour", (r) => r.local_hour, 0), column("Interval start (UTC)", (r) => r.period_start), column("Interval end (UTC)", (r) => r.period_end), numericColumn(`${variable.label} (${variable.unit})`, (r) => r.weather[state.weather]), column("Weather quality", (r) => r.weather_quality?.[state.weather] ?? "not recorded"), column("Temporal support", () => variable.temporal_support), column("Source", () => variable.source)],
      { compact: true, unit: variable.unit, gap: HOUR, pointsOnly: state.weather === "wind_direction_10m", tick: (stamp) => timeLabel(stamp, false).replace(/ 2026$/, ""), detail: (stamp) => `${timeLabel(stamp)} ICT · measured interval start`, xLabel: "Vietnam local interval time", note: `${weatherSupport(variable)}. The x-axis is the measured interval start; source support is retained in the table. Retrospective context only, not captured operational features.${state.weather === "wind_direction_10m" ? " Wind direction is circular: points are not connected across angles." : ""}`, pageSize: 24 });
    const associations = stationScoped(data.weather_associations).filter((row) => row.variable !== "wind_direction_10m" && (!state.weather || row.variable === state.weather));
    tablePanel("weather-associations-card", "pearson", "Descriptive weather association", `Fixed full-window Phase 5 summary · ${frozenLabel()}`, associations,
      [column("Station", (r) => sensorName(r.sensor_id)), column("Exposure", (r) => weatherMeta(r.variable).label), numericColumn("Pearson r", (r) => r.pearson_r, 3), numericColumn("Paired n", (r) => r.n, 0)],
      { before: '<p class="long-text">Pairwise-complete correlation with accepted PM2.5. This table is exploratory and is not a significance test or causal estimate. Date filters do not recalculate it.</p>', after: '<p class="footer-note">The station and variable selectors apply to this fixed summary. Wind direction is circular and has no linear Pearson estimate. Adjusted Phase 6 results are separately available in <a href="#air-quality">Air quality</a>.</p>' });
    renderCams();
  }

  function renderCams() {
    const locations = unique(data.cams_daily.map((row) => row.location_id)).sort((a, b) => camsLocationMeta(a).colorIndex - camsLocationMeta(b).colorIndex || a.localeCompare(b));
    const cams = camsScoped(data.cams_daily);
    const camsSeries = locations.filter((location) => state.camsLocation === "all" || location === state.camsLocation).map((location) => {
      const lookup = new Map(cams.filter((row) => row.location_id === location).map((row) => [row.local_date, row.mean]));
      const metadata = camsLocationMeta(location);
      return { label: `${metadata.label} · CAMS modeled`, colorIndex: metadata.colorIndex, points: datePoints().map((stamp) => ({ x: stamp, y: lookup.get(new Date(stamp).toISOString().slice(0, 10)) ?? null })) };
    });
    const controls = `<div class="inline-controls"><label class="control-label" for="cams-location-filter">CAMS modeled location<select id="cams-location-filter" aria-describedby="cams-location-help">${optionHTML(["all", ...locations], state.camsLocation, (location) => location === "all" ? "All modeled locations" : camsLocationMeta(location).label)}</select></label></div><p class="card-subtitle" id="cams-location-help">Modeled city context, independent of the measured station selector. The selected Vietnam local dates still apply.</p>`;
    chartPanel("cams-card", "cams-daily", "CAMS available-value daily means", `Modeled PM2.5 context, not qualified OpenAQ daily means · ${scopeLabel()}`, camsSeries, cams,
      [column("Modeled city context", (r) => camsLocationMeta(r.location_id).label), column("Location key", (r) => r.location_id), column("Vietnam local date", (r) => r.local_date), numericColumn("Available-value mean (µg/m³)", (r) => r.mean), numericColumn("Available values (n)", (r) => r.n, 0), column("Source role", () => "CAMS modeled city context · not measured station data")],
      { ...dailyChartOptions("CAMS values are modeled city context, never ground truth or replacements for measured PM2.5. Daily means use available modeled values only, including partial first/last local dates; they do not meet or imply OpenAQ full-day qualification. Inspect each date’s n in the table. Da Nang has no qualified measured target."), controls, emptyTitle: "No modeled values to plot", empty: "No modeled CAMS values are available for the selected city and dates. Measured station filters do not apply to this card." });
    $("cams-location-filter").addEventListener("change", (event) => {
      state.camsLocation = event.target.value;
      renderCams();
      $("cams-location-filter").focus({ preventScroll: true });
    });
  }

  const baselineFeatures = { persistence_last_available: "history_only", persistence_lag_1h: "history_only", trailing_mean_24h: "history_only", local_hour_climatology: "calendar_only", weather_augmented_climatology: "weather_only" };
  function modelRows() {
    return [...data.baselines.metrics.map((row) => ({ ...row, kind: "Baseline", name: row.baseline_id, display_feature: baselineFeatures[row.baseline_id] || "not_recorded", display_scope: row.sensor_id === "pooled" ? "pooled" : "per_sensor" })), ...data.ml.metrics.map((row) => ({ ...row, kind: "ML", name: row.model_family, display_feature: row.feature_set, display_scope: row.scope }))];
  }
  function modelMatches(row, baseline = false) {
    const m = state.model;
    return (m.sensor === "all" || row.sensor_id === m.sensor) && (m.horizon === "all" || String(row.horizon_hours) === m.horizon) &&
      (m.split === "all" || row.split === m.split) && (m.feature === "all" || (row.display_feature || row.feature_set) === m.feature) &&
      (m.scope === "all" || (row.display_scope || row.scope) === m.scope) &&
      (m.family === "all" || (baseline ? m.family === "baselines" : row.model_family === m.family)) &&
      (m.transform === "all" || (!baseline && row.target_transform === m.transform));
  }
  function evaluation(row) { return row.evaluation_type || (row.split === "validation" ? "tuning_diagnostic" : row.split === "train" ? "in_sample_fit" : "fixed_test_holdout"); }
  function renderModels() {
    $("model-limited-notice").innerHTML = notice("Limited diagnostic.", "Only calendar-only model instances trained. PM history and captured forecast-weather features are unavailable in this historical window. A prospective collection period is required. All metrics are descriptive_only; date filters in other views have no effect here.");
    const counts = data.ml.counts;
    $("model-summary-card").innerHTML = heading("Availability before accuracy", "Frozen Phase 7 → Phase 9 evidence boundary", badge("Limited diagnostic", "amber")) + `<div class="diagnostic-counts"><div><strong>${integer(counts.trained_instances)}</strong><span>trained instances<br />calendar-only</span></div><div><strong>${integer(counts.unavailable_instances)}</strong><span>unavailable instances<br />explicit reasons retained</span></div><div><strong>${integer(counts.available_metric_cells)}</strong><span>available metric cells<br />of ${integer(counts.metric_cells)}</span></div></div>` + facts([["Missing feature families", data.features.missing_families.map(human).join(", ") || "None recorded"], ["Prospective collection required", data.features.prospective_collection_period_required ? "Yes" : "Not recorded"], ["Feature / baseline / ML version", `${data.features.version} · ${data.baselines.version} · ${data.ml.version}`]]);
    const split = data.ml.split || data.features.split;
    const fractions = split.fractions || {};
    $("model-split-card").innerHTML = heading("Chronological evaluation", "One shared split; horizon purge is inherited") + `<div class="split-track" aria-hidden="true">${["train", "validation", "test"].map((name) => `<span style="flex:${finite(fractions[name]) ? fractions[name] : 0}"></span>`).join("")}</div><div class="split-items">${["train", "validation", "test"].map((name) => `<div><strong>${h(human(name))} · ${percent(finite(fractions[name]) ? fractions[name] * 100 : null)}</strong><span>${name === "train" ? "Fit transforms" : name === "validation" ? "Tuning diagnostic" : "Fixed holdout"}</span></div>`).join("")}</div>` + facts([["Validation starts (ICT)", timeLabel(split.validation_start)], ["Test starts (ICT)", timeLabel(split.test_start)], ["ML final fit", "Train + validation"], ["Phase 8 climatology fit", "Train only"]]) + '<p class="footer-note">Validation RMSE tunes Ridge alpha. No test-based model, feature-set, or transform selection. Test comparisons can have different training histories.</p>';
    renderModelTables();
  }
  function historyStatusCell(row) {
    const raw = row.history_status || "unknown";
    const labels = { training_history_mismatch: "Different training history", matched: "Matched training history", not_paired: "Not paired", not_applicable: "Not applicable", unknown: "Unknown training history" };
    const label = Object.hasOwn(labels, raw) ? labels[raw] : human(raw);
    return `<span class="badge history-status-badge${raw === "training_history_mismatch" ? " badge-amber" : ""}" title="${h(raw)}" data-history-status="${h(raw)}">${h(label)}</span><details class="cell-detail history-code-detail"><summary>Raw status code</summary><code>${h(raw).replace(/_/g, "_<wbr>")}</code></details>`;
  }
  function fitPartitionCell(raw) {
    const labels = { train: "Train", train_plus_validation: "Train + validation", validation: "Validation", test: "Test" };
    const label = raw == null ? "—" : Object.hasOwn(labels, raw) ? labels[raw] : human(raw);
    return `<span class="fit-partition" title="${h(raw ?? "Not recorded")}">${h(label)}</span>`;
  }
  function renderModelTables() {
    const rows = modelRows().filter((row) => modelMatches(row, row.kind === "Baseline"));
    const controls = `<div class="inline-controls"><label class="control-label">Family<select id="model-family-filter">${optionHTML(["all", "baselines", ...unique(data.ml.metrics.map((row) => row.model_family))], state.model.family)}</select></label><label class="control-label">Target transform<select id="model-transform-filter">${optionHTML(["all", ...unique(data.ml.metrics.map((row) => row.target_transform))], state.model.transform)}</select></label></div>`;
    const columns = [
      column("Method", (r) => `${r.kind}: ${r.name}`, { html: (r) => `<span class="cell-main">${h(human(r.name))}</span><span class="cell-detail">${h(r.kind)} · ${h(r.target_transform || "direct / raw concentration")} · ${h(human(r.display_scope))}</span>` }),
      column("Sensor / features", (r) => `${sensorName(r.sensor_id)}; ${r.display_feature}`, { html: (r) => `${h(sensorName(r.sensor_id))}<span class="cell-detail">${h(human(r.display_feature))}</span>` }),
      column("Horizon / split", (r) => `${r.horizon_hours}h; ${r.split}; ${evaluation(r)}`, { html: (r) => `${h(r.horizon_hours)}h · ${h(r.split)}<span class="cell-detail">${h(evaluation(r))}</span>` }),
      numericColumn("MAE · µg/m³", (r) => r.mae), numericColumn("RMSE · µg/m³", (r) => r.rmse), numericColumn("MASE", (r) => r.mase), numericColumn("sMAPE · %", (r) => r.smape), numericColumn("R² · ML only", (r) => r.r2, 3),
      column("Status / reason", (r) => `${r.metric_status}; ${r.metric_reason || r.model_reason || "descriptive_only"}`, { html: (r) => `${badge(human(r.metric_status), r.metric_status === "available" ? "blue" : "")}<span class="cell-detail cell-reason">${h(r.metric_reason || r.model_reason || "descriptive_only")}</span>` }),
    ];
    tablePanel("model-metrics-card", "model-metrics", "Baselines & model metrics", "Recorded frozen scores · no browser recomputation · each row is descriptive_only", rows, columns,
      { before: controls, pageSize: 12, after: '<p class="footer-note">“Pooled sensors” combines the two monitored sites descriptively, not a population. Feature and scope filters group the declared baselines by their evidence requirements and reporting sensor scope; they do not refit them. MASE uses a training one-hour-naive denominator; sMAPE is zero-safe. Unavailable values remain — with a recorded reason.</p>' });
    ["family", "transform"].forEach((key) => $(`model-${key}-filter`).addEventListener("change", (event) => { state.model[key] = event.target.value; renderModelTables(); $(`model-${key}-filter`).focus(); }));
    const comparisons = data.ml.comparisons.filter((row) => modelMatches(row));
    const mismatches = comparisons.filter((row) => row.history_status === "training_history_mismatch").length;
    tablePanel("model-comparisons-card", "model-comparisons", "Paired comparisons & fit history", "Deltas are model minus reference on shared finite keys · descriptive_only", comparisons,
      [column("Model / reference", (r) => `${r.model_family}; ${r.reference_baseline || r.comparison_kind}`, { html: (r) => `<span class="cell-main">${h(human(r.model_family))} · ${h(r.target_transform)}</span><span class="cell-detail">${h(human(r.reference_baseline || r.comparison_kind))}</span><span class="cell-detail">${h(human(r.feature_set))} · ${h(human(r.scope))}</span>` }),
        column("Sensor / slice", (r) => `${sensorName(r.sensor_id)}; ${r.horizon_hours}h; ${r.split}`, { html: (r) => `${h(sensorName(r.sensor_id))}<span class="cell-detail">${h(r.horizon_hours)}h · ${h(r.split)} · ${h(evaluation(r))}</span>` }),
        column("History status", (r) => r.history_status, { html: historyStatusCell }),
        column("Model fit partition", (r) => r.fit_partition, { html: (r) => fitPartitionCell(r.fit_partition) }), column("Reference fit partition", (r) => r.reference_fit_partition ?? r.counterpart_fit_partition, { html: (r) => fitPartitionCell(r.reference_fit_partition ?? r.counterpart_fit_partition) }),
        numericColumn("Model finite", (r) => r.model_finite_rows, 0), numericColumn("Reference finite", (r) => r.reference_finite_rows, 0), numericColumn("Paired rows", (r) => r.paired_rows, 0),
        numericColumn("Δ MAE · µg/m³", (r) => r.mae_delta), numericColumn("Δ RMSE · µg/m³", (r) => r.rmse_delta),
        column("Pair status / reason", (r) => `${r.comparison_status}; ${r.comparison_reason || ""}`, { html: (r) => `${h(r.comparison_status)}<span class="cell-detail">${h(r.comparison_reason || (r.comparison_status === "not_paired" ? "No shared finite prediction keys" : "descriptive_only"))}</span>` })],
      { before: notice("Fit histories must be read alongside deltas.", `${integer(mismatches)} selected records have a <strong>training-history mismatch</strong>. The final ML fit includes validation while the Phase 8 climatology fit is train-only. A numeric delta is not evidence of forecast skill.`), pageSize: 10 });
  }

  function provenanceArtifact(artifact, index) {
    const exceptions = artifact.integrity_exceptions;
    const exceptionHTML = exceptions.length ? `<section class="integrity-exceptions" id="provenance-phase-${h(artifact.phase)}-exceptions" aria-label="Recorded integrity exceptions"><h4>Recorded integrity exception</h4><p class="card-subtitle">These files are excluded from the verified-files list. The complete historical artifact is not fully verified.</p>${exceptions.map((exception, exceptionIndex) => `<div class="integrity-exception" id="provenance-phase-${h(artifact.phase)}-exception-${exceptionIndex}"><p class="cell-main">${h(exception.file)}</p><p class="long-text">${h(exception.reason)}</p><dl class="exception-hashes"><dt>Declared SHA-256</dt><dd class="hash" data-hash-kind="declared">${h(exception.declared_sha256)}</dd><dt>Observed SHA-256</dt><dd class="hash" data-hash-kind="observed">${h(exception.observed_sha256)}</dd></dl></div>`).join("")}</section>` : "";
    return `<details class="provenance-item" id="provenance-phase-${h(artifact.phase)}"><summary id="provenance-toggle-${index}"><span class="phase-number">${h(artifact.phase)}</span><span class="provenance-title">${h(artifact.label)}<span>${h(artifact.directory)}</span>${exceptions.length ? `<span class="provenance-exception-label">${integer(exceptions.length)} documented integrity exception${exceptions.length === 1 ? "" : "s"}</span>` : ""}</span></summary><div class="provenance-detail"><p class="card-subtitle">Manifest / bundle identity</p><p class="hash">${h(artifact.identity)}</p>${exceptionHTML}<p class="card-subtitle">Verified files (${integer(Object.keys(artifact.files_sha256).length)})</p><ul class="hash-list" id="provenance-phase-${h(artifact.phase)}-verified-files">${Object.entries(artifact.files_sha256).map(([name, digest]) => `<li>${h(name)}<span class="hash">${h(digest)}</span></li>`).join("")}</ul></div></details>`;
  }

  function renderMethods() {
    const w = data.meta.window;
    text("methods-schema", data.schema_version);
    $("methods-window-card").innerHTML = heading("Frozen observation boundary", "Time semantics are explicit") + facts([["Window start (UTC)", w.start_utc], ["Window end (UTC, exclusive)", w.end_utc], ["Eligibility cutoff (UTC)", w.cutoff_utc], ["Local timezone", `${w.timezone} · UTC+07:00`], ["Local display span", frozenLabel()], ["Measured time support", "[period_start, period_end), 1 hour"]]) + '<p class="footer-note">The UTC study window contains partial Vietnam-local boundary days. Their hours count toward coverage, but they are not shown as qualified daily concentration means.</p>';
    $("methods-policy-card").innerHTML = heading("Qualification & availability", "No silent substitutions") + `<div class="long-text"><p>${h(data.meta.daily_policy)}</p><p>${h(data.meta.source_policy)}</p><p>Latest eligible source revision is selected before quality filtering. Accepted observations alone enter measured summaries. Missing and excluded evidence stays visible.</p><p>Captured features require evidence timestamps strictly before the origin. Historical retrieval time is not historical availability; no captured-to-assumed fallback is used.</p></div>`;
    $("methods-source-card").innerHTML = heading("Source roles & attribution", "Measured, reanalysis, and modeled evidence remain separate") + sourceRows() + data.sensors.map((sensor) => `<div class="source-row"><div><h4>${h(sensor.name)} · ${h(sensor.region)}</h4><p>${h(sensor.attribution || "Attribution not recorded")}</p><p>Licence reference: ${h(sensor.licence_url || "Not recorded")}</p></div></div>`).join("");
    const limitations = unique([...data.meta.limitations, ...data.statistics.limitations]);
    $("methods-data-card").innerHTML = heading("Interpretation limits", "Read before drawing conclusions") + `<ul class="method-list"><li>Two sensor sites are not city averages or population exposure estimates.</li><li>Associations are bounded to one frozen 90-day UTC window, not causal effects.</li><li>Diurnal profiles and Pearson correlations are descriptive. Only recorded adjusted Phase 6 outputs can be inferential.</li><li>ERA5 is retrospective context. CAMS and provider forecasts are not ground truth.</li><li>The calendar-only diagnostic artifact establishes neither forecast skill nor operational readiness.</li><li>No live ingestion, schedules, database access, or production automation runs in this dashboard.</li></ul>${limitations.length ? `<details class="data-disclosure"><summary>Additional recorded limitations (${limitations.length})</summary><ul class="method-list">${limitations.map((item) => `<li>${h(item)}</li>`).join("")}</ul></details>` : ""}`;
    const integrityNotes = data.meta.integrity_notes;
    const integrityNoteHTML = integrityNotes.length ? `<div class="notice" id="provenance-integrity-notes" role="note">${icon("alert")}<div class="notice-body"><strong>Documented integrity warning</strong><ul class="method-list">${integrityNotes.map((note) => `<li>${h(note)}</li>`).join("")}</ul><p>All displayed data payloads are verified; this does not mean the complete historical Phase 5 artifact is fully verified.</p></div></div>` : "";
    $("provenance-card").innerHTML = heading("Artifact chain", "Verified displayed data payloads · source identities and documented exceptions") + `<p class="card-subtitle">Public bundle SHA-256</p><p class="hash" id="bundle-sha256">${h(data.bundle_sha256)}</p><div id="provenance-list">${data.provenance.map(provenanceArtifact).join("")}</div>${integrityNoteHTML}<p class="footer-note">Paths above are evidence references, not server links. This browser can fetch only its local public JSON and dashboard assets; it does not access the repository, credentials, database, or source APIs.</p>`;
  }

  function renderActive() {
    if (!data) return;
    const renderers = { overview: renderOverview, "air-quality": renderAir, "weather-context": renderWeather, "model-diagnostics": renderModels, "methods-provenance": renderMethods };
    renderers[state.view]();
  }
  function navigate(event) {
    const requested = location.hash.slice(1);
    state.view = Object.hasOwn(NAV, requested) ? requested : "overview";
    document.querySelectorAll("[data-view]").forEach((view) => {
      const active = view.dataset.view === state.view;
      view.hidden = !active;
      const title = view.querySelector("h1");
      if (!title.dataset.originalId) title.dataset.originalId = title.id;
      title.id = active ? "view-title" : title.dataset.originalId;
      view.setAttribute("aria-labelledby", title.id);
    });
    document.querySelectorAll("[data-view-link]").forEach((link) => {
      const active = link.dataset.viewLink === state.view;
      link.classList.toggle("is-active", active);
      if (active) { link.setAttribute("aria-current", "page"); link.id = "current-nav"; }
      else { link.removeAttribute("aria-current"); link.removeAttribute("id"); }
    });
    text("breadcrumb-view", NAV[state.view]);
    document.title = `${NAV[state.view]} · Vietnam Air Observatory`;
    renderActive();
    if (data && event?.type === "hashchange") {
      $("view-title").setAttribute("tabindex", "-1");
      $("view-title").focus({ preventScroll: true });
      window.scrollTo(0, 0);
    }
  }
  function populate(select, values, label, firstLabel = "All") {
    const old = select.value;
    select.innerHTML = `<option value="all">${h(firstLabel)}</option>` + values.map((value) => `<option value="${h(value)}">${h(label(value))}</option>`).join("");
    if ([...select.options].some((option) => option.value === old)) select.value = old;
  }
  function syncDescriptiveControls() {
    const b = bounds();
    ["global", "air", "weather"].forEach((prefix) => {
      $(`${prefix}-sensor-filter`).value = state.sensor;
      ["start", "end"].forEach((key) => {
        const input = $(`${prefix}-${key}-filter`);
        input.min = b.start; input.max = b.end; input.value = state[key]; input.removeAttribute("aria-invalid"); input.removeAttribute("aria-describedby");
      });
    });
    document.querySelectorAll(".filter-error").forEach((error) => error.remove());
  }
  function changeDescriptive(prefix) {
    const start = $(`${prefix}-start-filter`);
    const end = $(`${prefix}-end-filter`);
    const b = bounds();
    const valid = start.validity.valid && end.validity.valid && /^\d{4}-\d{2}-\d{2}$/.test(start.value) && /^\d{4}-\d{2}-\d{2}$/.test(end.value) && start.value <= end.value && start.value >= b.start && end.value <= b.end;
    if (!valid) {
      start.setAttribute("aria-invalid", "true"); end.setAttribute("aria-invalid", "true");
      const bar = start.closest(".filter-bar");
      let error = bar.querySelector(".filter-error");
      if (!error) { error = document.createElement("p"); error.id = `${prefix}-date-error`; error.className = "filter-error"; error.setAttribute("role", "alert"); bar.append(error); }
      start.setAttribute("aria-describedby", error.id); end.setAttribute("aria-describedby", error.id);
      error.textContent = `Choose ordered Vietnam local dates from ${b.start} through ${b.end}. The displayed scope has not changed.`;
      return;
    }
    state.start = start.value; state.end = end.value; state.sensor = $(`${prefix}-sensor-filter`).value;
    syncDescriptiveControls(); renderActive();
  }
  function resetDescriptive() {
    const b = bounds(); state.start = b.start; state.end = b.end; state.sensor = "all";
    syncDescriptiveControls(); renderActive();
  }
  function setupData() {
    const b = bounds(); state.start = b.start; state.end = b.end;
    const ids = data.sensors.map((sensor) => sensor.id);
    ["global", "air", "weather"].forEach((prefix) => populate($(`${prefix}-sensor-filter`), ids, sensorName, "All monitored stations"));
    syncDescriptiveControls();
    const variables = data.weather_variables.map((variable) => variable.code);
    state.weather = variables.includes("temperature_2m") ? "temperature_2m" : variables[0] || "";
    $("weather-variable-filter").innerHTML = variables.map((code) => `<option value="${h(code)}">${h(weatherMeta(code).label)} (${h(weatherMeta(code).unit)})</option>`).join("");
    $("weather-variable-filter").value = state.weather;
    const metrics = [...data.ml.metrics, ...data.baselines.metrics];
    const diagnosticValues = { sensor: unique(metrics.map((row) => row.sensor_id)), horizon: unique(metrics.map((row) => row.horizon_hours)).sort((a, b) => a - b), split: ["train", "validation", "test"].filter((split) => metrics.some((row) => row.split === split)), feature: unique(data.ml.metrics.map((row) => row.feature_set)), scope: unique(data.ml.metrics.map((row) => row.scope)) };
    Object.entries(diagnosticValues).forEach(([key, values]) => {
      populate($(`model-${key}-filter`), values, key === "sensor" ? sensorName : key === "horizon" ? (value) => `${value} hours` : human, `All ${key === "feature" ? "feature sets" : `${key}s`}`);
      if (!values.some((value) => String(value) === state.model[key])) state.model[key] = "all";
      $(`model-${key}-filter`).value = state.model[key];
    });
    text("sidebar-window", frozenLabel());
    text("overview-window", frozenLabel()); text("overview-timezone", "Vietnam local dates · UTC+07:00");
    ["air-quality-window", "weather-window", "model-window"].forEach((id) => text(id, frozenLabel()));
    $("dataset-status").innerHTML = '<span class="status-dot" aria-hidden="true"></span><span>Frozen snapshot · read-only</span>';
    $("dashboard-app").hidden = false;
    navigate();
  }
  function validateBundle(payload) {
    if (!payload || payload.schema_version !== "phase10_dashboard_v1") throw new Error("schema");
    for (const key of ["sensors", "hourly", "daily", "diurnal", "weather_associations", "weather_variables", "cams_daily", "provenance"]) if (!Array.isArray(payload[key])) throw new Error("shape");
    for (const key of ["meta", "statistics", "features", "baselines", "ml"]) if (!payload[key] || typeof payload[key] !== "object") throw new Error("shape");
    if (!payload.meta.window || payload.meta.window.timezone !== TZ || !Array.isArray(payload.meta.limitations) || !Array.isArray(payload.statistics.limitations) || !Array.isArray(payload.statistics.results) || !Array.isArray(payload.baselines.metrics) || !Array.isArray(payload.ml.metrics) || !Array.isArray(payload.ml.comparisons) || !Array.isArray(payload.features.missing_families)) throw new Error("shape");
    if (!Array.isArray(payload.meta.integrity_notes) || payload.meta.integrity_notes.some((note) => typeof note !== "string")) throw new Error("shape");
    let hasIntegrityException = false;
    for (const artifact of payload.provenance) {
      if (!artifact || !artifact.files_sha256 || typeof artifact.files_sha256 !== "object" || Array.isArray(artifact.files_sha256) || !Array.isArray(artifact.integrity_exceptions)) throw new Error("shape");
      for (const exception of artifact.integrity_exceptions) {
        if (!exception || ["file", "declared_sha256", "observed_sha256", "reason"].some((key) => typeof exception[key] !== "string" || !exception[key])) throw new Error("shape");
        if (!/^[a-f0-9]{64}$/.test(exception.declared_sha256) || !/^[a-f0-9]{64}$/.test(exception.observed_sha256) || Object.hasOwn(artifact.files_sha256, exception.file)) throw new Error("shape");
        hasIntegrityException = true;
      }
    }
    if (hasIntegrityException && payload.meta.integrity_notes.length === 0) throw new Error("shape");
    if (!/^[a-f0-9]{64}$/.test(payload.bundle_sha256 || "")) throw new Error("identity");
    return payload;
  }
  async function loadData() {
    if (loading) return;
    loading = true;
    $("app-loading").hidden = false; $("app-error").hidden = true; $("dashboard-app").hidden = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("./data/dashboard.json", { cache: "no-store", credentials: "omit", mode: "same-origin", redirect: "error", signal: controller.signal });
      if (!response.ok) throw new Error("unavailable");
      data = validateBundle(await response.json());
      setupData();
    } catch (error) {
      data = null;
      $("dashboard-app").hidden = true; $("app-error").hidden = false;
      text("app-error-message", error.message === "schema" || error.message === "shape" || error.message === "identity"
        ? "The local evidence bundle does not match the reviewed dashboard contract. No values were displayed. Rebuild the verified bundle, then try again."
        : "The local JSON bundle is missing, unreadable, or could not be rendered. Start the allowlisted loopback dashboard server and ensure dashboard/data/dashboard.json is present. No fallback or mock data is used.");
      text("dataset-status", "Local bundle unavailable");
    } finally { window.clearTimeout(timer); $("app-loading").hidden = true; loading = false; }
  }
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const button = $("theme-toggle");
    button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[theme === "dark" ? "sun" : "moon"]}</svg>`;
    button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
    button.setAttribute("aria-pressed", String(theme === "dark"));
    try { localStorage.setItem("vietnam-air-theme", theme); } catch { /* Storage can be unavailable in private environments. */ }
  }
  function skipToContent(event) {
    event.preventDefault();
    $("main-content").focus();
  }
  let initialTheme = "light";
  try { if (localStorage.getItem("vietnam-air-theme") === "dark") initialTheme = "dark"; } catch { /* Use readable light default. */ }
  applyTheme(initialTheme);
  $("theme-toggle").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  $("retry-load").addEventListener("click", loadData);
  $("skip-to-content").addEventListener("click", skipToContent);
  window.addEventListener("hashchange", navigate);
  ["global", "air", "weather"].forEach((prefix) => ["sensor", "start", "end"].forEach((key) => $(`${prefix}-${key}-filter`).addEventListener("change", () => changeDescriptive(prefix))));
  ["reset-descriptive-filters", "reset-air-filters", "reset-weather-filters"].forEach((id) => $(id).addEventListener("click", resetDescriptive));
  $("weather-variable-filter").addEventListener("change", (event) => { state.weather = event.target.value; renderWeather(); });
  ["sensor", "horizon", "split", "feature", "scope"].forEach((key) => $(`model-${key}-filter`).addEventListener("change", (event) => { state.model[key] = event.target.value; renderModelTables(); }));
  $("reset-model-filters").addEventListener("click", () => {
    Object.keys(state.model).forEach((key) => { state.model[key] = key === "split" ? "test" : "all"; const select = $(`model-${key}-filter`); if (select) select.value = state.model[key]; });
    renderModelTables();
  });
  navigate();
  loadData();
})();
