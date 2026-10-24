/* EcoVolter Lovelace card
 *
 * Design notes (why it is built this way):
 * - The DOM is built once per config and afterwards only updated in place.
 *   Home Assistant pushes `hass` many times per second; rebuilding innerHTML on
 *   every push destroyed buttons between touchstart and click, so taps on
 *   mobile were lost and the slider snapped back.
 * - Shadow DOM keeps the card's CSS from leaking into the rest of the dashboard.
 * - Entities are found via `hass.entities` (available to every user). The old
 *   `config/entity_registry/list` websocket call is admin-only, so the card was
 *   blank for non-admin users (typically family phones).
 * - Optimistic values expire: if the charger does not confirm a change within
 *   a few seconds, the card shows the real state again instead of lying forever.
 */
const VERSION = "0.4.0";
const DOMAIN = "ecovolter";
const MIN_A = 6;
const MAX_A = 16;
const PENDING_MS = 15000;
const STEP_DEBOUNCE_MS = 700;

// translation_key (+ domain) -> card key
const KEY_MAP = {
  "binary_sensor:vehicle_connected": "vehicle_connected",
  "binary_sensor:charging": "charging",
  "sensor:power": "power",
  "sensor:session_energy": "session_energy",
  "sensor:total_energy": "total_energy",
  "sensor:charging_count": "charging_count",
  "sensor:total_charging_time": "total_charging_time",
  "sensor:current_l1": "current_l1",
  "sensor:current_l2": "current_l2",
  "sensor:current_l3": "current_l3",
  "sensor:voltage_l1": "voltage_l1",
  "sensor:voltage_l2": "voltage_l2",
  "sensor:voltage_l3": "voltage_l3",
  "sensor:active_phases": "active_phases",
  "sensor:target_current": "configured_current",
  "switch:charging_enabled": "charging_enabled",
  "switch:three_phase": "three_phase",
  "number:target_current": "target_current",
  // scheduler
  "select:charging_mode": "charging_mode",
  "select:target_type": "target_type",
  "number:target_hours": "target_hours",
  "number:target_energy": "target_energy",
  "number:max_price": "max_price",
  "time:ready_by": "ready_by",
  "select:ready_day": "ready_day",
  "button:charge_again": "charge_again",
  "sensor:charging_plan": "charging_plan",
  "sensor:current_total_price": "current_total_price",
  "binary_sensor:scheduled_now": "scheduled_now",
};
const MODES = ["manual", "cheapest", "price_limit", "low_tariff"];
// unique_id suffixes, used only for the admin websocket fallback
const UID_KEYS = Object.values(KEY_MAP).sort((a, b) => b.length - a.length);

const T = {
  cs: {
    connected: "Vozidlo připojeno", disconnected: "Vozidlo nepřipojeno",
    charging: "nabíjí", idle: "nenabíjí", unavailable: "Nabíječka nedostupná",
    power: "Výkon", session: "Relace", phases: "Fáze", configured: "Nastavený proud",
    charge: "Nabíjení", phase: "3 fáze", current: "Proud",
    phaseCurrents: "Proudy fází", phaseVoltages: "Napětí fází", stats: "Statistiky",
    total: "Celkem", count: "Počet nabíjení", duration: "Doba",
    selectDevice: "Vyberte EcoVolter nabíječku v editoru karty.",
    notFound: "Entity nabíječky nebyly nalezeny.",
    failed: "EcoVolter: příkaz se nezdařil",
    scheduler: "Plánovač", now: "Teď",
    modes: { manual: "Ručně", cheapest: "Nejlevnější", price_limit: "Pod limit", low_tariff: "Jen NT" },
    hours: "Hodiny", kwh: "kWh", readyBy: "Hotovo do", maxPrice: "Max. cena", noLimit: "bez limitu",
    planned: "Naplánováno", start: "start", estimate: "odhad", left: "zbývá", charged: "nabito",
    shortfall: "Do termínu lze naplánovat jen", reached: "Cíl splněn", noPrices: "Chybí ceny elektřiny – nastavte senzor v Možnostech integrace",
    manualInfo: "Nabíjení ovládáte ručně.", lowTariffInfo: "Nabíjí se jen v nízkém tarifu (NT).",
    limitInfo: "Nabíjí se, kdykoli je cena pod limitem.", chargingNow: "nabíjí se podle plánu", waiting: "čeká na levný úsek",
    vt: "VT", currency: "Kč", est: "odhad", until: "do",
    days: { today: "Dnes", tomorrow: "Zítra", day_after: "Pozítří" },
    chargeAgain: "Nabít znovu", doneHint: "Po odpojení a připojení auta se nabíjení samo nespustí.",
    awaitPrices: "část plánu po {t} je odhad – upřesní se po zveřejnění cen na další den (kolem 14:00)",
  },
  en: {
    connected: "Vehicle connected", disconnected: "Vehicle disconnected",
    charging: "charging", idle: "not charging", unavailable: "Charger unavailable",
    power: "Power", session: "Session", phases: "Phases", configured: "Set current",
    charge: "Charging", phase: "3 phases", current: "Current",
    phaseCurrents: "Phase currents", phaseVoltages: "Phase voltages", stats: "Statistics",
    total: "Total", count: "Charging count", duration: "Duration",
    selectDevice: "Select an EcoVolter charger in the card editor.",
    notFound: "Charger entities were not found.",
    failed: "EcoVolter: command failed",
    scheduler: "Scheduler", now: "Now",
    modes: { manual: "Manual", cheapest: "Cheapest", price_limit: "Below limit", low_tariff: "Low tariff" },
    hours: "Hours", kwh: "kWh", readyBy: "Ready by", maxPrice: "Max price", noLimit: "no limit",
    planned: "Planned", start: "start", estimate: "est.", left: "left", charged: "charged",
    shortfall: "Before the deadline only", reached: "Target reached", noPrices: "No electricity prices – set the sensor in the integration options",
    manualInfo: "Charging is controlled manually.", lowTariffInfo: "Charges only in the low tariff (NT).",
    limitInfo: "Charges whenever the price is below the limit.", chargingNow: "charging as planned", waiting: "waiting for a cheap slot",
    vt: "VT", currency: "CZK", est: "estimate", until: "by",
    days: { today: "Today", tomorrow: "Tomorrow", day_after: "Day after" },
    chargeAgain: "Charge again", doneHint: "Re-plugging the car will not start charging on its own.",
    awaitPrices: "part of the plan after {t} is an estimate – refined when tomorrow's prices are published (around 14:00)",
  },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clampA = (v) => Math.max(MIN_A, Math.min(MAX_A, Math.round(Number(v))));
const fmtDur = (min) => {
  min = Math.max(0, Math.round(Number(min) || 0));
  const h = Math.floor(min / 60), m = min % 60;
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
};
const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const isBad = (s) => !s || s.state === "unknown" || s.state === "unavailable";
// Current setpoint of a number entity, or null when it is not a usable number.
const ampOf = (s) => {
  if (isBad(s)) return null;
  const v = clampA(s.state);
  return Number.isFinite(v) ? v : null;
};

function ecovolterDevices(hass) {
  const ids = new Set();
  for (const e of Object.values(hass?.entities || {})) {
    if (e.platform === DOMAIN && e.device_id) ids.add(e.device_id);
  }
  return [...ids].map((id) => {
    const d = hass.devices?.[id];
    return { id, name: d?.name_by_user || d?.name || id };
  });
}

const STYLE = `
:host{display:block}
[hidden]{display:none!important}
ha-card{padding:16px;overflow:hidden;-webkit-tap-highlight-color:transparent}
:host([variant=minimalistic]) ha-card{padding:12px}
.head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:14px}
.title{font-size:20px;font-weight:600;line-height:1.2}
.status{font-size:13px;opacity:.7;margin-top:2px}
.status.bad{color:var(--error-color);opacity:1}
ha-icon{color:var(--state-icon-color)}
ha-icon.active{color:var(--primary-color)}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.phase-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.tile{min-width:0;padding:10px 6px;text-align:center;border-radius:12px;background:var(--secondary-background-color)}
small{display:block;opacity:.65;margin-bottom:4px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
strong{font-size:16px;white-space:nowrap}
.switches{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
button{font:inherit;border:0;border-radius:12px;padding:12px;cursor:pointer;
  background:var(--secondary-background-color);color:var(--primary-text-color);
  touch-action:manipulation;user-select:none;-webkit-user-select:none;transition:background .15s}
button.on{background:var(--primary-color);color:var(--text-primary-color)}
button.pending{opacity:.7}
button:disabled,input:disabled{opacity:.4;cursor:default}
.ctl{display:flex;gap:12px;align-items:center;margin-top:12px;min-height:44px}
.ctl input[type=range]{flex:1;min-width:0;height:32px;margin:0;touch-action:pan-y;accent-color:var(--primary-color)}
.ctl .val{min-width:44px;text-align:right;font-weight:600}
.ctl.buttons{display:grid;grid-template-columns:auto 1fr 1.6fr 1fr;gap:8px}
.amp-btn{padding:8px;font-size:22px;line-height:1}
.amp-value{display:flex;align-items:center;justify-content:center;height:40px;border:1px solid var(--divider-color);border-radius:8px;background:var(--card-background-color)}
.amp-input{width:3ch;min-width:0;text-align:right;border:0;background:transparent;color:var(--primary-text-color);font:inherit;font-weight:600;padding:0;-moz-appearance:textfield}
.amp-input::-webkit-outer-spin-button,.amp-input::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
.amp-value span{font-weight:600;margin-left:3px}
.section{margin:16px 0 8px;font-weight:600}
.msg{padding:18px}
.sched{margin-top:16px;padding-top:14px;border-top:1px solid var(--divider-color)}
.sched-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.sched-head b{font-size:15px}.sched-head span{font-size:13px;opacity:.75}
.modes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
.modes button{padding:10px 4px;font-size:13px}
.params{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.5fr) minmax(0,1fr);gap:8px;margin-top:10px}
.params[hidden]{display:none}
.param{display:grid;gap:4px;min-width:0}.param[hidden]{display:none}
.param small{margin:0}
.seg{display:flex;border-radius:8px;overflow:hidden;border:1px solid var(--divider-color)}
.seg button{flex:1;border-radius:0;padding:0;font-size:11px;height:100%}
.field{display:flex;align-items:center;height:38px;border:1px solid var(--divider-color);border-radius:8px;background:var(--card-background-color);padding:0 8px;gap:4px}
.time-field{justify-content:center;gap:2px}
.time-field select.day{font-weight:500;font-size:14px;margin-right:6px;padding-right:6px;border-right:1px solid var(--divider-color);border-radius:0}
.time-field select{appearance:none;-webkit-appearance:none;border:0;background:transparent;color:var(--primary-text-color);font:inherit;font-weight:600;font-size:16px;padding:0 2px;text-align:center;cursor:pointer;min-width:0}
.field input::placeholder{font-weight:400;opacity:.6;font-size:12px}
.param>small,.param>.seg{height:22px;box-sizing:border-box;display:flex;align-items:center}
.field{overflow:hidden;box-sizing:border-box;width:100%}
.field input{flex:1;min-width:0;width:100%;border:0;background:transparent;color:var(--primary-text-color);font:inherit;font-weight:600;padding:0;text-align:center}
.field span{font-size:12px;opacity:.7}
.sched-status{margin-top:10px;font-size:13px;line-height:1.4;white-space:pre-line}
.again{margin-top:8px;width:100%;padding:10px}
.sched-status.warn{color:var(--warning-color,#e69500)}
.timeline{position:relative;display:flex;align-items:flex-end;gap:1px;height:72px;margin-top:10px;touch-action:pan-y}
.timeline .bar{flex:1;min-width:1px;border-radius:2px 2px 0 0;background:var(--disabled-text-color,#bbb);opacity:.55;position:relative}
.timeline .bar.sel{background:var(--primary-color);opacity:1}
.timeline .bar.vt::after{content:"";position:absolute;left:0;right:0;bottom:-5px;height:3px;background:var(--error-color,#db4437);opacity:.6}
.timeline .bar.est{background:repeating-linear-gradient(135deg,var(--disabled-text-color,#bbb) 0 3px,transparent 3px 6px);opacity:.5}
.timeline .bar.est.sel{background:repeating-linear-gradient(135deg,var(--primary-color) 0 3px,transparent 3px 6px);opacity:.9}
.tl-axis{display:flex;justify-content:space-between;font-size:11px;opacity:.65;margin-top:7px}
.tl-info{font-size:12px;opacity:.8;min-height:16px;margin-top:4px;text-align:center}
.limit-line{position:absolute;left:0;right:0;border-top:1px dashed var(--error-color,#db4437);pointer-events:none}
@media(max-width:600px){
  ha-card{padding:14px}.title{font-size:19px}
  .grid,.phase-grid,.switches{gap:6px}
  small{font-size:11px}strong{font-size:15px}
  .switches button{padding:12px 6px;font-size:14px}
  .modes button{font-size:12px;padding:10px 2px}
  .params{grid-template-columns:minmax(0,1fr) minmax(0,1.4fr)}
  #pMax{grid-column:1 / -1}
  .params #pMax:only-of-type{grid-column:auto}
}
@media(max-width:380px){.grid,.modes{grid-template-columns:repeat(2,minmax(0,1fr))}.params{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;

class EcoVolterCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._ents = null; // card key -> entity_id
    this._pending = {}; // card key -> {value, until}
    this._dragging = false;
    this._editing = false;
    this._stepTimer = null;
  }

  static getConfigElement() { return document.createElement("ecovolter-card-editor"); }

  static getStubConfig(hass) {
    const d = ecovolterDevices(hass)[0];
    return { variant: "compact", language: "cs", current_control: "slider", ...(d ? { device: d.id } : {}) };
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    const old = this._config;
    this._config = { variant: "compact", language: "cs", current_control: "slider", ...config };
    if (!old || old.device !== this._config.device) this._ents = null;
    this._built = false;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._ents && this._config?.device) this._resolve();
    if (!this._built) this._render();
    else this._update();
  }
  get hass() { return this._hass; }

  getCardSize() {
    const v = this._config?.variant;
    return v === "detailed" ? 10 : v === "minimalistic" ? 4 : 6;
  }

  get _t() { return T[this._config?.language === "en" ? "en" : "cs"]; }

  /* ---------- entity lookup ---------- */

  _resolve() {
    const hass = this._hass, device = this._config.device;
    const ents = {};
    for (const e of Object.values(hass.entities || {})) {
      if (e.device_id !== device || e.platform !== DOMAIN) continue;
      const key = KEY_MAP[e.entity_id.split(".")[0] + ":" + e.translation_key];
      if (key) ents[key] = e.entity_id;
    }
    if (Object.keys(ents).length) {
      this._ents = ents;
      this._built = false;
      return;
    }
    // Fallback for older HA versions without translation_key in hass.entities.
    if (this._resolving) return;
    if (!hass.user?.is_admin) { this._ents = {}; this._built = false; return; }
    this._resolving = true;
    hass
      .callWS({ type: "config/entity_registry/list" })
      .then((list) => {
        const found = {};
        for (const e of list) {
          if (e.device_id !== device || e.disabled_by) continue;
          const key = UID_KEYS.find((k) => (e.unique_id || "").endsWith("_" + k));
          if (key && !found[key]) found[key] = e.entity_id;
        }
        this._ents = found;
        this._built = false;
        this._render();
      })
      .catch((err) => console.warn("EcoVolter card: entity lookup failed", err))
      .finally(() => { this._resolving = false; });
  }

  _s(key) {
    const id = this._ents?.[key];
    return id ? this._hass?.states?.[id] : undefined;
  }

  /* ---------- pending (optimistic) values ---------- */

  _setPending(key, value) { this._pending[key] = { value, until: Date.now() + PENDING_MS }; }

  _effective(key, actual) {
    const p = this._pending[key];
    if (!p) return actual;
    if (Date.now() > p.until || String(actual) === String(p.value)) {
      delete this._pending[key];
      return actual;
    }
    return p.value;
  }

  /* ---------- formatting ---------- */

  _fmt(key) {
    const s = this._s(key);
    if (isBad(s)) return "—";
    const unit = s.attributes.unit_of_measurement ? " " + s.attributes.unit_of_measurement : "";
    const n = Number(s.state);
    if (!Number.isFinite(n)) return s.state + unit;
    if (key === "total_charging_time") {
      const m = Math.round(n / 60);
      return Math.floor(m / 60) + " h " + (m % 60) + " min";
    }
    if (key === "charging_count" || key === "active_phases") return String(Math.round(n));
    if (key === "configured_current" || key === "target_current") return Math.round(n) + unit;
    if (key.startsWith("voltage")) return n.toFixed(0) + unit;
    return n.toFixed(2) + unit;
  }

  /* ---------- build DOM once ---------- */

  _render() {
    const root = this.shadowRoot;
    const c = this._config;
    if (!c) return;
    const t = this._t;
    if (!c.device) {
      root.innerHTML = `<style>${STYLE}</style><ha-card><div class="msg">${esc(t.selectDevice)}</div></ha-card>`;
      return;
    }
    if (!this._hass || !this._ents) return;
    if (!Object.keys(this._ents).length) {
      root.innerHTML = `<style>${STYLE}</style><ha-card><div class="msg">${esc(t.notFound)}</div></ha-card>`;
      return;
    }

    this.setAttribute("variant", c.variant);
    const minimal = c.variant === "minimalistic";
    const tile = (key, label) => `<div class="tile"><small>${esc(label)}</small><strong data-v="${key}">—</strong></div>`;

    let detail = "";
    if (c.variant === "detailed") {
      detail =
        `<div class="section">${esc(t.phaseCurrents)}</div><div class="phase-grid">` +
        [1, 2, 3].map((n) => tile("current_l" + n, "L" + n)).join("") +
        `</div><div class="section">${esc(t.phaseVoltages)}</div><div class="phase-grid">` +
        [1, 2, 3].map((n) => tile("voltage_l" + n, "L" + n)).join("") +
        `</div><div class="section">${esc(t.stats)}</div><div class="phase-grid">` +
        tile("total_energy", t.total) + tile("charging_count", t.count) + tile("total_charging_time", t.duration) +
        `</div>`;
    }

    const control =
      c.current_control === "buttons"
        ? `<div class="ctl buttons"><span>${esc(t.current)}</span>
             <button class="amp-btn" id="minus" aria-label="-1 A">−</button>
             <label class="amp-value"><input id="ampInput" class="amp-input" type="number" inputmode="numeric" min="${MIN_A}" max="${MAX_A}" step="1"><span>A</span></label>
             <button class="amp-btn" id="plus" aria-label="+1 A">+</button></div>`
        : `<div class="ctl"><span>${esc(t.current)}</span>
             <input id="slider" type="range" min="${MIN_A}" max="${MAX_A}" step="1">
             <span class="val" id="sliderVal">— A</span></div>`;

    root.innerHTML = `<style>${STYLE}</style><ha-card>
      <div class="head"><div>
        <div class="title">${esc(c.name || "EcoVolter")}</div>
        <div class="status" id="status"></div>
      </div><ha-icon id="icon" icon="mdi:ev-station"></ha-icon></div>
      ${minimal ? "" : `<div class="grid">${tile("power", t.power)}${tile("session_energy", t.session)}${tile("active_phases", t.phases)}${tile("configured_current", t.configured)}</div>`}
      <div class="switches">
        <button id="charge">⚡ ${esc(t.charge)}</button>
        <button id="phase">〰 ${esc(t.phase)}</button>
      </div>
      ${control}
      ${this._schedulerHtml()}
      ${detail}
    </ha-card>`;

    this._bind();
    this._built = true;
    this._update();
  }

  _showScheduler() {
    if (!this._ents?.charging_mode) return false;
    const opt = this._config.scheduler;
    return opt === undefined ? this._config.variant !== "minimalistic" : opt !== false;
  }

  _schedulerHtml() {
    if (!this._showScheduler()) return "";
    const t = this._t;
    const field = (id, unit, step, min, max) =>
      // type=text + inputmode=decimal: accepts "4,5" on Czech keyboards (type=number drops the comma)
      `<label class="field"><input id="${id}" type="text" inputmode="decimal" autocomplete="off" data-step="${step}" data-min="${min}" data-max="${max}"><span>${unit}</span></label>`;
    return `<div class="sched">
      <div class="sched-head"><b>${esc(t.scheduler)}</b><span id="priceNow"></span></div>
      <div class="modes">${MODES.map((m) => `<button data-mode="${m}">${esc(t.modes[m])}</button>`).join("")}</div>
      <div class="params" id="params">
        <div class="param" id="pTarget"><div class="seg"><button data-tt="hours">${esc(t.hours)}</button><button data-tt="energy">${esc(t.kwh)}</button></div>
          <span id="tgtHoursWrap">${field("tgtHours", "h", "0.25", 0, 24)}</span>
          <span id="tgtEnergyWrap">${field("tgtEnergy", "kWh", "1", 0, 150)}</span></div>
        <div class="param" id="pReady"><small>${esc(t.readyBy)}</small><div class="field time-field"><select id="readyD" class="day">${["today", "tomorrow", "day_after"].map((d) => `<option value="${d}">${esc(t.days[d])}</option>`).join("")}</select><select id="readyH" aria-label="hod">${Array.from({ length: 24 }, (_, h) => `<option value="${h}">${String(h).padStart(2, "0")}</option>`).join("")}</select><b>:</b><select id="readyM" aria-label="min">${[0, 15, 30, 45].map((m) => `<option value="${m}">${String(m).padStart(2, "0")}</option>`).join("")}</select></div></div>
        <div class="param" id="pMax"><small>${esc(t.maxPrice)}</small>${field("maxPrice", t.currency + "/kWh", "0.1", 0, 30).replace("<input ", `<input placeholder="${esc(t.noLimit)}" `)}</div>
      </div>
      <div class="sched-status" id="schedStatus"></div>
      <button id="chargeAgain" class="again" hidden>↻ ${esc(t.chargeAgain)}</button>
      <div class="timeline" id="timeline"></div>
      <div class="tl-axis" id="tlAxis"></div>
      <div class="tl-info" id="tlInfo"></div>
    </div>`;
  }

  _bindScheduler() {
    const root = this.shadowRoot;
    if (!root.getElementById("timeline")) return;
    root.querySelectorAll("[data-mode]").forEach((b) =>
      b.addEventListener("click", () => this._setSelect("charging_mode", b.dataset.mode)));
    root.querySelectorAll("[data-tt]").forEach((b) =>
      b.addEventListener("click", () => this._setSelect("target_type", b.dataset.tt)));
    const bindNum = (id, key) => {
      const el = root.getElementById(id);
      el.addEventListener("focus", () => { this._editingField = id; });
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } });
      el.addEventListener("blur", () => { this._editingField = null; this._setNumber(key, el.value); });
    };
    bindNum("tgtHours", "target_hours");
    bindNum("tgtEnergy", "target_energy");
    bindNum("maxPrice", "max_price");
    // Native <select>s instead of <input type=time>: one value per choice (no
    // half-typed times sent to HA) and reliable pickers in the Companion app.
    const rh = root.getElementById("readyH"), rm = root.getElementById("readyM");
    const commit = () => this._setTime(`${String(rh.value).padStart(2, "0")}:${String(rm.value).padStart(2, "0")}`);
    for (const sel of [rh, rm]) {
      sel.addEventListener("focus", () => { this._editingField = "readyBy"; });
      sel.addEventListener("change", () => { this._editingField = null; commit(); });
      sel.addEventListener("blur", () => { this._editingField = null; });
    }
    const rd = root.getElementById("readyD");
    rd.addEventListener("focus", () => { this._editingField = "readyD"; });
    rd.addEventListener("blur", () => { this._editingField = null; });
    rd.addEventListener("change", () => { this._editingField = null; this._setSelect("ready_day", rd.value); });
    const tl = root.getElementById("timeline");
    const info = (e) => {
      const bar = e.target.closest?.(".bar");
      if (bar) root.getElementById("tlInfo").textContent = bar.dataset.info;
    };
    root.getElementById("chargeAgain").addEventListener("click", () => {
      const b = this._s("charge_again");
      if (b) this._call("button", "press", { entity_id: b.entity_id }, "charge_again");
    });
    tl.addEventListener("pointermove", info);
    tl.addEventListener("pointerdown", info);
  }

  _updateScheduler() {
    const root = this.shadowRoot;
    if (!root.getElementById("timeline")) return;
    const t = this._t;
    const set = (el, txt) => { if (el && el.textContent !== txt) el.textContent = txt; };
    const modeS = this._s("charging_mode");
    const mode = this._effective("charging_mode", modeS?.state);
    root.querySelectorAll("[data-mode]").forEach((b) => {
      b.classList.toggle("on", b.dataset.mode === mode);
      b.classList.toggle("pending", !!this._pending.charging_mode && b.dataset.mode === mode);
    });
    const tt = this._effective("target_type", this._s("target_type")?.state) || "hours";
    root.querySelectorAll("[data-tt]").forEach((b) => b.classList.toggle("on", b.dataset.tt === tt));

    root.getElementById("params").hidden = !(mode === "cheapest" || mode === "price_limit");
    root.getElementById("pTarget").hidden = mode !== "cheapest";
    root.getElementById("pReady").hidden = mode !== "cheapest";
    root.getElementById("tgtHoursWrap").hidden = tt !== "hours";
    root.getElementById("tgtEnergyWrap").hidden = tt !== "energy";

    const syncNum = (id, key) => {
      const el = root.getElementById(id), s = this._s(key);
      if (this._editingField === id || isBad(s)) return;
      const num = Number(this._effective(key, Number(s.state)));
      const v = key === "max_price" && num === 0 ? "" : String(num).replace(".", this._config.language === "en" ? "." : ",");
      if (el.value !== v) el.value = v;
    };
    syncNum("tgtHours", "target_hours");
    syncNum("tgtEnergy", "target_energy");
    syncNum("maxPrice", "max_price");
    const rdS = this._s("ready_day"), rd = root.getElementById("readyD");
    rd.hidden = !rdS;
    if (rdS && this._editingField !== "readyD") {
      const v = this._effective("ready_day", rdS.state);
      if (rd.value !== v) rd.value = v;
    }
    const rs = this._s("ready_by");
    if (this._editingField !== "readyBy" && !isBad(rs)) {
      const [hh, mm] = String(this._effective("ready_by", rs.state.slice(0, 5))).split(":").map(Number);
      const rh = root.getElementById("readyH"), rm = root.getElementById("readyM");
      // minutes set elsewhere (e.g. 06:20 from an automation) are shown as an extra option
      if (Number.isFinite(mm) && ![...rm.options].some((o) => Number(o.value) === mm)) {
        rm.add(new Option(String(mm).padStart(2, "0"), String(mm)));
      }
      if (Number.isFinite(hh) && rh.value !== String(hh)) rh.value = String(hh);
      if (Number.isFinite(mm) && rm.value !== String(mm)) rm.value = String(mm);
    }

    const priceS = this._s("current_total_price");
    set(root.getElementById("priceNow"), isBad(priceS) ? "" :
      `${t.now} ${Number(priceS.state).toFixed(2)} ${t.currency}/kWh`);

    const plan = this._s("charging_plan")?.attributes || {};
    const slots = Array.isArray(plan.slots) ? plan.slots : [];
    const status = root.getElementById("schedStatus");
    let txt = "", warn = false;
    if (mode === "manual") txt = t.manualInfo;
    else if (mode === "low_tariff") txt = t.lowTariffInfo + (this._s("scheduled_now")?.state === "on" ? ` · ${t.chargingNow}` : "");
    else if (!slots.length) { txt = t.noPrices; warn = true; }
    else if (mode === "price_limit") txt = t.limitInfo + (this._s("scheduled_now")?.state === "on" ? ` · ${t.chargingNow}` : "");
    else if (plan.reason === "target_reached" || plan.finished) txt = `✅ ${t.reached} · ${t.charged} ${fmtDur(plan.delivered_minutes)}` + (plan.delivered_kwh ? ` / ${plan.delivered_kwh} kWh` : "") + `\n${t.doneHint}`;
    else {
      const startS = this._s("charging_plan");
      const start = !isBad(startS) ? new Date(startS.state) : null;
      const deadline = plan.deadline ? hhmm(new Date(plan.deadline)) : "";
      if (!plan.complete) { warn = true; txt = `⚠ ${t.shortfall} ${fmtDur(plan.planned_minutes)} / ${fmtDur(plan.needed_minutes)} (${t.readyBy.toLowerCase()} ${deadline})`; }
      else txt = `${t.planned} ${fmtDur(plan.planned_minutes)}`;
      if (plan.complete && plan.deadline) {
        txt += this._config.language === "en"
          ? ` ${t.until} ${this._dayWord(new Date(plan.deadline))} ${deadline}`
          : ` · ${this._dayWord(new Date(plan.deadline))} ${t.until} ${deadline}`;
      }
      if (this._s("scheduled_now")?.state === "on") txt += ` · ${t.chargingNow}`;
      else if (start) txt += ` · ${t.start} ${hhmm(start)}`;
      if (plan.estimated_cost) txt += ` · ${t.estimate} ${Math.round(plan.estimated_cost)} ${t.currency}`;
      if (plan.delivered_minutes) txt += ` · ${t.charged} ${fmtDur(plan.delivered_minutes)}`;
      if (plan.waiting_for_prices && plan.prices_until) txt += `\nℹ ${t.awaitPrices.replace("{t}", hhmm(new Date(plan.prices_until)))}`;
    }
    set(status, txt);
    status.classList.toggle("warn", warn);
    root.getElementById("chargeAgain").hidden = !(mode === "cheapest" && plan.finished && this._s("charge_again"));

    // Rebuild the bars only when the plan actually changes (minutes matter for "past").
    const sig = JSON.stringify([slots, mode, plan.max_price, Math.floor(Date.now() / 60000)]);
    if (sig === this._tlSig) return;
    this._tlSig = sig;
    const tl = root.getElementById("timeline"), axis = root.getElementById("tlAxis");
    const showTl = mode !== "manual" && slots.length > 0;
    tl.hidden = axis.hidden = root.getElementById("tlInfo").hidden = !showTl;
    if (!showTl) return;
    const now = Date.now();
    const deadlineMs = plan.deadline ? Date.parse(plan.deadline) : Infinity;
    const shown = slots.filter(([st], i) => {
      const end = i + 1 < slots.length ? Date.parse(slots[i + 1][0]) : Date.parse(st) + 3600e3;
      return end > now && (mode !== "cheapest" || Date.parse(st) < Math.max(deadlineMs, now + 12 * 3600e3));
    });
    const prices = shown.map((x) => x[1]);
    const max = Math.max(...prices, plan.max_price || 0, 0.01);
    const min = Math.min(0, ...prices);
    const h = (p) => Math.max(3, ((p - min) / (max - min)) * 100);
    tl.innerHTML = shown.map(([st, price, sel, vt, est]) => {
      const d = new Date(st);
      const selOn = sel && mode === "cheapest";
      const info = `${hhmm(d)} · ${est ? "~" : ""}${Number(price).toFixed(2)} ${t.currency}/kWh${vt ? " · " + t.vt : ""}${est ? " (" + t.est + ")" : ""}`;
      return `<div class="bar${selOn ? " sel" : ""}${vt ? " vt" : ""}${est ? " est" : ""}" style="height:${h(price)}%" data-info="${esc(info)}"></div>`;
    }).join("") + (mode === "price_limit" && plan.max_price ? `<div class="limit-line" style="bottom:${h(plan.max_price)}%"></div>` : "");
    const first = shown[0] ? new Date(shown[0][0]) : null, last = shown.at(-1) ? new Date(shown.at(-1)[0]) : null;
    const mid = shown[Math.floor(shown.length / 2)] ? new Date(shown[Math.floor(shown.length / 2)][0]) : null;
    axis.innerHTML = [first, mid, last].map((d) => `<span>${d ? hhmm(d) : ""}</span>`).join("");
  }

  _dayWord(d) {
    const t = this._t, today = new Date();
    const diff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 864e5);
    const w = diff === 0 ? t.days.today : diff === 1 ? t.days.tomorrow : diff === 2 ? t.days.day_after : d.toLocaleDateString();
    return w.toLowerCase();
  }

  _setSelect(key, option) {
    const s = this._s(key);
    if (!s || this._effective(key, s.state) === option) return;
    this._setPending(key, option);
    this._update();
    this._call("select", "select_option", { entity_id: s.entity_id, option }, key);
  }

  _setNumber(key, raw) {
    const s = this._s(key);
    if (key === "max_price" && String(raw).trim() === "") raw = "0"; // empty = no limit
    const n = Number(String(raw).replace(",", "."));
    if (!s || raw === "" || !Number.isFinite(n)) { this._update(); return; }
    const min = Number(s.attributes.min ?? 0), max = Number(s.attributes.max ?? 1e9);
    const v = Math.max(min, Math.min(max, n));
    if (v === Number(s.state)) { this._update(); return; }
    this._setPending(key, v);
    this._update();
    this._call("number", "set_value", { entity_id: s.entity_id, value: v }, key);
  }

  _setTime(value) {
    const s = this._s("ready_by");
    if (!s || !/^\d{2}:\d{2}/.test(value || "")) return;
    const hm = value.slice(0, 5);
    if (hm === String(s.state).slice(0, 5)) return;
    this._setPending("ready_by", hm);
    this._call("time", "set_value", { entity_id: s.entity_id, time: hm + ":00" }, "ready_by");
  }

  _bind() {
    this._bindScheduler();
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("charge").addEventListener("click", () => this._toggle("charging_enabled"));
    $("phase").addEventListener("click", () => this._toggle("three_phase"));

    const slider = $("slider");
    if (slider) {
      const start = () => { this._dragging = true; this._dragAt = Date.now(); };
      const stop = () => { this._dragging = false; };
      slider.addEventListener("pointerdown", start);
      slider.addEventListener("touchstart", start, { passive: true });
      slider.addEventListener("input", (e) => {
        start();
        $("sliderVal").textContent = e.target.value + " A";
      });
      slider.addEventListener("change", (e) => { stop(); this._sendCurrent(e.target.value); });
      // Safety nets: never let the card stay "frozen" in drag mode.
      for (const ev of ["pointerup", "pointercancel", "touchend", "touchcancel", "blur"]) {
        slider.addEventListener(ev, () => setTimeout(stop, 50), { passive: true });
      }
    }

    const input = $("ampInput");
    if (input) {
      input.addEventListener("focus", () => { this._editing = true; input.select?.(); });
      input.addEventListener("blur", () => {
        this._editing = false;
        this._commitInput(input);
      });
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      });
      $("minus").addEventListener("click", () => this._step(-1));
      $("plus").addEventListener("click", () => this._step(1));
    }
  }

  /* ---------- update values in place ---------- */

  _update() {
    if (!this._built || !this._hass) return;
    const root = this.shadowRoot;
    const t = this._t;
    const set = (el, txt) => { if (el && el.textContent !== txt) el.textContent = txt; };

    root.querySelectorAll("[data-v]").forEach((el) => set(el, this._fmt(el.dataset.v)));

    const conn = this._s("vehicle_connected");
    const chg = this._s("charging");
    const unavailable = isBad(conn) && isBad(this._s("charging_enabled"));
    const status = root.getElementById("status");
    let txt;
    if (unavailable) txt = t.unavailable;
    else {
      txt = (conn?.state === "on" ? "🟢 " + t.connected : "⚪ " + t.disconnected) +
        " · " + (chg?.state === "on" ? t.charging : t.idle);
      if (this._config.variant === "minimalistic") {
        txt += ` · ${t.phases}: ${this._fmt("active_phases")} · ${t.power}: ${this._fmt("power")} · ${t.session}: ${this._fmt("session_energy")}`;
      }
    }
    set(status, txt);
    status.classList.toggle("bad", unavailable);
    root.getElementById("icon")?.classList.toggle("active", chg?.state === "on");

    for (const [id, key] of [["charge", "charging_enabled"], ["phase", "three_phase"]]) {
      const btn = root.getElementById(id);
      const s = this._s(key);
      const on = this._effective(key, s?.state === "on");
      btn.classList.toggle("on", !!on);
      btn.classList.toggle("pending", !!this._pending[key]);
      btn.disabled = isBad(s);
    }

    const num = this._s("target_current");
    const actual = ampOf(num);
    const amp = this._effective("target_current", actual);
    const disabled = actual == null;

    const slider = root.getElementById("slider");
    if (slider) {
      slider.disabled = disabled;
      // Do not fight the user's finger. Drag mode expires after 10 s as a fallback.
      if (this._dragging && Date.now() - this._dragAt > 10000) this._dragging = false;
      if (!this._dragging && amp != null) {
        if (slider.value !== String(amp)) slider.value = String(amp);
        set(root.getElementById("sliderVal"), amp + " A");
      }
    }
    const input = root.getElementById("ampInput");
    if (input) {
      input.disabled = disabled;
      root.getElementById("minus").disabled = disabled;
      root.getElementById("plus").disabled = disabled;
      if (!this._editing && amp != null && input.value !== String(amp)) input.value = String(amp);
    }
    this._updateScheduler();
  }

  /* ---------- actions ---------- */

  _notify(err) {
    console.error("EcoVolter card:", err);
    this.dispatchEvent(new CustomEvent("hass-notification", {
      detail: { message: `${this._t.failed}: ${err?.message || err}` },
      bubbles: true, composed: true,
    }));
  }

  async _call(domain, service, data, pendingKey) {
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      delete this._pending[pendingKey];
      this._update();
      this._notify(err);
    }
  }

  _toggle(key) {
    const s = this._s(key);
    if (isBad(s)) return;
    const turnOn = !this._effective(key, s.state === "on");
    this._setPending(key, turnOn);
    this._update();
    this._call("switch", turnOn ? "turn_on" : "turn_off", { entity_id: s.entity_id }, key);
  }

  _sendCurrent(value) {
    const s = this._s("target_current");
    const actual = ampOf(s);
    if (actual == null) return;
    const v = clampA(value);
    if (!Number.isFinite(v)) return;
    this._setPending("target_current", v);
    this._update();
    if (v === actual) return; // nothing to send
    this._call("number", "set_value", { entity_id: s.entity_id, value: v }, "target_current");
  }

  _step(delta) {
    const s = this._s("target_current");
    const actual = ampOf(s);
    if (actual == null) return;
    const cur = this._effective("target_current", actual);
    const v = clampA(cur + delta);
    this._setPending("target_current", v);
    this._update();
    // Debounce: tapping + three times sends one request, not three.
    clearTimeout(this._stepTimer);
    this._stepTimer = setTimeout(() => this._sendCurrent(v), STEP_DEBOUNCE_MS);
  }

  _commitInput(input) {
    const n = Number(input.value);
    if (!input.value || !Number.isFinite(n)) { this._update(); return; }
    const v = clampA(n);
    input.value = String(v);
    this._sendCurrent(v);
  }
}

class EcoVolterCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { variant: "compact", language: "cs", current_control: "slider", ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sig = ecovolterDevices(hass).map((d) => d.id + d.name).join("|");
    if (first || sig !== this._sig) { this._sig = sig; this._render(); }
  }

  _fire(key, value) {
    if (value == null || this._config[key] === value) return;
    this._config = { ...this._config, [key]: value };
    if (key === "name" && !value) delete this._config.name;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
  }

  _render() {
    if (!this._config) return;
    // Do not re-render while the user is typing into the name field.
    if (this.shadowRoot?.activeElement?.id === "n") return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const c = this._config;
    const ds = this._hass ? ecovolterDevices(this._hass) : [];
    const opt = (v, label, sel) => `<option value="${esc(v)}" ${sel ? "selected" : ""}>${esc(label)}</option>`;
    this.shadowRoot.innerHTML = `<style>
      .w{display:grid;gap:14px}.field{display:grid;gap:6px}
      .label{font-size:12px;color:var(--secondary-text-color)}
      select,input{box-sizing:border-box;width:100%;height:48px;padding:0 12px;border:1px solid var(--divider-color);border-radius:4px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit}
    </style><div class="w">
      <label class="field"><span class="label">Nabíječka / Charger</span><select id="d">
        ${opt("", "Vyberte EcoVolter…", !c.device)}
        ${ds.map((d) => opt(d.id, d.name, d.id === c.device)).join("")}
      </select></label>
      <label class="field"><span class="label">Varianta / Variant</span><select id="v">
        ${opt("minimalistic", "Minimalistic", c.variant === "minimalistic")}
        ${opt("compact", "Compact", c.variant === "compact")}
        ${opt("detailed", "Detailed", c.variant === "detailed")}
      </select></label>
      <label class="field"><span class="label">Ovládání proudu / Current control</span><select id="c">
        ${opt("slider", "Slider", c.current_control !== "buttons")}
        ${opt("buttons", "− / hodnota / +", c.current_control === "buttons")}
      </select></label>
      <label class="field"><span class="label">Plánovač / Scheduler</span><select id="s">
        ${opt("auto", "Automaticky / Auto", c.scheduler === undefined)}
        ${opt("show", "Zobrazit / Show", c.scheduler === true)}
        ${opt("hide", "Skrýt / Hide", c.scheduler === false)}
      </select></label>
      <label class="field"><span class="label">Jazyk / Language</span><select id="l">
        ${opt("cs", "Čeština", c.language !== "en")}
        ${opt("en", "English", c.language === "en")}
      </select></label>
      <label class="field"><span class="label">Název / Name</span><input id="n" value="${esc(c.name || "")}" placeholder="EcoVolter"></label>
    </div>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("d").addEventListener("change", (e) => this._fire("device", e.target.value));
    $("v").addEventListener("change", (e) => this._fire("variant", e.target.value));
    $("c").addEventListener("change", (e) => this._fire("current_control", e.target.value));
    $("l").addEventListener("change", (e) => this._fire("language", e.target.value));
    $("s").addEventListener("change", (e) => {
      const v = e.target.value;
      const next = { ...this._config };
      if (v === "auto") delete next.scheduler; else next.scheduler = v === "show";
      this._config = next;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: next }, bubbles: true, composed: true }));
    });
    $("n").addEventListener("change", (e) => this._fire("name", e.target.value));
  }
}

if (!customElements.get("ecovolter-card")) customElements.define("ecovolter-card", EcoVolterCard);
if (!customElements.get("ecovolter-card-editor")) customElements.define("ecovolter-card-editor", EcoVolterCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "ecovolter-card")) {
  window.customCards.push({
    type: "ecovolter-card",
    name: "EcoVolter",
    description: "EcoVolter charger card with device selection",
    preview: true,
    documentationURL: "https://github.com/itsit-cz/HA-ecovolter",
  });
}
console.info("EcoVolter Card " + VERSION);
