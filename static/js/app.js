"use strict";

// ----- helper -------------------------------------------------------------
async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (res.status === 401) { window.location = "/login"; throw new Error("unauth"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || ("Errore " + res.status));
  return data;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function money(p, cur) { return Math.round(p) + " " + esc(cur || "EUR"); }

// Data ISO (AAAA-MM-GG) -> gg-mm-aaaa per la UI. Lascia intatto il resto.
function fmtDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s == null ? "" : s));
  return m ? m[3] + "-" + m[2] + "-" + m[1] : (s == null ? "" : String(s));
}

// ----- DASHBOARD (ricerca) ------------------------------------------------
function initDashboard() {
  const form = document.getElementById("searchForm");
  const mode = document.getElementById("mode");
  const results = document.getElementById("results");
  const status = document.getElementById("searchStatus");

  const show = (name, on) => {
    const el = document.querySelector('[data-field="' + name + '"]');
    if (el) el.hidden = !on;
  };
  const applyMode = () => {
    const m = mode.value;
    show("destination", m !== "explore");
    show("swap", m !== "explore");
    show("departDate", m === "search");
    show("returnDate", m === "search");
    show("flex", m === "search");
    show("adults", m === "search");
    show("maxPrice", m === "explore");
  };
  mode.addEventListener("change", applyMode);
  applyMode();

  // Inverte i codici di partenza e arrivo.
  const swapBtn = document.getElementById("swapBtn");
  if (swapBtn) swapBtn.addEventListener("click", () => {
    const o = document.getElementById("origin");
    const d = document.getElementById("destination");
    const tmp = o.value; o.value = d.value; d.value = tmp;
  });

  // ---- Filtri e ordinamento (solo modalità "Tratta singola") -------------
  const filtersEl = document.getElementById("searchFilters");
  let lastOffers = [];        // ultime offerte grezze dalla ricerca
  let lastProviders = [];

  // Fascia oraria di una partenza "HH:MM" -> chiave fascia.
  const BANDS = { any: [0, 24], morning: [5, 12], afternoon: [12, 18],
                  evening: [18, 24], night: [0, 5] };
  const bandOf = (hhmm, key) => {
    if (key === "any") return true;
    if (!hhmm) return false;               // senza orario: escluso se filtri per fascia
    const h = parseInt(hhmm.slice(0, 2), 10);
    const [lo, hi] = BANDS[key] || [0, 24];
    return h >= lo && h < hi;
  };
  const stopBucket = (s) => (s == null ? null : (s >= 2 ? "2" : String(s)));

  // Intervallo orario manuale (slider a due maniglie), in minuti.
  const SL_MIN = 0, SL_MAX = 1410, SL_STEP = 30, SL_GAP = 30;   // 00:00–23:30
  const toHHMM = (min) => String(Math.floor(min / 60)).padStart(2, "0")
    + ":" + String(min % 60).padStart(2, "0");
  const toMin = (hhmm) => parseInt(hhmm.slice(0, 2), 10) * 60 + parseInt(hhmm.slice(3, 5), 10);
  const sliderActive = () => {
    const f = document.getElementById("fFrom"), t = document.getElementById("fTo");
    return f && t && (+f.value > SL_MIN || +t.value < SL_MAX);
  };

  function buildFilters(offers) {
    document.getElementById("resultsCol").className = "col-12 col-lg-9";

    // Compagnie lette DINAMICAMENTE dai risultati (ordinate), checkbox verticali.
    const carriers = [...new Set(offers.flatMap(o => o.carriers || []))].sort();
    const check = (id, value, label, cls) =>
      '<div class="form-check"><input class="form-check-input ' + cls + '" type="checkbox" id="'
      + id + '" value="' + esc(value) + '" checked>'
      + '<label class="form-check-label" for="' + id + '">' + label + "</label></div>";
    const carList = carriers.length
      ? carriers.map((c, i) => check("car_" + i, c, esc(c), "f-car")).join("")
      : '<span class="text-muted small">nessuna compagnia indicata</span>';

    const sec = (title, extra, body) =>
      '<div class="f-section">'
      + '<div class="d-flex align-items-center justify-content-between mb-2">'
      + '<span class="f-title text-uppercase text-muted fw-semibold">' + title + "</span>"
      + (extra || "") + "</div>" + body + "</div>";

    filtersEl.innerHTML =
        '<div class="filters-card card card-body shadow-sm">'
      + '<div class="d-flex align-items-center justify-content-between">'
      + '<button type="button" class="btn btn-sm btn-light fw-semibold d-inline-flex align-items-center gap-1 flex-grow-1 text-start" id="fToggle" aria-expanded="true">'
      + '<span class="flex-grow-1">⚙︎ Filtri e ordinamento</span>'
      + '<span class="badge rounded-pill text-bg-primary d-none" id="fCount"></span>'
      + '<span id="fChevron">▾</span></button></div>'
      + '<div id="fBody" class="pt-3">'

      + sec("Ordina per", "",
            '<select id="fSort" class="form-select form-select-sm">'
          + '<option value="price">Prezzo</option>'
          + '<option value="depart">Orario partenza</option>'
          + '<option value="arrive">Orario arrivo</option></select>')

      + sec("Scali", "",
            check("st0", "0", "Diretto", "f-stop")
          + check("st1", "1", "1 scalo", "f-stop")
          + check("st2", "2", "2+ scali", "f-stop"))

      + sec("Orario partenza", "",
            '<select id="fBand" class="form-select form-select-sm mb-3">'
          + '<option value="any">Qualsiasi orario</option>'
          + '<option value="morning">Mattina (05–12)</option>'
          + '<option value="afternoon">Pomeriggio (12–18)</option>'
          + '<option value="evening">Sera (18–24)</option>'
          + '<option value="night">Notte (00–05)</option></select>'
          + '<div class="small text-muted mb-1">oppure intervallo manuale</div>'
          + '<div class="dual-range mb-1"><div class="track"></div><div class="range" id="fRangeFill"></div>'
          + '<input type="range" id="fFrom" min="' + SL_MIN + '" max="' + SL_MAX + '" step="' + SL_STEP + '" value="' + SL_MIN + '" aria-label="dalle">'
          + '<input type="range" id="fTo" min="' + SL_MIN + '" max="' + SL_MAX + '" step="' + SL_STEP + '" value="' + SL_MAX + '" aria-label="alle"></div>'
          + '<div class="d-flex justify-content-between small">'
          + '<span>dalle <strong id="fFromLbl">00:00</strong></span>'
          + '<span>alle <strong id="fToLbl">23:30</strong></span></div>')

      + sec("Compagnie", '<span class="small">'
            + '<button type="button" class="btn btn-sm btn-link p-0 text-decoration-none me-2" id="carAll">Tutte</button>'
            + '<button type="button" class="btn btn-sm btn-link p-0 text-decoration-none" id="carNone">Nessuna</button></span>',
            '<div class="f-cars d-flex flex-column gap-1">' + carList + "</div>")

      + '<button type="button" class="btn btn-sm btn-outline-secondary w-100 mt-3" id="fReset">Azzera filtri</button>'
      + "</div></div>";

    // Listener: ogni cambio riapplica i filtri.
    filtersEl.querySelectorAll(".f-stop, .f-car, #fBand, #fSort").forEach(el =>
      el.addEventListener("change", applyFilters));
    const fFrom = document.getElementById("fFrom"), fTo = document.getElementById("fTo");
    [fFrom, fTo].forEach(el => el.addEventListener("input", () => { onSlide(el); }));
    document.getElementById("fBand").addEventListener("change", resetSlider);
    document.getElementById("carAll").addEventListener("click", () => setCars(true));
    document.getElementById("carNone").addEventListener("click", () => setCars(false));
    document.getElementById("fReset").addEventListener("click", resetFilters);
    const toggle = document.getElementById("fToggle");
    toggle.addEventListener("click", () => {
      const open = document.getElementById("fBody").classList.toggle("d-none");
      toggle.setAttribute("aria-expanded", open ? "false" : "true");
      document.getElementById("fChevron").textContent = open ? "▸" : "▾";
    });
    // Mobile: pannello chiuso di default (su desktop la sidebar resta aperta).
    if (window.matchMedia("(max-width: 991.98px)").matches) toggle.click();
    paintSlider();
    filtersEl.hidden = false;
  }

  // --- slider a due maniglie -------------------------------------------
  function onSlide(moved) {
    const f = document.getElementById("fFrom"), t = document.getElementById("fTo");
    if (+f.value > +t.value - SL_GAP) {           // niente sovrapposizione delle maniglie
      if (moved === f) f.value = +t.value - SL_GAP;
      else t.value = +f.value + SL_GAP;
    }
    document.getElementById("fBand").value = "any";  // il manuale annulla la fascia
    paintSlider();
    applyFilters();
  }
  function paintSlider() {
    const f = document.getElementById("fFrom"), t = document.getElementById("fTo");
    if (!f || !t) return;
    const lo = (f.value - SL_MIN) / (SL_MAX - SL_MIN) * 100;
    const hi = (t.value - SL_MIN) / (SL_MAX - SL_MIN) * 100;
    const fill = document.getElementById("fRangeFill");
    fill.style.left = lo + "%"; fill.style.width = (hi - lo) + "%";
    document.getElementById("fFromLbl").textContent = toHHMM(+f.value);
    document.getElementById("fToLbl").textContent = toHHMM(+t.value);
    f.style.zIndex = (+f.value > SL_MAX - 120) ? 5 : 4;   // maniglia "dalle" afferrabile in alto
  }
  function resetSlider() {
    const f = document.getElementById("fFrom"), t = document.getElementById("fTo");
    if (f && t) { f.value = SL_MIN; t.value = SL_MAX; paintSlider(); }
  }

  const setCars = (on) => {
    filtersEl.querySelectorAll(".f-car").forEach(c => { c.checked = on; });
    applyFilters();
  };
  function resetFilters() {
    filtersEl.querySelectorAll(".f-stop, .f-car").forEach(c => { c.checked = true; });
    document.getElementById("fBand").value = "any";
    document.getElementById("fSort").value = "price";
    resetSlider();
    applyFilters();
  }

  function applyFilters() {
    const stops = [...filtersEl.querySelectorAll(".f-stop:checked")].map(c => c.value);
    const cars = [...filtersEl.querySelectorAll(".f-car:checked")].map(c => c.value);
    const allCars = filtersEl.querySelectorAll(".f-car").length;
    const band = (document.getElementById("fBand") || {}).value || "any";
    const sort = (document.getElementById("fSort") || {}).value || "price";
    const manual = sliderActive();
    const lo = manual ? +document.getElementById("fFrom").value : 0;
    const hi = manual ? +document.getElementById("fTo").value : 1440;

    const timeOk = (hhmm) => {
      if (manual) {                                   // intervallo manuale ha priorità
        if (!hhmm) return false;
        const m = toMin(hhmm);
        return m >= lo && m <= hi;
      }
      return bandOf(hhmm, band);                       // altrimenti fascia
    };

    let rows = lastOffers.filter(o => {
      const b = stopBucket(o.stops);
      if (b != null && !stops.includes(b)) return false;         // scali
      if (!timeOk(o.depart_time)) return false;                  // orario partenza
      if (allCars && cars.length < allCars) {                    // compagnie
        const oc = o.carriers || [];
        if (oc.length && !oc.some(c => cars.includes(c))) return false;
      }
      return true;
    });
    const key = { price: o => o.price,
                  depart: o => o.depart_time || "99:99",
                  arrive: o => o.arrival_time || "99:99" }[sort];
    rows = rows.slice().sort((a, b) => {
      const ka = key(a), kb = key(b);
      return ka < kb ? -1 : ka > kb ? 1 : 0;
    });

    // Conteggio filtri attivi (per il badge).
    let active = 0;
    if (stops.length < 3) active++;
    if (allCars && cars.length < allCars) active++;
    if (manual || band !== "any") active++;
    if (sort !== "price") active++;
    const badge = document.getElementById("fCount");
    if (badge) { badge.textContent = active; badge.classList.toggle("d-none", active === 0); }

    results.innerHTML = rows.length
      ? rows.map(offerCard).join("")
      : '<p class="text-muted">Nessun volo con questi filtri.</p>';
    status.textContent = rows.length + " di " + lastOffers.length
      + (lastOffers.length === 1 ? " risultato" : " risultati")
      + " · fonti: " + lastProviders.join(", ");
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const origin = document.getElementById("origin").value.trim().toUpperCase();
    const dest = document.getElementById("destination").value.trim().toUpperCase();
    const m = mode.value;
    results.innerHTML = "";
    if (filtersEl) filtersEl.hidden = true;
    document.getElementById("resultsCol").className = "col-12";
    status.textContent = "Ricerca in corso…";
    try {
      let html = "";
      if (m === "search") {
        // Flessibilità date -> finestra (giorni) + mesi scanditi dal catalogo.
        const FLEX = { "1": [1, 1], "2": [2, 1], "3": [3, 1], "7": [7, 1],
                       "14": [14, 1], "31": [16, 1], "90": [46, 3] };
        const fv = document.getElementById("flex").value;
        const [flexDays, months] = FLEX[fv] || [14, 1];
        const q = new URLSearchParams({ origin, destination: dest,
          departDate: document.getElementById("departDate").value,
          adults: document.getElementById("adults").value,
          flexDays: flexDays, months: months });
        const rd = document.getElementById("returnDate").value;
        if (rd) q.set("returnDate", rd);
        const data = await api("GET", "/api/search?" + q.toString());
        lastOffers = data.offers || [];
        lastProviders = data.providers || [];
        if (lastOffers.length) {
          buildFilters(lastOffers);
          applyFilters();
          return;
        }
        status.textContent = "0 risultati · fonti: " + lastProviders.join(", ");
      } else if (m === "explore") {
        const q = new URLSearchParams({ origin });
        const mp = document.getElementById("maxPrice").value;
        if (mp) q.set("maxPrice", mp);
        const data = await api("GET", "/api/explore?" + q.toString());
        const dests = data.destinations || [];
        html = dests.map(destCard).join("");
        const live = dests.filter(d => d && d.indicative === false).length;
        status.textContent = dests.length + " mete trovate"
          + (live ? " · " + live + " con prezzo reale verificato" : "");
      } else {
        const q = new URLSearchParams({ origin, destination: dest });
        const data = await api("GET", "/api/cheapest-dates?" + q.toString());
        html = (data.dates || []).map(dateCard).join("");
        status.textContent = (data.dates || []).length + " date trovate";
      }
      results.innerHTML = html || '<p class="text-muted">Nessun risultato. Con le chiavi API in ambiente di test la copertura è limitata.</p>';
    } catch (err) {
      status.textContent = "";
      results.innerHTML = '<div class="alert alert-danger">' + esc(err.message) + "</div>";
    }
  });
}

function sourceBadge(src) {
  if (!src) return "";
  const prov = esc(src.provider || "");
  const car = src.carrier ? " · " + esc(src.carrier) : "";
  return '<span class="badge text-bg-light badge-source">Fonte: ' + prov + car + "</span>";
}

function stopsLabel(s) {
  if (s == null) return "";
  if (s === 0) return "diretto";
  return s + (s === 1 ? " scalo" : " scali");
}

function offerCard(o) {
  const times = (o.depart_time || "") + (o.depart_time && o.arrival_time ? " → " : "")
    + (o.arrival_time || "");
  const car = (o.carriers && o.carriers.length) ? o.carriers.map(esc).join(", ") : "";
  const meta = [o.stops != null ? stopsLabel(o.stops) : "", car].filter(Boolean).join(" · ");
  return '<div class="col-12 col-md-6 col-lg-4"><div class="card shadow-sm h-100"><div class="card-body">'
    + '<h5 class="card-title">' + esc(o.origin) + " → " + esc(o.destination) + "</h5>"
    + '<div class="price">' + money(o.price, o.currency) + "</div>"
    + '<div class="small text-muted">' + esc(fmtDate(o.depart_date))
    + (o.return_date ? " → " + esc(fmtDate(o.return_date)) : "") + "</div>"
    + (times ? '<div class="small">🕐 ' + esc(times) + "</div>" : "")
    + (meta ? '<div class="small text-muted mb-2">' + meta + "</div>" : '<div class="mb-2"></div>')
    + sourceBadge(o.source) + "</div></div></div>";
}

function destCard(d) {
  return '<div class="col-12 col-md-6 col-lg-4"><div class="card shadow-sm h-100"><div class="card-body">'
    + '<h5 class="card-title">' + esc(d.origin) + " → " + esc(d.destination) + "</h5>"
    + '<div class="price">da ' + money(d.price, d.currency) + "</div>"
    + '<div class="small text-muted mb-2">' + esc(fmtDate(d.depart_date))
    + (d.return_date ? " → " + esc(fmtDate(d.return_date)) : "") + (d.indicative ? " · prezzo indicativo" : "") + "</div>"
    + sourceBadge(d.source) + "</div></div></div>";
}

function dateCard(d) {
  return '<div class="col-6 col-md-4 col-lg-3"><div class="card shadow-sm h-100"><div class="card-body">'
    + '<div class="fw-bold">' + esc(fmtDate(d.depart_date)) + "</div>"
    + '<div class="price">' + money(d.price, d.currency) + "</div>"
    + sourceBadge(d.source) + "</div></div></div>";
}

// ----- ORARI DI CONTROLLO DEGLI ALERT ------------------------------------
// L'utente sceglie a che ora il worker controlla i suoi alert (1 al giorno;
// admin fino a 4). Gli orari sono nel fuso dell'utente, a passi di 30 minuti.
function initSchedule() {
  const summary = document.getElementById("schedSummary");
  const slotsEl = document.getElementById("schedSlots");
  const addBtn = document.getElementById("schedAdd");
  const hint = document.getElementById("schedHint");
  const msg = document.getElementById("schedMsg");
  const form = document.getElementById("schedForm");
  if (!summary || !form) return;
  let info = null;

  const fmtLocal = (iso) => iso ? fmtDate(iso.slice(0, 10)) + " " + iso.slice(11, 16) : "";

  function options(step, selected) {
    let html = "";
    for (let m = 0; m < 1440; m += step) {
      const v = String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
      html += '<option value="' + v + '"' + (v === selected ? " selected" : "") + ">" + v + "</option>";
    }
    return html;
  }

  function slotRow(value) {
    const wrap = document.createElement("div");
    wrap.className = "input-group input-group-sm";
    wrap.style.width = "9.5rem";
    wrap.innerHTML = '<select class="form-select sched-time" aria-label="Orario">'
      + options(info.step_minutes, value) + "</select>"
      + '<button type="button" class="btn btn-outline-secondary sched-del" aria-label="Rimuovi orario">✕</button>';
    wrap.querySelector(".sched-del").addEventListener("click", () => { wrap.remove(); sync(); });
    return wrap;
  }

  // Mostra/nasconde "+ Aggiungi" e le ✕ in base al limite del ruolo.
  function sync() {
    const n = slotsEl.querySelectorAll(".sched-time").length;
    addBtn.hidden = info.max_runs <= 1 || n >= info.max_runs;
    slotsEl.querySelectorAll(".sched-del").forEach(b => { b.hidden = n <= 1; });
  }

  function render() {
    const t = info.run_times;
    if (t.length) {
      summary.innerHTML = "Ogni giorno alle <strong>" + t.map(esc).join(", ") + "</strong>"
        + (info.next_run_local ? " · prossimo controllo: " + esc(fmtLocal(info.next_run_local)) : "")
        + (info.last_run_local ? '<br>Ultimo controllo: ' + esc(fmtLocal(info.last_run_local)) : "");
    } else {
      summary.innerHTML = "Nessun orario scelto: controllo ogni <strong>" + info.poll_interval_hours
        + " ore</strong>. Scegli un orario fisso con «Cambia orario»."
        + (info.last_run_local ? '<br>Ultimo controllo: ' + esc(fmtLocal(info.last_run_local)) : "");
    }
    slotsEl.innerHTML = "";
    (t.length ? t : ["07:00"]).forEach(v => slotsEl.appendChild(slotRow(v)));
    hint.textContent = (info.max_runs > 1
        ? "Puoi scegliere fino a " + info.max_runs + " orari al giorno. "
        : "Un controllo al giorno. ")
      + "Il controllo parte entro " + info.step_minutes + " minuti dall'orario scelto (fuso "
      + info.timezone + ").";
    sync();
  }

  async function load() {
    try { info = await api("GET", "/api/me/schedule"); render(); }
    catch (err) { summary.textContent = err.message; }
  }

  addBtn.addEventListener("click", () => {
    const used = [...slotsEl.querySelectorAll(".sched-time")].map(s => s.value);
    // propone il primo orario "tondo" libero tra 07:00, 13:00, 19:00, 23:00
    const pick = ["07:00", "13:00", "19:00", "23:00", "10:00", "16:00", "21:00"]
      .find(v => !used.includes(v)) || "12:00";
    slotsEl.appendChild(slotRow(pick));
    sync();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "";
    const times = [...slotsEl.querySelectorAll(".sched-time")].map(s => s.value);
    try {
      info = await api("PUT", "/api/me/schedule", { run_times: times });
      render();
      msg.className = "small text-success";
      msg.textContent = "Orari salvati.";
    } catch (err) {
      msg.className = "small text-danger";
      msg.textContent = err.message;
    }
  });

  load();
}

// ----- ALERTS -------------------------------------------------------------
function initAlerts() {
  initSchedule();
  const list = document.getElementById("alertsList");
  const form = document.getElementById("alertForm");
  const errBox = document.getElementById("alertFormError");

  let rows = [];
  let editingId = null;
  const newBox = document.getElementById("newAlert");
  const submitBtn = document.getElementById("alertSubmit");
  const cancelBtn = document.getElementById("alertCancel");
  const advBox = document.getElementById("advAlert");
  const openBox = (box) => bootstrap.Collapse.getOrCreateInstance(box, { toggle: false }).show();

  async function load() {
    const data = await api("GET", "/api/alerts");
    rows = data.alerts || [];
    list.innerHTML = rows.length
      ? rows.map(alertCard).join("")
      : '<p class="text-muted">Nessun alert. Creane uno con “+ Nuovo alert”.</p>';
  }

  const tripSel = document.getElementById("a_trip_type");
  const dows = (id) => Array.from(document.querySelectorAll("#" + id + " input:checked"))
    .map((c) => c.value).join(",") || null;
  const val = (id) => document.getElementById(id).value || null;
  const el = (id) => document.getElementById(id);

  // Fasce orarie: la select compila i campi "dalle/entro"; "Personalizzata" li mostra.
  const PRESETS = {
    depart: { sel: el("a_depart_preset"), from: el("a_depart_time_from"), to: el("a_depart_time_to") },
    return: { sel: el("a_return_preset"), from: el("a_return_time_from"), to: el("a_return_time_to") },
  };
  function syncPreset(kind) {
    const P = PRESETS[kind];
    document.querySelectorAll('[data-time-custom="' + kind + '"]')
      .forEach((n) => n.classList.toggle("d-none", P.sel.value !== "custom"));
  }
  function onPreset(kind) {
    const P = PRESETS[kind];
    if (P.sel.value && P.sel.value !== "custom") {
      const [f, t] = P.sel.value.split("-");
      P.from.value = f; P.to.value = t;
    } else if (!P.sel.value) { P.from.value = ""; P.to.value = ""; }
    syncPreset(kind);
  }
  function loadPreset(kind, from, to) {
    const P = PRESETS[kind];
    P.from.value = from || ""; P.to.value = to || "";
    const key = (from || "") + "-" + (to || "");
    const known = [...P.sel.options].some((o) => o.value === key);
    P.sel.value = known ? key : ((from || to) ? "custom" : "");
    syncPreset(kind);
  }
  ["depart", "return"].forEach((k) => PRESETS[k].sel.addEventListener("change", () => onPreset(k)));

  // Ritorno (data, giorni): solo per A/R. Fascia di rientro: A/R e in giornata.
  function syncTripType() {
    const t = tripSel.value;
    document.querySelectorAll("[data-ret-only]").forEach((n) => n.classList.toggle("d-none", t !== "round_trip"));
    document.querySelectorAll("[data-ret-time]").forEach((n) => n.classList.toggle("d-none", t === "one_way"));
    syncPreset("depart"); syncPreset("return");
  }
  tripSel.addEventListener("change", () => {
    syncTripType();
    // In giornata: propone partenza al mattino e rientro nel pomeriggio/sera.
    if (tripSel.value === "same_day" && !PRESETS.depart.sel.value && !PRESETS.return.sel.value) {
      PRESETS.depart.sel.value = "05:00-12:00"; onPreset("depart");
      PRESETS.return.sel.value = "14:00-23:59"; onPreset("return");
    }
  });
  syncTripType();

  function setMode(id) {
    editingId = id;
    submitBtn.textContent = id ? "Salva modifiche" : "Crea";
    cancelBtn.hidden = !id;
    errBox.textContent = "";
  }

  function resetForm() {
    form.reset();
    ["depart", "return"].forEach((k) => loadPreset(k, "", ""));
    syncTripType();
    setMode(null);
  }

  function fillForm(a) {
    form.reset();
    el("a_origin").value = a.origin;
    const any = a.destination === "ANY";
    el("a_anywhere").checked = any;
    el("a_destination").value = any ? "" : a.destination;
    el("a_depart_from").value = a.depart_from || "";
    el("a_depart_to").value = a.depart_to && a.depart_to !== a.depart_from ? a.depart_to : "";
    el("a_return_from").value = a.return_from || "";
    el("a_strategy").value = a.strategy;
    el("a_target_price").value = a.target_price != null ? a.target_price : "";
    el("a_currency").value = a.currency || "EUR";
    tripSel.value = a.trip_type || "round_trip";
    el("a_horizon").value = a.horizon_months || "";
    el("a_max_stops").value = a.max_stops != null ? a.max_stops : "";
    const check = (prefix, csv) => {
      const on = (csv || "").split(",");
      for (let i = 1; i <= 7; i++) el(prefix + i).checked = on.includes(String(i));
    };
    check("dd", a.depart_dows); check("rd", a.return_dows);
    loadPreset("depart", a.depart_time_from, a.depart_time_to);
    loadPreset("return", a.return_time_from, a.return_time_to);
    syncTripType();
    setMode(a.id);
    openBox(newBox); openBox(advBox);
    newBox.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  el("newAlertBtn").addEventListener("click", () => {
    resetForm();
    bootstrap.Collapse.getOrCreateInstance(newBox, { toggle: false }).toggle();
  });
  cancelBtn.addEventListener("click", () => {
    resetForm();
    bootstrap.Collapse.getOrCreateInstance(newBox, { toggle: false }).hide();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errBox.textContent = "";
    const anywhere = el("a_anywhere").checked;
    const t = tripSel.value;
    const roundTrip = t === "round_trip";
    const hasRetTime = t !== "one_way";
    const body = {
      origin: el("a_origin").value.trim().toUpperCase(),
      destination: anywhere ? "ANY" : el("a_destination").value.trim().toUpperCase(),
      depart_from: el("a_depart_from").value,
      depart_to: el("a_depart_to").value || null,
      return_from: roundTrip ? (el("a_return_from").value || null) : null,
      strategy: el("a_strategy").value,
      currency: (el("a_currency").value || "EUR").toUpperCase(),
      trip_type: t,
      depart_dows: dows("a_depart_dows"),
      return_dows: roundTrip ? dows("a_return_dows") : null,
      depart_time_from: val("a_depart_time_from"),
      depart_time_to: val("a_depart_time_to"),
      return_time_from: hasRetTime ? val("a_return_time_from") : null,
      return_time_to: hasRetTime ? val("a_return_time_to") : null,
    };
    const tp = el("a_target_price").value;
    body.target_price = tp ? parseFloat(tp) : null;
    const hz = el("a_horizon").value;
    if (hz) body.horizon_months = parseInt(hz, 10);
    const ms = el("a_max_stops").value;
    if (ms !== "") body.max_stops = parseInt(ms, 10);
    submitBtn.disabled = true;
    try {
      const wasEdit = !!editingId;
      if (wasEdit) await api("PUT", "/api/alerts/" + editingId, body);
      else await api("POST", "/api/alerts", body);
      resetForm();
      if (wasEdit) bootstrap.Collapse.getOrCreateInstance(newBox, { toggle: false }).hide();
      await load();
    } catch (err) { errBox.textContent = err.message; }
    finally { submitBtn.disabled = false; }
  });

  list.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const id = btn.dataset.id, action = btn.dataset.action;
    try {
      if (action === "edit") {
        const a = rows.find((r) => r.id === id);
        if (a) fillForm(a);
        return;
      }
      if (action === "delete") {
        if (!confirm("Eliminare questo alert?")) return;
        await api("DELETE", "/api/alerts/" + id);
      } else {
        await api("POST", "/api/alerts/" + id + "/" + action);
      }
      await load();
    } catch (err) { alert(err.message); }
  });

  // /alerts?edit=<id> (link "Modifica" dalla pagina di dettaglio)
  load().then(() => {
    const id = new URLSearchParams(location.search).get("edit");
    const a = id && rows.find((r) => r.id === id);
    if (a) fillForm(a);
  });
}

// Che cosa cerca un alert (la definizione, non un giorno specifico).
function alertDefinition(a) {
  const target = a.target_price != null ? "soglia " + money(a.target_price, a.currency) : "";
  const DOW = ["", "Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
  const dowTxt = (csv) => (csv || "").split(",").filter(Boolean).map((n) => DOW[+n] || n).join("/");
  const TRIP = { round_trip: "A/R", one_way: "solo andata", same_day: "in giornata" };
  const STRAT = { threshold: "sotto soglia", drop: "calo di prezzo", deal: "buon affare" };
  let when;
  if (a.horizon_months) when = "prossimi " + a.horizon_months + " mesi";
  else if (a.depart_to && a.depart_to !== a.depart_from) when = fmtDate(a.depart_from) + " – " + fmtDate(a.depart_to);
  else when = fmtDate(a.depart_from);
  const bits = [when, TRIP[a.trip_type] || a.trip_type];
  const dd = dowTxt(a.depart_dows); if (dd) bits.push("part. " + dd);
  const rd = dowTxt(a.return_dows); if (rd) bits.push("rit. " + rd);
  if (a.depart_time_from || a.depart_time_to)
    bits.push("part. " + (a.depart_time_from || "…") + "–" + (a.depart_time_to || "…"));
  if (a.return_time_from || a.return_time_to)
    bits.push("rit. " + (a.return_time_from || "…") + "–" + (a.return_time_to || "…"));
  if (a.max_stops != null) bits.push(a.max_stops + " scali max");
  bits.push(STRAT[a.strategy] || a.strategy);
  if (target) bits.push(target);
  return bits.join(" · ");
}

// Giorno della settimana abbreviato di una data ISO (AAAA-MM-GG).
function fmtDow(iso) {
  if (!iso || iso.length < 10) return "";
  const d = new Date(iso.slice(0, 10) + "T12:00:00");
  return ["Dom", "Lun", "Mar", "Mer", "Gio", "Ven", "Sab"][d.getDay()] || "";
}

function alertCard(a) {
  const paused = a.status === "paused";
  const badge = paused
    ? '<span class="badge text-bg-secondary">Sospeso</span>'
    : '<span class="badge text-bg-success">Attivo</span>';
  const toggle = paused
    ? '<button class="btn btn-sm btn-outline-success" data-action="resume" data-id="' + a.id + '">Riprendi</button>'
    : '<button class="btn btn-sm btn-outline-secondary" data-action="suspend" data-id="' + a.id + '">Sospendi</button>';
  const dest = a.destination === "ANY" ? "Ovunque 🌍" : a.destination;
  const def = '<div class="small text-muted mb-2">' + esc(alertDefinition(a)) + "</div>";

  // La MIGLIOR offerta trovata: destinazione (nome completo) e giorno reali.
  let found;
  const o = a.last_offer;
  if (o && o.price != null) {
    const code = o.destination || a.destination;
    const name = o.destination_name && o.destination_name !== code ? o.destination_name : "";
    const dep = fmtDow(o.depart_date) + " " + fmtDate(o.depart_date) + (o.depart_time ? " " + o.depart_time : "");
    const ret = o.return_date ? " → " + fmtDow(o.return_date) + " " + fmtDate(o.return_date) + (o.return_time ? " " + o.return_time : "") : "";
    found = '<div class="small text-muted">Offerta più economica</div>'
      + '<div class="mb-1" title="' + esc((name || code) + " (" + code + ")") + '">'
      + '<span class="fw-semibold">' + esc(name || code) + "</span>"
      + (name ? ' <span class="badge text-bg-light border ms-1">' + esc(code) + "</span>" : "") + "</div>"
      + '<div class="text-muted small">' + esc(dep + ret) + "</div>"
      + '<div class="price">' + money(o.price, o.currency || a.currency) + "</div>";
  } else if (a.last_price != null) {
    found = '<div class="price">' + money(a.last_price, a.currency) + "</div>";
  } else {
    found = '<div class="text-muted small">nessuna offerta ancora rilevata</div>';
  }

  return '<div class="col-12 col-md-6"><div class="card shadow-sm h-100 alert-card ' + (paused ? "status-paused" : "") + '">'
    + '<div class="card-body">'
    + '<div class="d-flex justify-content-between align-items-start">'
    + '<h5 class="card-title mb-1"><a class="text-decoration-none text-reset" href="/alerts/' + a.id + '">'
    + esc(a.origin) + " → " + esc(dest) + "</a></h5>" + badge + "</div>"
    + def
    + found
    + '<div class="d-flex flex-wrap gap-2 mt-3">'
    + '<a class="btn btn-sm btn-primary" href="/alerts/' + a.id + '">Vedi tutte le soluzioni →</a>'
    + '<button class="btn btn-sm btn-outline-primary" data-action="edit" data-id="' + a.id + '">Modifica</button>' + toggle
    + '<button class="btn btn-sm btn-outline-danger" data-action="delete" data-id="' + a.id + '">Elimina</button>'
    + "</div></div></div></div>";
}

// ----- DETTAGLIO ALERT: tutte le soluzioni trovate ------------------------
function offerRow(o) {
  const code = o.destination || "";
  const name = o.destination_name && o.destination_name !== code ? o.destination_name : "";
  const dep = fmtDow(o.depart_date) + " " + fmtDate(o.depart_date)
    + (o.depart_time ? " · " + o.depart_time + (o.arrival_time ? " → " + o.arrival_time : "") : "");
  const ret = o.return_date
    ? '<div class="small">🛬 ' + esc(fmtDow(o.return_date) + " " + fmtDate(o.return_date)
      + (o.return_time ? " · " + o.return_time : "")) + "</div>" : "";
  const car = (o.carriers && o.carriers.length) ? o.carriers.map(esc).join(", ") : "";
  const meta = [o.stops != null ? stopsLabel(o.stops) : "", car].filter(Boolean).join(" · ");
  return '<div class="col-12 col-md-6 col-lg-4"><div class="card shadow-sm h-100"><div class="card-body">'
    + '<div class="d-flex justify-content-between align-items-start gap-2">'
    + '<div title="' + esc((name || code) + " (" + code + ")") + '">'
    + '<div class="fw-semibold">' + esc(name || code) + "</div>"
    + (name ? '<div class="small text-muted">' + esc(code) + "</div>" : "") + "</div>"
    + '<div class="price">' + money(o.price, o.currency) + "</div></div>"
    + '<div class="small mt-2">🛫 ' + esc(dep) + "</div>" + ret
    + (meta ? '<div class="small text-muted">' + meta + "</div>" : "")
    + "</div></div></div>";
}

function initAlertDetail() {
  const id = window.__ALERT_ID__;
  const head = document.getElementById("alertHead");
  const tools = document.getElementById("offerTools");
  const status = document.getElementById("offerStatus");
  const list = document.getElementById("offersList");
  const sortSel = document.getElementById("offerSort");
  let offers = [];

  function paint() {
    const key = {
      price: (x, y) => x.price - y.price,
      date: (x, y) => (x.depart_date + (x.depart_time || "")).localeCompare(y.depart_date + (y.depart_time || "")),
      name: (x, y) => (x.destination_name || x.destination || "").localeCompare(y.destination_name || y.destination || "", "it"),
    }[sortSel.value];
    list.innerHTML = offers.slice().sort(key).map(offerRow).join("");
  }

  async function load() {
    try {
      const data = await api("GET", "/api/alerts/" + encodeURIComponent(id) + "/offers");
      const a = data.alert;
      const dest = a.destination === "ANY" ? "Ovunque 🌍" : a.destination;
      head.innerHTML = '<h1 class="h4 mb-1">' + esc(a.origin) + " → " + esc(dest) + "</h1>"
        + '<div class="small text-muted">' + esc(data.origin_name || "") + "</div>"
        + '<div class="small text-muted">' + esc(alertDefinition(a)) + "</div>"
        + '<a class="btn btn-sm btn-outline-primary mt-2" href="/alerts?edit=' + encodeURIComponent(a.id) + '">Modifica alert</a>';
      offers = data.offers || [];
      if (!offers.length) {
        status.textContent = "Nessuna soluzione ancora: compariranno al prossimo controllo dell'alert.";
        return;
      }
      const when = data.observed_at ? new Date(data.observed_at + "Z") : null;
      const pad = (n) => String(n).padStart(2, "0");
      const stamp = when ? fmtDate(when.getFullYear() + "-" + pad(when.getMonth() + 1) + "-" + pad(when.getDate()))
        + " " + pad(when.getHours()) + ":" + pad(when.getMinutes()) : "";
      status.textContent = offers.length + (offers.length === 1 ? " soluzione" : " soluzioni")
        + (stamp ? " · ultimo controllo " + stamp : "")
        + (data.from_history ? " · storico delle migliori offerte rilevate: l'elenco completo arriva al prossimo controllo" : "");
      tools.hidden = false;
      paint();
    } catch (err) {
      status.innerHTML = '<span class="text-danger">' + esc(err.message) + "</span>";
    }
  }
  sortSel.addEventListener("change", paint);
  load();
}

// ----- PREFERENCES --------------------------------------------------------
function initPreferences() {
  const form = document.getElementById("prefsForm");
  const msg = document.getElementById("prefsMsg");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "";
    try {
      await api("PUT", "/api/me/preferences", {
        poll_interval_hours: parseInt(document.getElementById("p_interval").value, 10),
        currency: document.getElementById("p_currency").value.toUpperCase(),
        timezone: document.getElementById("p_timezone").value,
      });
      msg.className = "small mt-2 text-success";
      msg.textContent = "Preferenze salvate.";
    } catch (err) {
      msg.className = "small mt-2 text-danger";
      msg.textContent = err.message;
    }
  });

  const pwdForm = document.getElementById("pwdForm");
  const pwdMsg = document.getElementById("pwdMsg");
  if (pwdForm) {
    pwdForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      pwdMsg.textContent = "";
      const cur = document.getElementById("pw_current").value;
      const nw = document.getElementById("pw_new").value;
      const conf = document.getElementById("pw_confirm").value;
      if (nw !== conf) {
        pwdMsg.className = "small mt-2 text-danger";
        pwdMsg.textContent = "Le due nuove password non coincidono.";
        return;
      }
      try {
        await api("PUT", "/api/me/password", { current_password: cur, new_password: nw });
        pwdForm.reset();
        pwdMsg.className = "small mt-2 text-success";
        pwdMsg.textContent = "Password aggiornata.";
      } catch (err) {
        pwdMsg.className = "small mt-2 text-danger";
        pwdMsg.textContent = err.message;
      }
    });
  }
}

// ----- ADMIN --------------------------------------------------------------
function initAdmin() {
  const statsBox = document.getElementById("stats");
  const body = document.getElementById("usersBody");
  const isSuper = window.__IS_SUPERADMIN__ === true;

  async function loadStats() {
    const s = await api("GET", "/api/admin/stats");
    const tile = (t, v) => '<div class="col-6 col-md-3"><div class="card shadow-sm"><div class="card-body text-center">'
      + '<div class="h3 mb-0">' + esc(v) + "</div><div class=\"small text-muted\">" + esc(t) + "</div></div></div></div>";
    statsBox.innerHTML = tile("Utenti", s.users) + tile("Alert attivi", s.alerts_active)
      + tile("Email inviate", s.emails_sent)
      + tile("Ultimo run", s.last_run ? (s.last_run.status || "-") : "mai");
  }

  async function loadUsers() {
    const data = await api("GET", "/api/admin/users");
    body.innerHTML = (data.users || []).map(u => {
      let roleCell = esc(u.role);
      if (isSuper) {
        roleCell = '<select class="form-select form-select-sm" data-role-for="' + u.id + '">'
          + ["user", "admin", "superadmin"].map(r =>
            '<option value="' + r + '"' + (r === u.role ? " selected" : "") + ">" + r + "</option>").join("")
          + "</select>";
      }
      const act = u.status === "suspended"
        ? '<button class="btn btn-sm btn-outline-success" data-uaction="resume" data-id="' + u.id + '">Riattiva</button>'
        : '<button class="btn btn-sm btn-outline-secondary" data-uaction="suspend" data-id="' + u.id + '">Sospendi</button>';
      return "<tr><td>" + esc(u.email) + "</td><td>" + roleCell + "</td><td>" + esc(u.status)
        + '</td><td class="text-end">' + act + "</td></tr>";
    }).join("");
  }

  body.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-uaction]");
    if (!btn) return;
    try { await api("POST", "/api/admin/users/" + btn.dataset.id + "/" + btn.dataset.uaction); await loadUsers(); }
    catch (err) { alert(err.message); }
  });

  body.addEventListener("change", async (e) => {
    const sel = e.target.closest("select[data-role-for]");
    if (!sel) return;
    try { await api("PATCH", "/api/admin/users/" + sel.dataset.roleFor + "/role", { role: sel.value }); }
    catch (err) { alert(err.message); await loadUsers(); }
  });

  loadStats().catch(() => {});
  loadUsers().catch(() => {});
}

// ----- mostra/nascondi password (icona occhio) ----------------------------
// Icone stile Bootstrap Icons (SVG inline, nessuna dipendenza esterna).
const ICON_EYE =
  '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" viewBox="0 0 16 16">'
  + '<path d="M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8M1.173 8a13 13 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5s3.879 1.168 5.168 2.457A13 13 0 0 1 14.828 8q-.086.13-.195.288c-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5s-3.879-1.168-5.168-2.457A13 13 0 0 1 1.172 8z"/>'
  + '<path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5M4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0"/></svg>';
const ICON_EYE_SLASH =
  '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" viewBox="0 0 16 16">'
  + '<path d="M13.359 11.238C15.06 9.72 16 8 16 8s-3-5.5-8-5.5a7 7 0 0 0-2.79.588l.77.771A6 6 0 0 1 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13 13 0 0 1 14.828 8q-.086.13-.195.288c-.335.48-.83 1.12-1.465 1.755q-.247.248-.517.486z"/>'
  + '<path d="M11.297 9.176a3.5 3.5 0 0 0-4.474-4.474l.823.823a2.5 2.5 0 0 1 2.829 2.829zm-2.943 1.299.822.822a3.5 3.5 0 0 1-4.474-4.474l.823.823a2.5 2.5 0 0 0 2.829 2.829"/>'
  + '<path d="M3.35 5.47q-.27.24-.518.487A13 13 0 0 0 1.172 8l.195.288c.335.48.83 1.12 1.465 1.755C4.121 11.332 5.881 12.5 8 12.5c.716 0 1.39-.133 2.02-.36l.77.772A7 7 0 0 1 8 13.5C3 13.5 0 8 0 8s.939-1.721 2.641-3.238l.708.709z"/>'
  + '<path d="m13.646 14.354-12-12 .708-.708 12 12z"/></svg>';

function initPasswordToggles() {
  document.querySelectorAll("[data-pw-toggle]").forEach((btn) => {
    btn.innerHTML = ICON_EYE;
    btn.setAttribute("aria-label", "Mostra password");
    btn.addEventListener("click", () => {
      const inp = document.getElementById(btn.getAttribute("data-pw-toggle"));
      if (!inp) return;
      const show = inp.type === "password";
      inp.type = show ? "text" : "password";
      btn.innerHTML = show ? ICON_EYE_SLASH : ICON_EYE;
      btn.setAttribute("aria-label", show ? "Nascondi password" : "Mostra password");
    });
  });
}

// ----- bootstrap ----------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initPasswordToggles();
  switch (window.__PAGE__) {
    case "dashboard": initDashboard(); break;
    case "alerts": initAlerts(); break;
    case "alert_detail": initAlertDetail(); break;
    case "preferences": initPreferences(); break;
    case "admin": initAdmin(); break;
  }
});
