// 예보 변동성 웹 조회. 서버 /api/* 의 JSON을 받아 달력(주·월·연), 일간 모달, 그래프를 그린다.
// 화면 문구는 static/i18n/<언어>.json (t("키")). 외부 문자열(도시 이름 등)은 항상 textContent로 넣는다.
"use strict";

// ---------- 작은 도구 ----------

const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") Object.assign(node.style, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("aw." + key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("aw." + key, JSON.stringify(value)); } catch { /* 저장 못 해도 동작에는 지장 없음 */ }
  },
};

function debounce(fn, ms) {
  let timer = null;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

// ---------- 언어 (i18n) ----------
// 언어 목록은 static/i18n/languages.json, 문구는 static/i18n/<code>.json. 새 언어 파일에 빠진 키는 영어로 보인다.

const i18n = { lang: "en", dict: {}, base: {}, languages: [] };

function t(key, vars = {}) {
  const s = i18n.dict[key] ?? i18n.base[key] ?? key;
  if (typeof s !== "string") return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

function pickLanguage() {
  const codes = i18n.languages.map((l) => l.code);
  const saved = store.get("lang", null);
  if (codes.includes(saved)) return saved;
  for (const pref of navigator.languages || [navigator.language]) {
    const code = (pref || "").slice(0, 2).toLowerCase();
    if (codes.includes(code)) return code;
  }
  return codes.includes("en") ? "en" : codes[0];
}

async function loadLanguage(code) {
  if (!Object.keys(i18n.base).length) i18n.base = await fetchJSON("static/i18n/en.json");
  i18n.dict = code === "en" ? i18n.base : await fetchJSON(`static/i18n/${code}.json`);
  i18n.lang = code;
  document.documentElement.lang = code;
  document.title = t("app_title");
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-aria]")) el.setAttribute("aria-label", t(el.dataset.i18nAria));
}

// 날씨 이름: weather_code.json의 언어별 이름 (없으면 영어)
function wxName(code) {
  const names = state.meta.weather_names[String(code)];
  return names ? names[i18n.lang] ?? names.en ?? String(code) : "–";
}

// ---------- 서버 ----------

async function api(path, params = {}) {
  const res = await fetch(`api/${path}?${new URLSearchParams(params)}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ? t(`err.${body.error}`, { detail: body.detail ?? "" }) : `${res.status}`);
  return body;
}

function showError(err) {
  const box = $("#error");
  box.hidden = !err;
  box.textContent = err ? t("load_failed", { msg: err.message || err }) : "";
}

// ---------- 날짜 ('YYYY-MM-DD' 문자열, 시간대 없이 UTC로 계산) ----------

const HOUR = 3600000;
const DAY = 24 * HOUR;
const toDate = (s) => new Date(s + "T00:00:00Z");
const iso = (d) => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const d = toDate(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
const weekStart = (s) => addDays(s, -toDate(s).getUTCDay()); // 일요일 시작
const monthStart = (s) => s.slice(0, 8) + "01";
const monthEnd = (s) => { const d = toDate(monthStart(s)); d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(0); return iso(d); };
const addMonths = (s, n) => { const d = toDate(monthStart(s)); d.setUTCMonth(d.getUTCMonth() + n); return iso(d); };
const weekdays = () => t("weekdays");
const dow = (s) => weekdays()[toDate(s).getUTCDay()];
const md = (s) => `${+s.slice(5, 7)}/${+s.slice(8, 10)}`;
const daysBetween = (a, b) => Math.round((toDate(b) - toDate(a)) / DAY);
const monthName = (m) => t("months")[m - 1]; // m: 1~12
const periodMonth = (y, m) => t("period_month", { y, m, mon: monthName(m) });

function leadLabel(n) {
  if (n === 0) return t("lead_0");
  if (n === 1) return t("lead_1");
  if (n === 2) return t("lead_2");
  return t("lead_n", { n });
}

// ---------- 색 ----------
// 변동 정도(0~1)는 초록 → 노랑 → 빨강 (OKLab에서 보간). n일 전 선은 --lead-ramp 순서형 색.

function hexToRgb(hex) {
  const n = parseInt(hex.trim().slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const unlin = (c) => Math.round(255 * Math.min(1, Math.max(0, c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)));

function toOklab(hex) {
  const [r, g, b] = hexToRgb(hex).map(lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromOklab([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s].map(unlin);
  return "#" + rgb.map((c) => c.toString(16).padStart(2, "0")).join("");
}
function rampAt(stops, x) {
  x = Math.min(1, Math.max(0, x));
  const pos = x * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  const a = toOklab(stops[i]), b = toOklab(stops[i + 1]), f = pos - i;
  return fromOklab(a.map((v, k) => v + (b[k] - v) * f));
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const heatStops = () => [css("--heat-0"), css("--heat-1"), css("--heat-2")];
const heat = (x) => rampAt(heatStops(), x);
function withAlpha(hex, a) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}
function leadColor(n) {
  if (n === 0) return css("--d0"); // 당일(기준)은 n일 전 색들과 겹치지 않는 주황
  const ramp = css("--lead-ramp").split(",").map((s) => s.trim());
  return rampAt(ramp, (n - 1) / 13);
}
// 바로 옆 n일 전끼리 색이 비슷하므로 짝수 n일 전은 점선 (선 모양으로 한 번 더 구분)
const leadDash = (n) => (n > 0 && n % 2 === 0 ? [6, 4] : []);

// ---------- 숫자 ----------

function fmt(v, digits, signed) {
  if (v === null || v === undefined) return "–";
  const s = Number(v).toFixed(digits);
  return signed && v > 0 ? "+" + s : s;
}
// 달력 항목: 점수·날씨 변동성은 부호 없음, 나머지는 차이라서 부호
const signedMetric = (key) => key !== "score" && key !== "weather";
// 값 + 단위. 점수는 언어마다 표기가 달라 i18n 형식("95점" / "95 pts" / "95点")
function withUnit(text, m) {
  if (text === "–") return text;
  if (m.key === "score") return t("score_fmt", { v: text });
  return m.unit ? `${text} ${m.unit}` : text;
}

// ---------- 툴팁 ----------

const tip = $("#tooltip");
function showTip(event, value, label) {
  tip.replaceChildren(h("strong", {}, value), h("div", { class: "label" }, label));
  tip.hidden = false;
  const pad = 12;
  const rect = tip.getBoundingClientRect();
  let x = event.clientX + pad, y = event.clientY + pad;
  if (x + rect.width > window.innerWidth - 4) x = event.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 4) y = event.clientY - rect.height - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}
const hideTip = () => { tip.hidden = true; };

// ---------- 상태 ----------

const state = {
  meta: null,
  cities: [],
  mode: store.get("mode", "calendar"),
  cityId: store.get("city", null),
  view: store.get("view", "month"),
  metric: store.get("metric", "score"),
  anchor: null, // 달력 기준 날짜
  day: { data: null, date: null, metric: "temp_max", show: "chart" },
};
const narrow = window.matchMedia("(max-width: 760px)");

const city = () => state.cities.find((c) => c.city_id === state.cityId);
const cityById = (id) => state.cities.find((c) => c.city_id === id);
const cityLabel = (c) => (c.active ? c.name : t("city_stopped", { name: c.name }));
const calMetric = () => state.meta.calendar_metrics.find((m) => m.key === state.metric);
const today = () => city().today;

function setSeg(root, value) {
  for (const b of root.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.value === String(value)));
}
function onSeg(root, handler) {
  root.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-value]");
    if (b && !b.disabled) handler(b.dataset.value);
  });
}

// ---------- 시작 ----------

async function init() {
  try {
    i18n.languages = await fetchJSON("static/i18n/languages.json");
    await loadLanguage(pickLanguage());
    [state.meta, state.cities] = await Promise.all([api("meta"), api("cities")]);
  } catch (err) {
    showError(err);
    return;
  }
  for (const l of i18n.languages) $("#lang").append(h("option", { value: l.code }, l.name));
  $("#lang").value = i18n.lang;
  $("#lang").addEventListener("change", (e) => changeLanguage(e.target.value));

  if (!state.cities.length) {
    showError(new Error(t("no_cities")));
    return;
  }
  if (!city()) state.cityId = state.cities[0].city_id;
  if (!state.meta.calendar_metrics.some((m) => m.key === state.metric)) state.metric = "score";
  state.anchor = city().today;

  onSeg($("#mode"), (v) => { state.mode = v; store.set("mode", v); renderMode(); });
  onSeg($("#view"), (v) => { state.view = v; store.set("view", v); loadCalendar(); });
  $("#prev").addEventListener("click", () => move(-1));
  $("#next").addEventListener("click", () => move(1));
  $("#today").addEventListener("click", () => { state.anchor = city().today; loadCalendar(); });
  $("#metric").addEventListener("change", (e) => { state.metric = e.target.value; store.set("metric", state.metric); loadCalendar(); });
  $("#city-select").addEventListener("change", (e) => pickCity(e.target.value));
  narrow.addEventListener("change", () => { if (state.mode === "calendar") loadCalendar(); });
  new ResizeObserver(() => layoutYear()).observe($("#calendar"));

  initGraph();
  initDayModal();
  buildTexts();
  loadFailures();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.mode === "calendar") loadCalendar(); else rebuildPanels();
    if ($("#day-modal").open) drawDay();
  });
  renderMode();
}

// 언어에 따라 바뀌는 목록·버튼을 (다시) 만든다
function buildTexts() {
  buildCityPickers();
  $("#metric").replaceChildren(...state.meta.calendar_metrics.map((m) => h("option", { value: m.key }, t(`cal.${m.key}`))));
  $("#metric").value = state.metric;
  $("#day-metrics").replaceChildren(...state.meta.day_metrics.map((m) =>
    h("button", { type: "button", "data-value": m.key }, t(`day.${m.key}`))));
  buildGraphControls();
}

async function changeLanguage(code) {
  store.set("lang", code);
  try {
    await loadLanguage(code);
  } catch (err) {
    showError(err);
    return;
  }
  buildTexts();
  loadFailures();
  renderMode();
  if ($("#day-modal").open && state.day.data) { $("#day-title").textContent = dayTitle(state.day.date); drawDay(); }
}

function buildCityPickers() {
  const list = $("#city-list");
  list.replaceChildren();
  $("#city-select").replaceChildren();
  for (const c of state.cities) {
    list.append(h("button", { type: "button", "data-id": c.city_id, onclick: () => pickCity(c.city_id) },
      cityLabel(c), h("span", { class: "country" }, c.country || "")));
    $("#city-select").append(h("option", { value: c.city_id }, cityLabel(c)));
  }
}

function pickCity(id) {
  state.cityId = id;
  store.set("city", id);
  state.anchor = city().today;
  loadCalendar();
  syncCityPickers();
}
function syncCityPickers() {
  for (const b of $("#city-list").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.id === state.cityId));
  $("#city-select").value = state.cityId;
}

function renderMode() {
  setSeg($("#mode"), state.mode);
  $("#calendar-mode").hidden = state.mode !== "calendar";
  $("#graph-mode").hidden = state.mode !== "graph";
  hideTip();
  syncCityPickers();
  if (state.mode === "calendar") loadCalendar(); else showGraph();
}

// ---------- 수집 실패 알림 ----------
// 웹은 읽기 전용이라 DB의 read_at은 건드리지 않는다. "확인"한 마지막 번호를 이 브라우저에 저장해 그 뒤 것만 보여줌.

async function loadFailures() {
  let list;
  try { list = await api("errors"); } catch { return; } // 알림은 부가 기능: 실패해도 화면은 그대로
  const seen = store.get("errors.seen", 0);
  const fresh = list.filter((e) => e.error_id > seen);
  const banner = $("#fail-banner");
  banner.hidden = !fresh.length;
  if (!fresh.length) return;
  const latest = fresh[0];
  const when = (e) => `${e.occurred_at.slice(0, 16).replace("T", " ")} UTC`;
  $("#fail-summary").textContent = t("fail_summary", { n: fresh.length, when: when(latest) });
  $("#fail-list").replaceChildren(...fresh.map((e) => h("li", {}, `${when(e)} — ${e.message}`)));
  $("#fail-more").onclick = () => { $("#fail-list").hidden = !$("#fail-list").hidden; };
  $("#fail-ack").onclick = () => { store.set("errors.seen", latest.error_id); banner.hidden = true; };
}

// ---------- 달력 ----------

function move(step) {
  if (state.view === "week") state.anchor = addDays(state.anchor, 7 * step);
  else if (state.view === "month") state.anchor = addMonths(state.anchor, step);
  else state.anchor = addMonths(state.anchor, 12 * step);
  loadCalendar();
}

function calendarRange() {
  const a = state.anchor;
  if (state.view === "week") { const s = weekStart(a); return [s, addDays(s, 6)]; }
  if (state.view === "month") return [monthStart(a), monthEnd(a)];
  const y = a.slice(0, 4);
  return [`${y}-01-01`, `${y}-12-31`];
}

let calendarToken = 0;
async function loadCalendar() {
  setSeg($("#view"), state.view);
  const [start, end] = calendarRange();
  $("#period").textContent = state.view === "week" ? `${start.replaceAll("-", ".")} – ${md(end)}`
    : state.view === "month" ? periodMonth(+start.slice(0, 4), +start.slice(5, 7)) : t("period_year", { y: start.slice(0, 4) });
  const box = $("#calendar");
  box.style.opacity = "0.5"; // 새로 받는 동안 이전 화면 유지
  const token = ++calendarToken;
  try {
    const data = await api("calendar", { city: state.cityId, start, end, metric: state.metric });
    if (token !== calendarToken) return;
    showError(null);
    box.replaceChildren(state.view === "week" ? renderWeek(start, data.days)
      : state.view === "month" ? renderMonth(start, data.days) : renderYear(start, data.days));
    layoutYear();
    renderLegend();
  } catch (err) {
    showError(err);
  } finally {
    if (token === calendarToken) box.style.opacity = "";
  }
}

// 미래 날짜 중 예보가 있는 범위(오늘+14일)까지만 일간 보기를 연다
const openable = (d) => daysBetween(today(), d) <= 14;

function cellTip(date, lead, value) {
  const m = calMetric();
  return [withUnit(fmt(value, m.digits, signedMetric(m.key)), m), `${md(date)} (${dow(date)}) · ${leadLabel(lead)} · ${t(`cal.${m.key}`)}`];
}

// 당일 열: 실제 예보 값 (점수는 기준, 날씨 변동성은 당일 날씨 이름)
function d0Text(d0, m) {
  if (!d0) return "–";
  if (m.key === "score") return t("reference");
  if (m.key === "weather") return wxName(d0.weather_code);
  return fmt(d0.value, m.digits, false);
}

// 주간: 7행(일~토) × 15열(당일 → 하루 전 → … → 14일 전). 좁은 화면에서는 뒤집어 15행 × 7열
function renderWeek(start, days) {
  const m = calMetric();
  const dates = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const leads = state.meta.leads; // 1 → 14
  const valueUnit = m.key === "score" || m.key === "weather" ? "" : ` (${m.unit})`;
  const d0Cell = (d) => {
    const day = days[d];
    return h("td", {
      class: day ? "d0" : "d0 missing",
      onpointermove: day ? (e) => showTip(e, `${d0Text(day.d0, m)}${valueUnit && day.d0.value !== null ? " " + m.unit : ""}`,
        `${md(d)} (${dow(d)}) · ${t("d0_tip")}`) : null,
      onpointerleave: hideTip,
    }, d0Text(day && day.d0, m));
  };
  const cell = (d, lead) => {
    const day = days[d];
    const value = day ? day.values[lead - 1] : null;
    const bad = day ? day.bad[lead - 1] : null;
    if (value === null || value === undefined) return h("td", { class: "missing" }, "–");
    return h("td", {
      style: { background: withAlpha(heat(bad), 0.32) },
      onpointermove: (e) => showTip(e, ...cellTip(d, lead, value)),
      onpointerleave: hideTip,
    }, fmt(value, m.digits, signedMetric(m.key)));
  };
  const dayHead = (d) => h("th", { class: "row-head" },
    h("button", { type: "button", class: d === today() ? "is-today" : null, onclick: () => openDay(d),
                  disabled: !openable(d) }, narrow.matches ? [md(d), h("br"), `(${dow(d)})`] : `${md(d)} (${dow(d)})`));

  let table;
  if (!narrow.matches) {
    table = h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", { class: "d0" }, `${t("lead_0")}${valueUnit}`),
        leads.map((n) => h("th", {}, leadLabel(n))))),
      h("tbody", {}, dates.map((d) => h("tr", {}, dayHead(d), d0Cell(d), leads.map((n) => cell(d, n))))));
  } else {
    table = h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, h("th", { class: "row-head" }, t("lead_corner")), dates.map(dayHead))),
      h("tbody", {},
        h("tr", {}, h("th", { class: "row-head d0" }, t("lead_0")), dates.map(d0Cell)),
        leads.map((n) => h("tr", {}, h("th", { class: "row-head", title: leadLabel(n) }, t("lead_short", { n })),
          dates.map((d) => cell(d, n))))));
  }
  const wrap = h("div", { class: "table-wrap" }, table);
  if (!dates.some((d) => days[d])) wrap.append(h("p", { class: "empty" }, t("week_empty")));
  return wrap;
}

// 월간: 보통 달력. 칸마다 날짜, 당일 날씨·기온, 아래 14칸 띠 (왼쪽 하루 전 → 오른쪽 14일 전)
function renderMonth(start, days) {
  const end = monthEnd(start);
  const first = toDate(start).getUTCDay();
  const weeks = Math.ceil((first + daysBetween(start, end) + 1) / 7);
  const grid = h("div", { class: "month", style: { gridTemplateRows: `auto repeat(${weeks}, minmax(0, 1fr))` } },
    weekdays().map((d) => h("div", { class: "dow" }, d)));
  for (let i = 0; i < first; i++) grid.append(h("div", { class: "day-cell out" }));
  for (let d = start; d <= end; d = addDays(d, 1)) {
    const day = days[d];
    const strip = h("div", { class: "strip" });
    if (day) {
      for (let lead = 1; lead <= 14; lead++) {
        const bad = day.bad[lead - 1];
        const value = day.values[lead - 1];
        strip.append(h("span", {
          style: bad === null ? {} : { background: heat(bad) },
          onpointermove: (e) => showTip(e, ...cellTip(d, lead, value)),
          onpointerleave: hideTip,
        }));
      }
    }
    const d0 = day && day.d0;
    grid.append(h("button", {
      type: "button", class: "day-cell", disabled: !openable(d), onclick: () => openDay(d),
      "aria-label": t("open_day", { date: md(d) }),
    },
    h("span", { class: d === today() ? "num is-today" : "num" }, +d.slice(8)),
    d0 ? h("span", { class: "wx" }, wxName(d0.weather_code)) : null,
    d0 ? h("span", { class: "temp" }, `${fmt(d0.temp_max, 0)}° / ${fmt(d0.temp_min, 0)}°`) : null,
    strip));
  }
  const trailing = weeks * 7 - first - (daysBetween(start, end) + 1);
  for (let i = 0; i < trailing; i++) grid.append(h("div", { class: "day-cell out" }));
  return grid;
}

// 연간: 날짜마다 14개 변동 정도의 중앙값 → 그 해 다른 날짜들과 비교한 순위로 색. 배치는 layoutYear()
function renderYear(start, days) {
  const medians = {};
  for (const [d, day] of Object.entries(days)) {
    const vs = day.bad.filter((v) => v !== null).sort((a, b) => a - b);
    if (!vs.length) continue;
    const mid = vs.length >> 1;
    medians[d] = vs.length % 2 ? vs[mid] : (vs[mid - 1] + vs[mid]) / 2;
  }
  const sorted = Object.values(medians).sort((a, b) => a - b);
  const rank = (v) => (sorted.length < 2 ? 0.5 : sorted.indexOf(v) / (sorted.length - 1));

  const year = h("div", { class: "year" });
  for (let mth = 0; mth < 12; mth++) {
    const ms = addMonths(start, mth);
    const daysBox = h("div", { class: "days" });
    const first = toDate(ms).getUTCDay();
    for (let i = 0; i < first; i++) daysBox.append(h("span", { class: "out" }));
    for (let d = ms; d <= monthEnd(ms); d = addDays(d, 1)) {
      const med = medians[d];
      const r = med === undefined ? null : rank(med);
      daysBox.append(h("button", {
        type: "button",
        class: d === today() ? "today" : null,
        style: r === null ? {} : { background: heat(r) },
        disabled: !openable(d),
        "aria-label": t("open_day", { date: md(d) }),
        onclick: () => openDay(d),
        onpointermove: (e) => (med === undefined
          ? showTip(e, t("no_data"), `${md(d)} (${dow(d)})`)
          : showTip(e, t("median", { v: med.toFixed(2) }), `${md(d)} (${dow(d)}) · ${r >= 0.5
            ? t("year_rank_high", { n: sorted.length, p: Math.round((1 - r) * 100) })
            : t("year_rank_low", { n: sorted.length, p: Math.round(r * 100) })}`)),
        onpointerleave: hideTip,
      }));
    }
    const filled = first + daysBetween(ms, monthEnd(ms)) + 1;
    for (let i = filled; i < 42; i++) daysBox.append(h("span", { class: "out" })); // 6줄로 맞춤
    year.append(h("div", { class: "mini" }, h("h3", {}, monthName(mth + 1)),
      h("div", { class: "dows" }, weekdays().map((d) => h("span", {}, d))), daysBox));
  }
  return year;
}

// 연간 배치: 화면 비율에 따라 날짜 칸이 가장 크게 나오는 열×행. 어떤 배치로도 너무 작으면 고정 크기 + 스크롤
const YEAR_LAYOUTS = [[4, 3], [3, 4], [6, 2], [2, 6], [12, 1]];
const YEAR_MIN_CELL = 12; // px
function layoutYear() {
  const box = $("#calendar");
  const year = box.querySelector(".year");
  if (!year) return;
  if (narrow.matches) { // 좁은 화면은 CSS의 2열 + 세로 스크롤
    year.classList.remove("scroll");
    year.style.gridTemplateColumns = year.style.gridTemplateRows = "";
    return;
  }
  const cs = getComputedStyle(box);
  const W = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const H = box.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  const gapX = 20, gapY = 14, head = 38; // .year의 간격, 달 이름 + 요일 줄
  let best = null;
  for (const [cols, rows] of YEAR_LAYOUTS) {
    const cellW = ((W - gapX * (cols - 1)) / cols - 2 * 6) / 7;
    const cellH = ((H - gapY * (rows - 1)) / rows - head - 2 * 5) / 6;
    const cell = Math.min(cellW, cellH);
    if (!best || cell > best.cell) best = { cols, rows, cell };
  }
  const scroll = best.cell < YEAR_MIN_CELL;
  year.classList.toggle("scroll", scroll);
  year.style.gridTemplateColumns = scroll ? "repeat(4, 150px)" : `repeat(${best.cols}, minmax(0, 1fr))`;
  year.style.gridTemplateRows = scroll ? "repeat(3, auto)" : `repeat(${best.rows}, minmax(0, 1fr))`;
}

function renderLegend() {
  const legend = $("#legend");
  const bar = h("span", { class: "bar", style: { background: `linear-gradient(90deg, ${heatStops().join(", ")})` } });
  const missing = h("span", {}, h("span", { class: "swatch" }), t("no_data"));
  if (state.view === "year") {
    legend.replaceChildren(h("span", { class: "ramp" }, t("less_var"), bar, t("more_var")), h("span", {}, t("legend_year")), missing);
    return;
  }
  const m = calMetric();
  const w = state.meta.worst[m.key];
  const [left, right] = m.key === "score" ? [t("legend_score_left"), t("legend_score_right", { w })]
    : m.key === "weather" ? [t("legend_weather_left"), t("legend_weather_right")]
      : [t("legend_diff_left", { unit: m.unit }), t("legend_diff_right", { w, unit: m.unit })];
  const note = state.view === "month" ? "legend_month"
    : m.key === "score" ? "legend_week_score" : m.key === "weather" ? "legend_week_weather" : "legend_week_diff";
  legend.replaceChildren(h("span", { class: "ramp" }, left, bar, right), missing, h("span", {}, t(note)));
}

// ---------- Chart.js 공통 ----------

function chartTheme() {
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--grid");
}

// 툴팁이 떠 있는 X에 세로 기준선
const crosshair = {
  id: "crosshair",
  afterDatasetsDraw(chart) {
    const active = chart.tooltip?.getActiveElements?.() || [];
    if (!active.length) return;
    const { ctx, chartArea } = chart;
    const x = active[0].element.x;
    ctx.save();
    ctx.strokeStyle = css("--axis");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

function tooltipStyle() {
  return {
    backgroundColor: css("--surface"),
    titleColor: css("--text-2"),
    bodyColor: css("--text"),
    borderColor: css("--border"),
    borderWidth: 1,
    padding: 8,
    boxWidth: 14,
    boxHeight: 2,
  };
}

// ---------- 일간 모달 ----------

let dayChart = null;

function initDayModal() {
  const dlg = $("#day-modal");
  $("#day-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); }); // 바깥(배경) 클릭
  dlg.addEventListener("close", hideTip);
  onSeg($("#day-metrics"), (v) => { state.day.metric = v; drawDay(); });
  onSeg($("#day-show"), (v) => { state.day.show = v; drawDay(); });
}

const dayTitle = (date) => `${city().name} · ${date} (${dow(date)})`;

async function openDay(date) {
  hideTip();
  const dlg = $("#day-modal");
  state.day.date = date;
  $("#day-title").textContent = dayTitle(date);
  $("#day-sub").textContent = t("loading");
  if (!dlg.open) dlg.showModal();
  try {
    state.day.data = await api("day", { city: state.cityId, date });
    drawDay();
  } catch (err) {
    $("#day-sub").textContent = t("load_failed", { msg: err.message });
  }
}

function drawDay() {
  const data = state.day.data;
  if (!data) return;
  const m = state.meta.day_metrics.find((x) => x.key === state.day.metric);
  setSeg($("#day-metrics"), m.key);
  setSeg($("#day-show"), state.day.show);
  const available = data.leads.filter((l) => l.available);
  $("#day-sub").textContent = data.has_d0 ? t("day_sub", { wx: wxName(data.d0_weather_code) }) : t("day_sub_no_d0");
  $("#day-note").textContent = !available.length ? t("day_none")
    : m.key === "weather" ? t("day_note_weather") : data.has_d0 ? t("day_note_diff") : "";

  const chartBox = $("#day-chart-box"), tableBox = $("#day-table");
  chartBox.hidden = state.day.show !== "chart";
  tableBox.hidden = state.day.show !== "table";
  if (state.day.show === "table") { tableBox.replaceChildren(dayTable(data)); return; }

  chartTheme();
  const useDiff = data.has_d0;
  const points = data.leads.map((l) => (l.available ? (useDiff ? l.diffs[m.key] : l.values[m.key]) : null));
  const color = css("--accent");
  const unit = m.key === "weather" ? "" : m.unit;
  if (dayChart) dayChart.destroy();
  dayChart = new Chart($("#day-chart"), {
    type: "line",
    data: {
      labels: data.leads.map((l) => leadLabel(l.lead)),
      datasets: [{
        label: t(`day.${m.key}`), data: points, borderColor: color, backgroundColor: color,
        borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, spanGaps: true, tension: 0,
      }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle(),
          displayColors: false,
          callbacks: {
            title: (items) => items[0].label,
            label: (item) => {
              const l = data.leads[item.dataIndex];
              const main = withUnit(fmt(item.raw, m.digits, useDiff && m.key !== "weather"), { key: m.key, unit });
              const v = m.key === "weather" ? wxName(l.weather_code) : withUnit(fmt(l.values[m.key], m.digits, false), m);
              return useDiff ? `${main}   ${t("forecast_paren", { v })}` : main;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: css("--axis") } },
        y: {
          title: { display: !!unit, text: unit },
          border: { display: false },
          ...(m.key === "weather" ? { min: 0, max: 1 } : {}), // 날씨 변동성은 0~1 고정 (날짜끼리 비교 가능하게)
          grid: { color: (ctx) => (ctx.tick.value === 0 && useDiff ? css("--axis") : css("--grid")),
                  lineWidth: (ctx) => (ctx.tick.value === 0 && useDiff ? 1.5 : 1) },
          ticks: { callback: (v) => fmt(v, m.digits > 1 ? 2 : m.digits, useDiff && m.key !== "weather") },
        },
      },
    },
    plugins: [crosshair],
  });
}

function dayTable(data) {
  const ms = state.meta.day_metrics.filter((m) => m.key !== "weather");
  const head = h("tr", {}, h("th", { class: "row-head" }, ""), h("th", {}, t("col_weather")),
    ms.map((m) => h("th", {}, m.unit ? `${t(`day.${m.key}`)} (${m.unit})` : t(`day.${m.key}`))), h("th", {}, t("col_score")));
  const rows = data.leads.map((l) => {
    if (!l.available) {
      return h("tr", {}, h("th", { class: "row-head" }, leadLabel(l.lead)),
        h("td", { class: "missing name", colspan: ms.length + 2 }, t("not_collected")));
    }
    const mismatch = l.diffs && l.lead && !l.weather_match;
    return h("tr", {},
      h("th", { class: "row-head" }, leadLabel(l.lead)),
      h("td", { class: "name" }, wxName(l.weather_code), mismatch ? h("span", { class: "mismatch" }, t("differs")) : null),
      ms.map((m) => h("td", {}, fmt(l.values[m.key], m.digits, false),
        l.diffs && l.lead ? h("div", { class: "diff" }, fmt(l.diffs[m.key], m.digits, true)) : null)),
      h("td", {}, l.lead === 0 ? t("reference") : fmt(l.score, 1, false)));
  });
  return h("table", { class: "grid day-table" }, h("thead", {}, head), h("tbody", {}, rows));
}

// ---------- 그래프 모드 ----------
// 분할(1·2·4·8·16)마다 도시·항목을 따로 고르고, 보이는 기간은 모든 그래프가 함께 움직인다.
// 한 그래프에 커서를 올리면 다른 분할에도 같은 시각에 세로선·툴팁이 뜬다.
// 점 하나의 단위(1시간 ~ 1달)는 사용자가 고른다 (자동으로 바뀌지 않음).
// 하루 이하 단위는 서버가 1시간 슬롯을 묶어서 준다('slot' + hours): 하루 통합과 같은 규칙
//   (최고기온 최대, 최저기온 최소, 강수량 합계, 강수확률·바람 최대, 가시거리 최소).
// 1일은 하루 통합 값('day') 그대로, 3일·1주·1달은 화면이 그것을 묶는다: 하루 값의 평균 (평균 최고·최저기온), 강수량은 합계
// 휠: 확대·축소 / Shift+휠, 가로 휠, 끌기: 앞뒤 이동.

const MAX_BACK_DAYS = 730; // 최대 2년 전까지
const AHEAD_DAYS = 15; // 예보가 있는 미래 (오늘 + 14일)
const MIN_SPAN = 12 * HOUR;
const LAYOUTS = { 1: [1, 1], 2: [2, 1], 4: [2, 2], 8: [4, 2], 16: [4, 4] }; // 열 × 행
// maxDays: 이 단위로 한 화면에 볼 수 있는 최대 기간 (1시간 단위로 2년을 펼치면 그래프 하나에 26만 점이 되어 느려짐)
const BINS = [
  { key: "1h", ms: HOUR, src: "slot", maxDays: 20 },
  { key: "3h", ms: 3 * HOUR, src: "slot", maxDays: 60 },
  { key: "6h", ms: 6 * HOUR, src: "slot", maxDays: 120 },
  { key: "12h", ms: 12 * HOUR, src: "slot", maxDays: 240 },
  { key: "1d", ms: DAY, src: "day", maxDays: MAX_BACK_DAYS + AHEAD_DAYS },
  { key: "3d", ms: 3 * DAY, src: "day", maxDays: MAX_BACK_DAYS + AHEAD_DAYS },
  { key: "1w", ms: 7 * DAY, src: "day", maxDays: MAX_BACK_DAYS + AHEAD_DAYS },
  { key: "1m", ms: 30 * DAY, src: "day", maxDays: MAX_BACK_DAYS + AHEAD_DAYS },
];
const SLOT_MARGIN = 14 * DAY; // 시간 단위 값은 보이는 기간 앞뒤로 더 받아 둠
// 여러 항목을 한 그래프에: 최고·최저기온 (선 a = 최고, 선 b = 최저)
const COMPOSITE = { temp_range: { key: "temp_range", unit: "℃", digits: 1, parts: ["temp_max", "temp_min"] } };
const PART_KEYS = ["part_max", "part_min"];

const graph = {
  count: store.get("g.count", 1),
  bin: BINS.find((b) => b.key === store.get("g.bin", "3h")) || BINS[0],
  panels: store.get("g.panels", []), // [{city, metric}]
  leads: new Set(store.get("g.leads", [0, 1, 3, 7, 14])),
  show: "chart",
  view: null, // {min, max} ms
  charts: [], // 분할마다 {chart, box, table}
};
const sourceCache = new Map(); // "도시|항목|slot1·slot3…·day" → {start, end, version, leads: {n: [{x, y}]}}
const binCache = new Map(); // "도시|항목|단위" → {version, leads}

const xValue = (x) => Date.parse(x.length === 10 ? x + "T00:00:00Z" : x + ":00Z");
const isoOf = (ms) => new Date(ms).toISOString().slice(0, 10);
const seriesMetric = (key) => COMPOSITE[key] || state.meta.series_metrics.find((m) => m.key === key);
const metricParts = (m) => m.parts || [m.key];
const seriesMetricList = () => { // 최고·최저기온은 최저기온 바로 뒤에
  const list = [];
  for (const m of state.meta.series_metrics) {
    list.push(m);
    if (m.key === "temp_min") list.push(COMPOSITE.temp_range);
  }
  return list;
};
const binLabel = (bin) => t(`bin.${bin.key}`);

function bounds() {
  const x = xValue(today());
  return [x - MAX_BACK_DAYS * DAY, x + AHEAD_DAYS * DAY];
}
function clampView(min, max) {
  const [lo, hi] = bounds();
  const span = Math.min(hi - lo, graph.bin.maxDays * DAY, Math.max(MIN_SPAN, max - min));
  min = Math.min(Math.max(min, lo), hi - span);
  return { min, max: min + span };
}

function initGraph() {
  onSeg($("#g-count"), (v) => { graph.count = +v; store.set("g.count", graph.count); rebuildPanels(); });
  onSeg($("#g-show"), (v) => { graph.show = v; rebuildPanels(); });
  onSeg($("#g-bin"), (v) => {
    graph.bin = BINS.find((b) => b.key === v);
    store.set("g.bin", v);
    if (graph.view) { // 새 단위의 최대 기간보다 넓으면 가운데를 기준으로 줄임
      const mid = (graph.view.min + graph.view.max) / 2, half = (graph.view.max - graph.view.min) / 2;
      graph.view = clampView(mid - half, mid + half);
    }
    buildGraphControls();
    renderGraphs();
    loadVisible();
  });
}

// 언어·단위에 따라 바뀌는 단위 버튼·기간 버튼·n일 전 버튼
function buildGraphControls() {
  $("#g-bin").replaceChildren(...BINS.map((b) => h("button", { type: "button", "data-value": b.key }, binLabel(b))));
  setSeg($("#g-bin"), graph.bin.key);

  const x = () => xValue(today());
  const presets = [
    [t("preset_past", { n: 7 }), -6, 1], [t("preset_past", { n: 14 }), -13, 1], [t("preset_next", { n: 14 }), 0, 15],
    [t("preset_past", { n: 30 }), -29, 1], [t("preset_past", { n: 90 }), -89, 1],
    [t("preset_1y"), -364, 1], [t("preset_2y"), -MAX_BACK_DAYS + 1, 1],
  ];
  $("#g-presets").replaceChildren(...presets.map(([label, from, to]) => {
    const tooLong = to - from > graph.bin.maxDays;
    return h("button", {
      type: "button", disabled: tooLong,
      title: tooLong ? t("preset_too_long", { bin: binLabel(graph.bin), days: graph.bin.maxDays }) : null,
      onclick: () => setView(x() + from * DAY, x() + to * DAY),
    }, label);
  }));

  const box = $("#g-leads");
  box.replaceChildren();
  for (let n = 0; n <= 14; n++) {
    box.append(h("button", {
      type: "button", "data-lead": n,
      onclick: () => toggleLead(n),
      onpointerenter: () => emphasize(n),
      onpointerleave: () => emphasize(null),
      onfocus: () => emphasize(n),
      onblur: () => emphasize(null),
    }, h("span", { class: leadDash(n).length ? "key dashed" : "key" }), leadLabel(n)));
  }
  box.append(h("button", { type: "button", class: "all", onclick: () => {
    const all = graph.leads.size === 15;
    graph.leads = new Set(all ? [0] : Array.from({ length: 15 }, (_, i) => i));
    store.set("g.leads", [...graph.leads]);
    renderGraphs();
  } }, t("leads_all")));
  updateLeadButtons();
}

function showGraph() {
  if (!graph.view) {
    const x = xValue(today());
    graph.view = clampView(x - 6 * DAY, x + 8 * DAY);
  }
  rebuildPanels();
}

function toggleLead(n) {
  if (graph.leads.has(n)) graph.leads.delete(n); else graph.leads.add(n);
  store.set("g.leads", [...graph.leads]);
  renderGraphs();
}

// 선 색: n일 전 색, 최고·최저기온의 최저(선 b)는 같은 색을 조금 옅게
const partColor = (lead, part) => (part === 0 ? leadColor(lead) : withAlpha(leadColor(lead), 0.55));

// 버튼에 올리면 그 선만 진하게
function emphasize(n) {
  for (const { chart } of graph.charts) {
    if (!chart) continue;
    for (const ds of chart.data.datasets) {
      ds.borderColor = n === null || ds.lead === n ? partColor(ds.lead, ds.part) : withAlpha(leadColor(ds.lead), 0.12);
      ds.borderWidth = ds.lead === n ? 3 : ds.lead === 0 ? 2.5 : 1.75;
    }
    chart.update("none");
  }
}

function panelDefaults(i) {
  const metrics = seriesMetricList().map((m) => m.key);
  const cityAt = state.cities[i % state.cities.length].city_id;
  return { city: i === 0 ? state.cityId : cityAt, metric: metrics[Math.floor(i / state.cities.length) % metrics.length] };
}

function rebuildPanels() {
  if (state.mode !== "graph") return;
  setSeg($("#g-count"), graph.count);
  setSeg($("#g-show"), graph.show);
  for (const { chart } of graph.charts) chart?.destroy();
  graph.charts = [];
  for (let i = 0; i < graph.count; i++) {
    const p = graph.panels[i];
    if (!p || !cityById(p.city) || !seriesMetric(p.metric)) graph.panels[i] = panelDefaults(i);
  }
  store.set("g.panels", graph.panels);

  const [cols, rows] = LAYOUTS[graph.count];
  const host = $("#g-panels");
  host.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  host.style.gridTemplateRows = `repeat(${rows}, minmax(0, 1fr))`;
  host.replaceChildren();
  chartTheme();
  for (let i = 0; i < graph.count; i++) {
    const p = graph.panels[i];
    const citySel = h("select", { "aria-label": t("aria_city"), onchange: (e) => { p.city = e.target.value; panelChanged(); } },
      state.cities.map((c) => h("option", { value: c.city_id }, cityLabel(c))));
    const metricSel = h("select", { "aria-label": t("metric_label"), onchange: (e) => { p.metric = e.target.value; panelChanged(); } },
      seriesMetricList().map((m) => h("option", { value: m.key }, t(`series.${m.key}`))));
    citySel.value = p.city;
    metricSel.value = p.metric;
    const canvas = h("canvas");
    const box = h("div", { class: "chart-box", hidden: graph.show !== "chart" }, canvas);
    const table = h("div", { class: "table-wrap", hidden: graph.show !== "table" });
    host.append(h("div", { class: "panel" }, h("div", { class: "panel-head" }, citySel, metricSel), box, table));
    const entry = { box, table, chart: graph.show === "chart" ? makeSeriesChart(canvas, i) : null };
    graph.charts.push(entry);
    if (entry.chart) attachNavigation(canvas, entry);
  }
  updateLeadButtons();
  renderGraphs();
  loadVisible();
}

function panelChanged() {
  store.set("g.panels", graph.panels);
  renderGraphs();
  loadVisible();
}

function updateLeadButtons() {
  for (const b of $("#g-leads").querySelectorAll("button[data-lead]")) {
    const n = +b.dataset.lead;
    b.setAttribute("aria-pressed", String(graph.leads.has(n)));
    b.querySelector(".key").style.borderTopColor = leadColor(n);
  }
}

// ---- 데이터: 보이는 기간에 맞춰 필요한 만큼 ----

const binSource = (bin) => (bin.src === "day" ? "day" : `slot${bin.ms / HOUR}`);
const sourceKey = (cityId, metric, bin) => `${cityId}|${metric}|${binSource(bin)}`;

function wantedRange(bin) {
  const [lo, hi] = bounds();
  if (bin.src === "day") return [lo, hi]; // 하루 값은 2년치를 한 번에 (도시·항목당 수백 KB)
  const margin = Math.max(SLOT_MARGIN, (graph.view.max - graph.view.min) / 2);
  return [Math.max(lo, graph.view.min - margin), Math.min(hi, graph.view.max + margin)];
}

const inflight = new Map();
let sourceVersion = 0;
async function ensureSource(cityId, metric, bin) {
  const key = sourceKey(cityId, metric, bin);
  const [lo, hi] = wantedRange(bin);
  const have = sourceCache.get(key);
  if (have && have.start <= lo && have.end >= hi) return false;
  const reqKey = `${key}|${isoOf(lo)}|${isoOf(hi)}`;
  if (inflight.has(reqKey)) return inflight.get(reqKey);
  const job = (async () => {
    const params = { city: cityId, metric, step: bin.src, start: isoOf(lo), end: isoOf(hi) };
    if (bin.src === "slot") params.hours = bin.ms / HOUR;
    const data = await api("series", params);
    const stepMs = bin.src === "day" ? DAY : bin.ms;
    const leads = {};
    for (const [n, rows] of Object.entries(data.leads)) leads[n] = toPoints(rows.map(([x, y]) => [xValue(x), y]), stepMs);
    sourceCache.set(key, { start: lo, end: hi, version: ++sourceVersion, leads });
    return true;
  })().finally(() => inflight.delete(reqKey));
  inflight.set(reqKey, job);
  return job;
}

const loadVisible = debounce(async () => {
  if (state.mode !== "graph") return;
  try {
    const jobs = [];
    for (const p of graph.panels.slice(0, graph.count)) {
      for (const metric of metricParts(seriesMetric(p.metric))) jobs.push(ensureSource(p.city, metric, graph.bin));
    }
    const changed = await Promise.all(jobs);
    showError(null);
    if (changed.some(Boolean)) renderGraphs();
  } catch (err) {
    showError(err);
  }
}, 150);

// [[x(ms), y], …] → 점 배열. 간격이 비면 null을 넣어 선을 잇지 않는다
function toPoints(rows, step, nextOf = (x) => x + step) {
  const out = [];
  let prev = null;
  for (const [x, y] of rows) {
    if (prev !== null && x > nextOf(prev) + step * 0.5) out.push({ x: nextOf(prev), y: null });
    out.push({ x, y });
    prev = x;
  }
  return out;
}

// 단위 구간의 시작 (UTC 기준 = 도시 현지 시각 그대로)
const MONDAY = 4 * DAY; // 1970-01-05가 월요일: 1주는 월요일 시작 (ISO 주)
function binStart(x, bin) {
  if (bin.key === "1m") { const d = new Date(x); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1); }
  if (bin.key === "1w") return Math.floor((x - MONDAY) / bin.ms) * bin.ms + MONDAY;
  return Math.floor(x / bin.ms) * bin.ms;
}
function binNext(x, bin) {
  if (bin.key === "1m") { const d = new Date(x); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1); }
  return x + bin.ms;
}

// 여러 날 단위만 하루 통합 값을 묶는다 (규칙은 맨 위 주석). 하루 이하 단위는 서버가 묶어 준 그대로
function aggregate(points, bin, metric) {
  if (bin.ms <= DAY) return points;
  const rule = metric === "precip" ? "sum" : "mean";
  const acc = new Map();
  for (const { x, y } of points) {
    if (y === null) continue;
    const k = binStart(x, bin);
    const a = acc.get(k);
    if (!a) acc.set(k, { v: y, n: 1 });
    else { a.v += y; a.n += 1; }
  }
  const rows = [...acc.entries()].sort((a, b) => a[0] - b[0])
    .map(([x, { v, n }]) => [x, rule === "mean" ? v / n : v]);
  return toPoints(rows, bin.ms, (x) => binNext(x, bin));
}

// 분할 하나의 데이터: 항목의 각 부분(최고·최저기온이면 둘)마다 {n일 전: 점 배열}
function binned(p, bin) {
  return metricParts(seriesMetric(p.metric)).map((metric) => {
    const src = sourceCache.get(sourceKey(p.city, metric, bin));
    if (!src) return null;
    const key = `${p.city}|${metric}|${bin.key}`;
    const have = binCache.get(key);
    if (have && have.version === src.version) return have.leads;
    const leads = {};
    for (const [n, pts] of Object.entries(src.leads)) leads[n] = aggregate(pts, bin, metric);
    binCache.set(key, { version: src.version, leads });
    return leads;
  });
}

// 정렬된 점 배열에서 [from, to] 구간만 (앞뒤 한 점씩 더 → 선이 가장자리까지 이어짐)
function sliceRange(points, from, to) {
  let lo = 0, hi = points.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (points[mid].x < from) lo = mid + 1; else hi = mid; }
  let end = lo;
  while (end < points.length && points[end].x <= to) end++;
  return points.slice(Math.max(0, lo - 1), Math.min(points.length, end + 1));
}

// ---- 그리기 ----

const pad2 = (n) => String(n).padStart(2, "0");
// 눈금: 점이 3일·1주·1달 단위면 점과 같은 자리(구간 시작)에, 아니면 자정·1시간 등 보기 좋은 간격으로
function niceTicks(min, max, width) {
  const span = max - min;
  const maxTicks = Math.max(2, Math.floor(width / 80));
  const bin = graph.bin;
  const ticks = [];
  if (bin.key === "1m" || span > 75 * DAY) { // 달 단위
    const months = [1, 2, 3, 6, 12].find((k) => span / (k * 30 * DAY) <= maxTicks) || 12;
    const d = new Date(min);
    d.setUTCDate(1); d.setUTCHours(0, 0, 0, 0);
    while (d.getTime() < min) d.setUTCMonth(d.getUTCMonth() + 1);
    while (d.getUTCMonth() % months) d.setUTCMonth(d.getUTCMonth() + 1);
    for (; d.getTime() <= max; d.setUTCMonth(d.getUTCMonth() + months)) ticks.push({ value: d.getTime() });
    return ticks;
  }
  if (bin.ms > DAY) { // 3일·1주: 구간 시작에 맞춘 눈금 (몇 구간마다)
    const every = [1, 2, 4, 8, 16].find((k) => span / (k * bin.ms) <= maxTicks) || 16;
    for (let x = binStart(min, bin); x <= max; x += every * bin.ms) if (x >= min) ticks.push({ value: x });
    return ticks;
  }
  const step = [HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY]
    .filter((s) => s >= bin.ms).find((s) => span / s <= maxTicks) || 14 * DAY;
  for (let x = Math.ceil(min / step) * step; x <= max; x += step) ticks.push({ value: x });
  return ticks;
}
function tickLabel(ms, span) {
  const d = new Date(ms);
  if (graph.bin.key === "1m" || span > 75 * DAY) {
    return d.getUTCMonth() === 0 ? t("month_tick_year", { y: d.getUTCFullYear() }) : monthName(d.getUTCMonth() + 1);
  }
  const date = `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  return d.getUTCHours() ? `${date} ${t("hour", { h: pad2(d.getUTCHours()) })}` : date;
}
const dateLabel = (d) => `${d.getUTCFullYear()}.${d.getUTCMonth() + 1}.${d.getUTCDate()}`;
// 점 하나가 나타내는 구간 (툴팁·표)
function pointLabel(ms, bin) {
  const d = new Date(ms);
  const end = new Date(binNext(ms, bin) - 1);
  switch (bin.key) {
    case "1h": return `${dateLabel(d)} ${t("hour", { h: pad2(d.getUTCHours()) })}`;
    case "3h": case "6h": case "12h": return `${dateLabel(d)} ${t("hour", { h: pad2(d.getUTCHours()) })}–${t("hour", { h: pad2(end.getUTCHours() + 1) })}`;
    case "1d": return dateLabel(d);
    case "1m": return periodMonth(d.getUTCFullYear(), d.getUTCMonth() + 1);
    default: return `${dateLabel(d)} – ${end.getUTCMonth() + 1}/${end.getUTCDate()}`;
  }
}

// 선은 n일 전 15개 × 부분 2개(최고·최저기온일 때만 둘 다 씀)
function makeSeriesChart(canvas, i) {
  const datasets = [];
  for (let n = 14; n >= 0; n--) { // 당일이 맨 위에 그려지도록 마지막에
    for (const part of [1, 0]) {
      datasets.push({
        lead: n, part, label: leadLabel(n), data: [], hidden: true,
        borderColor: partColor(n, part), backgroundColor: partColor(n, part),
        borderWidth: n === 0 ? 2.5 : 1.75, borderDash: leadDash(n),
        pointRadius: 0, pointHoverRadius: 3, tension: 0, spanGaps: false,
      });
    }
  }
  return new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      normalized: true,
      // 가로 위치가 가장 가까운 시점의 모든 선 (점을 정확히 짚지 않아도 됨)
      interaction: { mode: "nearest", axis: "x", intersect: false },
      onHover: (event, elements, chart) => syncHover(chart, elements),
      plugins: {
        legend: { display: false }, // 오른쪽 버튼이 범례
        tooltip: {
          ...tooltipStyle(),
          itemSort: (a, b) => a.dataset.lead - b.dataset.lead || a.dataset.part - b.dataset.part,
          filter: (item) => item.raw.y !== null,
          callbacks: {
            title: (items) => pointLabel(items[0].raw.x, graph.bin),
            label: (item) => {
              const m = seriesMetric(graph.panels[i].metric);
              const part = m.parts ? ` ${t(PART_KEYS[item.dataset.part])}` : "";
              return `${withUnit(fmt(item.raw.y, m.digits, false), m)}  ${item.dataset.label}${part}`;
            },
            labelColor: (item) => ({ borderColor: item.dataset.borderColor, backgroundColor: item.dataset.borderColor }),
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          grid: { display: false },
          border: { color: css("--axis") },
          afterBuildTicks: (axis) => { axis.ticks = niceTicks(axis.min, axis.max, axis.chart.width); },
          ticks: { maxRotation: 0, autoSkip: false, callback: (v) => tickLabel(v, graph.view.max - graph.view.min) },
        },
        y: { border: { display: false }, title: { display: false } },
      },
    },
    plugins: [crosshair],
  });
}

// ---- 분할끼리 커서 맞추기: 한 그래프에서 고른 시각을 다른 그래프에도 표시 ----

function syncHover(source, elements) {
  const x = elements.length ? source.data.datasets[elements[0].datasetIndex].data[elements[0].index].x : null;
  for (const { chart } of graph.charts) {
    if (chart && chart !== source) showAt(chart, x);
  }
}

function showAt(chart, x) {
  const active = [];
  if (x !== null) {
    chart.data.datasets.forEach((ds, di) => {
      if (ds.hidden || !ds.data.length) return;
      let lo = 0, hi = ds.data.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (ds.data[mid].x < x) lo = mid + 1; else hi = mid; }
      const i = lo < ds.data.length && ds.data[lo].x === x ? lo : -1; // 같은 단위라 시각이 정확히 같음
      if (i >= 0 && ds.data[i].y !== null) active.push({ datasetIndex: di, index: i });
    });
  }
  const area = chart.chartArea;
  chart.setActiveElements(active);
  chart.tooltip.setActiveElements(active, { x: chart.scales.x.getPixelForValue(x ?? 0), y: (area.top + area.bottom) / 2 });
  chart.update("none");
}

let renderQueued = false;
function renderGraphs() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; drawGraphs(); });
}

function drawGraphs() {
  if (state.mode !== "graph" || !graph.view) return;
  const v = graph.view;
  const span = v.max - v.min;
  const bin = graph.bin;
  $("#g-range").textContent = `${dateLabel(new Date(v.min))} – ${dateLabel(new Date(v.max))}`;
  const atMax = span >= bin.maxDays * DAY - HOUR && bin.maxDays < MAX_BACK_DAYS;
  const how = bin.key === "1h" ? "graph_how_raw" : bin.ms <= DAY ? "graph_how_day" : "graph_how_days";
  $("#g-note").textContent = t("graph_note", { bin: binLabel(bin), how: t(how) })
    + (atMax ? ` · ${t("bin_max", { bin: binLabel(bin), days: bin.maxDays })}` : "");
  updateLeadButtons();
  const radius = span / bin.ms <= 90 ? 2 : 0; // 점이 적을 때는 점도 찍음
  graph.charts.forEach((entry, i) => {
    const p = graph.panels[i];
    const m = seriesMetric(p.metric);
    const parts = binned(p, bin);
    if (graph.show === "table") {
      entry.table.replaceChildren(seriesTable(parts, m, v, bin));
      return;
    }
    const chart = entry.chart;
    chart.options.scales.x.min = v.min;
    chart.options.scales.x.max = v.max;
    chart.options.scales.y.title = { display: !!m.unit, text: m.unit };
    for (const ds of chart.data.datasets) {
      ds.hidden = !graph.leads.has(ds.lead) || ds.part >= parts.length;
      ds.pointRadius = radius;
      ds.borderColor = ds.backgroundColor = partColor(ds.lead, ds.part);
      const pts = !ds.hidden && parts[ds.part] && parts[ds.part][String(ds.lead)];
      ds.data = pts ? sliceRange(pts, v.min - span * 0.05, v.max + span * 0.05) : [];
    }
    chart.update("none");
  });
}

function seriesTable(parts, m, v, bin) {
  const leads = [...graph.leads].sort((a, b) => a - b);
  const byX = new Map(); // x → {n일 전: [최고, 최저] 또는 [값]}
  parts.forEach((leadsData, part) => {
    for (const n of leads) {
      const pts = leadsData && leadsData[String(n)];
      if (!pts) continue;
      for (const pt of sliceRange(pts, v.min, v.max)) {
        if (pt.y === null || pt.x < v.min || pt.x > v.max) continue;
        if (!byX.has(pt.x)) byX.set(pt.x, {});
        (byX.get(pt.x)[n] ||= [])[part] = pt.y;
      }
    }
  });
  const xs = [...byX.keys()].sort((a, b) => a - b);
  if (!leads.length || !xs.length) return h("p", { class: "empty" }, t("no_values"));
  const shown = xs.slice(0, 500);
  const hourly = bin.ms < DAY;
  const head = (n) => (m.parts ? `${leadLabel(n)} (${m.parts.map((_, k) => t(PART_KEYS[k])).join(" / ")})` : leadLabel(n));
  const cell = (vals) => (vals ? m.parts ? m.parts.map((_, k) => fmt(vals[k], m.digits, false)).join(" / ") : fmt(vals[0], m.digits, false) : "–");
  return h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, h("th", { class: "row-head" }, t(hourly ? "col_time" : "col_date")), leads.map((n) => h("th", {}, head(n))))),
    h("tbody", {}, shown.map((x) => h("tr", {},
      h("th", { class: "row-head" }, pointLabel(x, bin)),
      leads.map((n) => h("td", {}, cell(byX.get(x)[n])))))));
}

// ---- 확대·축소, 이동 (모든 분할이 같은 기간) ----

function setView(min, max) {
  graph.view = clampView(min, max);
  renderGraphs();
  loadVisible();
}

function attachNavigation(canvas, entry) {
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const xs = entry.chart.scales.x;
    const { min, max } = graph.view;
    const span = max - min;
    const horizontal = e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY);
    if (horizontal) {
      const d = ((e.deltaX || e.deltaY) / xs.width) * span;
      setView(min + d, max + d);
    } else {
      const k = Math.exp(Math.max(-200, Math.min(200, e.deltaY)) * 0.002); // 아래로 굴리면 축소(넓게)
      const at = Math.min(max, Math.max(min, xs.getValueForPixel(e.offsetX)));
      const newSpan = Math.min(span * k, graph.bin.maxDays * DAY); // 최대 기간에서 멈춤 (가운데가 밀리지 않게)
      setView(at - (at - min) * (newSpan / span), at + (max - at) * (newSpan / span));
    }
  }, { passive: false });

  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    drag = { x: e.clientX, view: { ...graph.view }, width: entry.chart.scales.x.width };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const d = (-(e.clientX - drag.x) / drag.width) * (drag.view.max - drag.view.min);
    setView(drag.view.min + d, drag.view.max + d);
  });
  const end = () => { drag = null; };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("mouseleave", () => syncHover(entry.chart, [])); // 다른 분할의 커서도 지움
}

init();
