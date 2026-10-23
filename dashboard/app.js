/* Chento Tracker — dashboard statica. Dati in window.CHENTO_DATA (generato da `python -m chento analyze`). */
(() => {
  const D = window.CHENTO_DATA;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmtR = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}R`);
  const fmtP = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
  const fmtN = (v, d = 2) => (v == null ? "—" : Number(v).toLocaleString("it-IT", { maximumFractionDigits: d }));
  const cls = (v) => (v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");
  const dt = (ts) => new Date(ts).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  const tip = $("#tooltip");

  if (!D) {
    $("#overview").innerHTML = `<h1 class="large">Nessun dato</h1><p class="subtitle">Esegui <code>python -m chento demo</code> oppure <code>python -m chento sync</code>, poi <code>python -m chento analyze</code>.</p>`;
    return;
  }

  const P = D.profile, R = D.replica.stats, X = D.derived.stats;
  $("#meta").textContent = `Aggiornato ${new Date(D.generated * 1000).toLocaleString("it-IT", { dateStyle: "medium", timeStyle: "short" })}`;
  if (D.demo) {
    $("#banner").innerHTML = `<div class="demo">⚠️ <span><b>Dati DEMO sintetici</b> — messaggi generati per prova su prezzi reali. Non sono messaggi di Chento: collega il bot Discord per l'analisi reale.</span></div>`;
  }

  /* ---------------- tabs ---------------- */
  const tabs = $("#tabs");
  function show(name) {
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
    document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === name));
    try { localStorage.setItem("chento-tab", name); } catch (e) { /* storage non disponibile */ }
    window.scrollTo({ top: 0 });
  }
  tabs.addEventListener("click", (e) => e.target.dataset.tab && show(e.target.dataset.tab));

  /* ---------------- charts ---------------- */
  function lineChart(series, { height = 240, yFmt = fmtR } = {}) {
    const W = 800, H = height, pl = 48, pr = 12, pt = 10, pb = 26;
    const all = series.flatMap((s) => s.points);
    if (!all.length) return `<div class="empty">Nessun trade chiuso</div>`;
    const xs = all.map((p) => +new Date(p.x)), ys = all.map((p) => p.y).concat(0);
    let x0 = Math.min(...xs), x1 = Math.max(...xs); if (x0 === x1) x1 = x0 + 1;
    let y0 = Math.min(...ys), y1 = Math.max(...ys); const pad = (y1 - y0) * 0.08 || 1; y0 -= pad; y1 += pad;
    const X = (v) => pl + ((v - x0) / (x1 - x0)) * (W - pl - pr);
    const Y = (v) => pt + (1 - (v - y0) / (y1 - y0)) * (H - pt - pb);
    const ticks = 4, grid = [];
    for (let i = 0; i <= ticks; i++) {
      const v = y0 + ((y1 - y0) * i) / ticks;
      grid.push(`<line class="grid-line" x1="${pl}" x2="${W - pr}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${pl - 8}" y="${Y(v) + 4}" text-anchor="end">${esc(yFmt(v))}</text>`);
    }
    const xl = [x0, (x0 + x1) / 2, x1].map((v, i) => `<text x="${X(v)}" y="${H - 6}" text-anchor="${["start", "middle", "end"][i]}">${new Date(v).toLocaleDateString("it-IT", { day: "2-digit", month: "short" })}</text>`);
    const paths = series.map((s) => {
      const pts = [{ x: s.points[0]?.x, y: 0 }, ...s.points];
      const d = pts.map((p, i) => `${i ? "L" : "M"}${X(+new Date(p.x)).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
      return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
    });
    const id = "c" + Math.random().toString(36).slice(2);
    setTimeout(() => {
      const svg = document.getElementById(id); if (!svg) return;
      const cross = svg.querySelector(".cross");
      svg.addEventListener("pointermove", (e) => {
        const r = svg.getBoundingClientRect(), vx = ((e.clientX - r.left) / r.width) * W;
        const t = x0 + ((vx - pl) / (W - pl - pr)) * (x1 - x0);
        const rows = series.map((s) => {
          let last = null; for (const p of s.points) { if (+new Date(p.x) <= t) last = p; else break; }
          return `<div><span style="color:${s.color}">●</span> ${esc(s.name)}: <b>${esc(yFmt(last ? last.y : 0))}</b></div>`;
        });
        cross.setAttribute("x1", vx); cross.setAttribute("x2", vx); cross.style.opacity = 1;
        tip.hidden = false; tip.innerHTML = `<div class="muted">${new Date(t).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric" })}</div>${rows.join("")}`;
        tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = e.clientY + 14 + "px";
      });
      svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.style.opacity = 0; });
    });
    return `<svg id="${id}" class="chart" viewBox="0 0 ${W} ${H}" role="img">${grid.join("")}<line class="zero" x1="${pl}" x2="${W - pr}" y1="${Y(0)}" y2="${Y(0)}"/>${xl.join("")}${paths.join("")}<line class="cross" y1="${pt}" y2="${H - pb}" stroke="${css("--label-3")}" style="opacity:0"/></svg>`;
  }

  function histogram(series, { bins = [-1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5, 3, 4] } = {}) {
    const W = 800, H = 200, pl = 36, pb = 24, pt = 8;
    const labels = ["≤-1", "-1…-0.5", "-0.5…0", "0…0.5", "0.5…1", "1…1.5", "1.5…2", "2…2.5", "2.5…3", "3…4", ">4"];
    const counts = series.map((s) => {
      const c = new Array(labels.length).fill(0);
      s.values.forEach((v) => { const k = bins.findIndex((b) => v < b); let i = k < 0 ? labels.length - 1 : k - 1; if (v <= -1) i = 0; c[Math.max(0, i)]++; });
      return c;
    });
    const max = Math.max(1, ...counts.flat());
    const gw = (W - pl) / labels.length, bw = (gw - 8) / series.length;
    let out = "";
    for (let i = 0; i <= 4; i++) { const y = pt + (1 - i / 4) * (H - pt - pb); out += `<line class="grid-line" x1="${pl}" x2="${W}" y1="${y}" y2="${y}"/><text x="${pl - 6}" y="${y + 4}" text-anchor="end">${Math.round((max * i) / 4)}</text>`; }
    labels.forEach((l, i) => {
      series.forEach((s, k) => {
        const h = (counts[k][i] / max) * (H - pt - pb);
        out += `<rect x="${pl + i * gw + 4 + k * bw}" y="${H - pb - h}" width="${bw - 2}" height="${h}" rx="3" fill="${s.color}"><title>${esc(s.name)} ${l}R: ${counts[k][i]}</title></rect>`;
      });
      out += `<text x="${pl + i * gw + gw / 2}" y="${H - 6}" text-anchor="middle">${l}</text>`;
    });
    return `<svg class="chart" viewBox="0 0 ${W} ${H}">${out}</svg>`;
  }

  const bars = (rows, { value = (r) => r.n, label = (r) => r.key, fmt = (v) => v, color = css("--blue") } = {}) => {
    const max = Math.max(1, ...rows.map((r) => Math.abs(value(r) ?? 0)));
    return rows.map((r) => `<div class="bar-row"><span class="name">${esc(label(r))}</span><span class="bar-track"><span class="bar-fill" style="width:${(Math.abs(value(r) ?? 0) / max) * 100}%;background:${typeof color === "function" ? color(r) : color}"></span></span><span class="num muted">${esc(fmt(value(r)))}</span></div>`).join("") || `<div class="muted">n/d</div>`;
  };

  const curve = (s) => s.curve.map((p) => ({ x: p.ts, y: p.r }));
  const C = { a: () => css("--blue"), b: () => css("--green") };

  /* ---------------- overview ---------------- */
  function kpi(label, a, b, fmt, invert = false) {
    let delta = "";
    if (b != null && a != null) {
      const d = b - a, good = invert ? d < 0 : d > 0;
      delta = `<div class="delta">Chento+ <span class="${d === 0 ? "" : good ? "pos" : "neg"}">${esc(fmt(b))}</span></div>`;
    }
    return `<div class="card kpi"><div class="label">${label}</div><div class="value ${label.includes("R") ? cls(a) : ""}">${esc(fmt(a))}</div>${delta}</div>`;
  }

  function renderOverview() {
    const f = P.fingerprint;
    $("#overview").innerHTML = `
      <h1 class="large">Panoramica</h1>
      <p class="subtitle">${fmtN(P.activity.messages, 0)} messaggi · ${fmtN(R.signals, 0)} segnali · ${P.period.from ? `${dt(P.period.from)} → ${dt(P.period.to)}` : ""}</p>
      <div class="grid g-5">
        ${kpi("Win rate", R.win_rate, X.win_rate, fmtP)}
        ${kpi("R totale", R.total_r, X.total_r, fmtR)}
        ${kpi("R medio", R.avg_r, X.avg_r, fmtR)}
        ${kpi("Profit factor", R.profit_factor, X.profit_factor, (v) => (v == null ? "—" : v.toFixed(2)))}
        ${kpi("Max drawdown", R.max_dd_r, X.max_dd_r, fmtR)}
      </div>
      <div class="grid g-21" style="margin-top:12px">
        <div class="card">
          <h3>Equity (R cumulati)</h3>
          <div class="legend"><span><i style="background:${C.a()}"></i>Replica Chento</span><span><i style="background:${C.b()}"></i>Chento+</span></div>
          ${lineChart([{ name: "Replica", color: C.a(), points: curve(R) }, { name: "Chento+", color: C.b(), points: curve(X) }], { height: 330 })}
        </div>
        <div class="card">
          <h3>Strategia rilevata</h3>
          <p class="summary" style="margin:0">${esc(f.summary)}</p>
          <div style="margin-top:14px;display:flex;gap:6px;flex-wrap:wrap">
            <span class="pill blue">${esc(f.horizon)}</span><span class="pill purple">${esc(f.asset_class)}</span>
            ${f.timeframe ? `<span class="pill">${esc(f.timeframe)}</span>` : ""}<span class="pill">${esc(f.bias)}</span>
          </div>
        </div>
      </div>
      <h2>Pattern ricorrenti</h2>
      <div class="card flush"><ul class="list">${P.insights.map((i) => `<li><span class="dot ${i.tone}"></span><span>${esc(i.text)}</span></li>`).join("") || `<li class="muted">Servono più dati.</li>`}</ul></div>`;
  }

  /* ---------------- strategy ---------------- */
  function table(rows, cols) {
    return `<div class="table-wrap"><table><thead><tr>${cols.map((c) => `<th class="${c[3] || ""}">${c[0]}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td class="${c[2] ? c[2](r) : ""} ${c[3] || ""}">${esc(c[1](r))}</td>`).join("")}</tr>`).join("") || `<tr><td class="muted" colspan="${cols.length}">n/d</td></tr>`}</tbody></table></div>`;
  }
  const perfCols = [["", (r) => r.key], ["Trade", (r) => r.n], ["Win rate", (r) => fmtP(r.win_rate)], ["R medio", (r) => fmtR(r.avg_r), (r) => cls(r.avg_r)], ["R totale", (r) => fmtR(r.total_r), (r) => cls(r.total_r)]];

  function heatmap(h) {
    const max = Math.max(1, ...h.flat()), days = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], blue = css("--blue");
    let out = `<span></span>` + Array.from({ length: 24 }, (_, i) => `<span class="hl">${i % 3 === 0 ? i : ""}</span>`).join("");
    h.forEach((row, d) => {
      out += `<span>${days[d]}</span>` + row.map((v, hr) => `<span class="cell" title="${days[d]} ${hr}:00 — ${v} messaggi" style="${v ? `background:color-mix(in srgb, ${blue} ${15 + (v / max) * 85}%, transparent)` : ""}"></span>`).join("");
    });
    return `<div class="heat">${out}</div>`;
  }

  function renderStrategy() {
    const r = P.risk, m = P.management, f = P.fingerprint;
    const stat = (l, v) => `<div><div class="muted" style="font-size:13px">${l}</div><div class="num" style="font-size:20px;font-weight:600">${esc(v ?? "—")}</div></div>`;
    $("#strategy").innerHTML = `
      <h1 class="large">Strategia di Chento</h1>
      <p class="subtitle">${esc(f.style)}</p>
      <div class="grid g-3">
        <div class="card"><h3>Stile (da testo e grafici)</h3>${bars(P.style_mix, { value: (x) => x.pct, label: (x) => x.label.split(" (")[0], fmt: fmtP, color: css("--purple") })}</div>
        <div class="card"><h3>Strumenti</h3>${bars(P.instruments, {})}</div>
        <div class="card"><h3>Direzione e timeframe</h3>
          ${bars([{ key: "Long", n: P.sides.long }, { key: "Short", n: P.sides.short }], { color: (x) => (x.key === "Long" ? css("--green") : css("--red")) })}
          <div style="height:10px"></div>${bars(P.timeframes, { color: css("--teal") })}</div>
      </div>
      <h2>Gestione del rischio</h2>
      <div class="card"><div class="grid g-4">
        ${stat("Segnali con SL", fmtP(r.with_stop_pct))}${stat("Stop medio", r.avg_stop_pct != null ? r.avg_stop_pct + "%" : null)}
        ${stat("R:R pianificato medio", r.avg_planned_rr)}${stat("Target medi", r.avg_targets)}
        ${stat("SL a breakeven", fmtP(m.be_after_entry_pct))}${stat("Chiusure manuali", fmtP(m.manual_close_pct))}
        ${stat("Durata mediana", m.median_hold_h != null ? m.median_hold_h + " h" : null)}${stat("Re-entry < 24h", m.reentries_24h)}
      </div></div>
      <h2>Quando pubblica</h2>
      <div class="card"><h3>Messaggi per giorno e ora (ora italiana)</h3>${heatmap(P.activity.heatmap)}
        <p class="muted" style="margin:12px 0 0;font-size:13px">${fmtN(P.activity.per_day)} messaggi/giorno · ${fmtN(P.activity.signals_per_week)} segnali/settimana · ${P.activity.with_images} con immagini</p></div>
      <h2>Performance per segmento <span class="muted" style="font-size:15px;font-weight:500">(replica 1:1)</span></h2>
      <div class="grid g-2">
        <div class="card flush">${table(P.by_symbol, perfCols)}</div>
        <div class="card flush">${table(P.by_session, perfCols)}</div>
        <div class="card flush">${table(P.by_side, perfCols)}</div>
        <div class="card flush">${table(P.by_weekday, perfCols)}</div>
      </div>`;
  }

  /* ---------------- feed ---------------- */
  const OUT = { win: ["green", "Vinto"], loss: ["red", "Perso"], breakeven: ["", "Pareggio"], open: ["blue", "Aperto"], not_filled: ["", "Non eseguito"], skipped: ["orange", "Saltato"], no_data: ["", "Nessun dato"], invalid: ["", "Non valido"] };
  const KIND = { entry: ["blue", "Segnale"], update: ["purple", "Update"], comment: ["", "Commento"] };
  let feedFilter = "all", feedQuery = "", feedLimit = 40;

  function perfBox(t, title) {
    if (!t) return "";
    const [c, l] = OUT[t.outcome] || ["", t.outcome];
    const extra = t.outcome === "skipped" ? (t.reasons || []).join(" · ") : t.exits ? t.exits.map((e) => `${e.why} @ ${fmtN(e.price, 6)}`).join(" · ") : "";
    return `<div class="perf-box"><div class="muted">${title}</div><div style="display:flex;gap:8px;align-items:center;margin-top:2px"><b class="${cls(t.r)}">${t.outcome === "skipped" || t.outcome === "not_filled" ? "—" : fmtR(t.r)}</b><span class="pill ${c}">${l}</span>${t.implied_stop ? `<span class="pill orange" title="SL non indicato: stimato con ATR">SL stimato</span>` : ""}</div>${extra ? `<div class="why">${esc(extra)}</div>` : ""}</div>`;
  }

  function msgCard(m) {
    const s = m.signal, [kc, kl] = KIND[s.kind];
    const lv = [];
    if (s.symbol) lv.push(`<span class="pill">${esc(s.symbol)}</span>`);
    if (s.side) lv.push(`<span class="pill ${s.side === "long" ? "green" : "red"}">${s.side.toUpperCase()}</span>`);
    if (s.entry?.length) lv.push(`<span class="pill">Entry ${s.entry.map((x) => fmtN(x, 6)).join("–")}</span>`);
    if (s.stop != null) lv.push(`<span class="pill">SL ${fmtN(s.stop, 6)}</span>`);
    if (s.targets?.length) lv.push(`<span class="pill">TP ${s.targets.map((x) => fmtN(x, 6)).join(" / ")}</span>`);
    if (s.rr) lv.push(`<span class="pill blue">R:R ${s.rr}</span>`);
    if (s.update) lv.push(`<span class="pill purple">${esc(s.update)}</span>`);
    Object.keys(s.tags || {}).forEach((t) => lv.push(`<span class="pill">#${esc(t)}</span>`));
    return `<article class="card msg">
      <div class="head"><span class="pill ${kc}">${kl}</span><span>${esc(m.author || "")}</span><span>·</span><time>${dt(m.ts)}</time>${s.source !== "rules" ? `<span class="pill purple">AI</span>` : ""}</div>
      <div></div>
      ${m.text ? `<div class="text">${esc(m.text)}</div>` : ""}
      ${m.images.length ? `<div class="thumbs">${m.images.map((src) => `<img loading="lazy" src="${esc(src)}" alt="grafico allegato">`).join("")}</div>` : ""}
      ${lv.length ? `<div class="levels">${lv.join("")}</div>` : ""}
      ${s.ai_analysis ? `<div class="text muted">${esc(s.ai_analysis)}</div>` : ""}
      ${s.kind === "entry" ? `<div class="perf">${perfBox(m.replica, "Replica Chento")}${perfBox(m.derived, "Chento+")}</div>` : ""}
    </article>`;
  }

  function renderFeed() {
    const counts = { all: D.feed.length, entry: 0, update: 0, comment: 0, img: 0 };
    D.feed.forEach((m) => { counts[m.signal.kind]++; if (m.images.length) counts.img++; });
    const chip = (k, l) => `<button class="chip" data-f="${k}" aria-pressed="${feedFilter === k}">${l} <span class="muted">${counts[k]}</span></button>`;
    const q = feedQuery.toLowerCase();
    const items = D.feed.slice().reverse().filter((m) =>
      (feedFilter === "all" || (feedFilter === "img" ? m.images.length : m.signal.kind === feedFilter)) &&
      (!q || (m.text + " " + (m.signal.symbol || "")).toLowerCase().includes(q)));
    $("#feed").innerHTML = `
      <h1 class="large">Messaggi</h1>
      <p class="subtitle">Ogni messaggio con testo, immagini, segnale estratto e performance reale sul prezzo.</p>
      <div class="feed-toolbar"><div class="chips">${chip("all", "Tutti")}${chip("entry", "Segnali")}${chip("update", "Update")}${chip("comment", "Commenti")}${chip("img", "Con immagini")}</div>
      <input class="search" type="search" placeholder="Cerca testo o simbolo" value="${esc(feedQuery)}"></div>
      ${items.slice(0, feedLimit).map(msgCard).join("") || `<div class="empty">Nessun messaggio</div>`}
      ${items.length > feedLimit ? `<button class="more">Mostra altri ${Math.min(40, items.length - feedLimit)}</button>` : ""}`;
    $("#feed .chips").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) { feedFilter = b.dataset.f; feedLimit = 40; renderFeed(); } });
    const inp = $("#feed .search");
    inp.addEventListener("input", () => { feedQuery = inp.value; feedLimit = 40; renderFeed(); const n = $("#feed .search"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); });
    $("#feed .more")?.addEventListener("click", () => { feedLimit += 40; renderFeed(); });
  }

  /* ---------------- compare ---------------- */
  function renderCompare() {
    const f = (row, v) => (v == null ? "—" : row.fmt === "r" ? fmtR(v) : row.fmt === "pct" ? fmtP(v) : row.fmt === "x" ? v.toFixed(2) : row.fmt === "h" ? v + " h" : v);
    const rows = D.comparison.map((r) => `<tr><td>${esc(r.label)}</td><td class="${r.better === "a" ? "win pos" : ""}">${esc(f(r, r.a))}</td><td class="${r.better === "b" ? "win pos" : ""}">${esc(f(r, r.b))}</td></tr>`).join("");
    const rv = (t) => t.trades.filter((x) => ["win", "loss", "breakeven"].includes(x.outcome)).map((x) => x.r);
    const diff = D.derived.trades.map((d, i) => [D.replica.trades[i], d]).filter(([a, b]) => a && Math.abs((a.r || 0) - (b.r || 0)) > 0.01).slice(-30).reverse();
    $("#compare").innerHTML = `
      <h1 class="large">Replica vs Chento+</h1>
      <p class="subtitle">Stessi segnali, stesso rischio per trade (${D.config.risk_pct}%). Chento+ impara i filtri solo dai trade già chiusi (walk-forward, nessun lookahead).</p>
      <div class="grid g-21">
        <div class="card"><h3>Equity</h3><div class="legend"><span><i style="background:${C.a()}"></i>Replica Chento</span><span><i style="background:${C.b()}"></i>Chento+</span></div>
          ${lineChart([{ name: "Replica", color: C.a(), points: curve(R) }, { name: "Chento+", color: C.b(), points: curve(X) }], { height: 260 })}</div>
        <div class="card flush"><table><thead><tr><th>Metrica</th><th>Replica</th><th>Chento+</th></tr></thead><tbody>${rows}</tbody></table></div>
      </div>
      <div class="grid g-2" style="margin-top:12px">
        <div class="card"><h3>Replica Chento — regole</h3><ul class="rules">
          <li>Ingresso sui suoi livelli (limit / stop-entry), a mercato se non indicati</li>
          <li>Suo SL; se assente SL stimato a 1.5×ATR</li><li>Uscite equidistribuite su tutti i suoi target</li>
          <li>Applica i suoi update: BE, parziali, chiusure</li></ul></div>
        <div class="card"><h3>Chento+ — regole</h3><ul class="rules">
          <li>Salta R:R &lt; 1.5, segnali ambigui e ingressi inseguiti (&gt; 50% verso TP1)</li>
          <li>Salta simboli e sessioni con expectancy storica negativa</li>
          <li>50% a TP1 e SL a breakeven, resto sull'ultimo target</li>
          <li>TP implicito a 2R se mancano target · SL 1.2×ATR se manca</li></ul></div>
      </div>
      <h2>Distribuzione dei risultati (R)</h2>
      <div class="card"><div class="legend"><span><i style="background:${C.a()}"></i>Replica</span><span><i style="background:${C.b()}"></i>Chento+</span></div>
        ${histogram([{ name: "Replica", color: C.a(), values: rv(D.replica) }, { name: "Chento+", color: C.b(), values: rv(D.derived) }])}</div>
      <h2>Dove divergono</h2>
      <div class="card flush">${table(diff, [["Segnale", ([a]) => `${dt(a.ts)} · ${a.symbol} ${a.side}`], ["Replica", ([a]) => fmtR(a.r), ([a]) => cls(a.r)], ["Chento+", ([, b]) => (b.outcome === "skipped" ? "saltato" : fmtR(b.r)), ([, b]) => cls(b.r)], ["Δ", ([a, b]) => fmtR((b.r || 0) - (a.r || 0)), ([a, b]) => cls((b.r || 0) - (a.r || 0))], ["Motivo", ([, b]) => (b.outcome === "skipped" ? (b.reasons || []).join("; ") : "gestione BE/parziali"), null, "wrap"]])}</div>`;
  }

  /* ---------------- alerts ---------------- */
  function renderAlerts() {
    const list = D.alerts;
    const card = (a) => {
      const k = a.verdict === "PRENDI" ? "take" : a.verdict === "SALTA" ? "skip" : a.kind === "update" ? "update" : "";
      return `<article class="card alert ${k}"><span class="stripe"></span><div>
        <div class="title">${esc(a.title)} ${a.symbol ? `<span class="pill">${esc(a.symbol)}</span>` : ""} ${a.verdict ? `<span class="pill ${a.verdict === "PRENDI" ? "green" : "orange"}">${a.verdict}</span>` : ""}<span class="muted" style="font-weight:400;font-size:13px;margin-left:auto">${dt(a.ts)}</span></div>
        <div class="body">${esc(a.summary)}</div>
        ${a.reasons ? `<div class="body">Motivi: ${esc(a.reasons.join(" · "))}</div>` : ""}
        ${a.position_pct ? `<div class="body">Size suggerita: <b>${a.position_pct}%</b> del conto (rischio ${D.config.risk_pct}%, stop ${a.stop_pct}%)${a.price_now ? ` · prezzo all'alert ${fmtN(a.price_now, 6)} (${a.distance_pct > 0 ? "+" : ""}${a.distance_pct}% dall'entry)` : ""}</div>` : ""}
        ${a.ai_analysis ? `<div class="analysis">${esc(a.ai_analysis)}</div>` : ""}
      </div></article>`;
    };
    $("#alerts").innerHTML = `
      <h1 class="large">Alert</h1>
      <p class="subtitle">Un alert per ogni messaggio di Chento: segnale, contesto storico e verdetto Chento+. In tempo reale con <code>python -m chento watch</code> (anche su webhook Discord).</p>
      ${list.length ? list.slice(0, 100).map(card).join("") : `<div class="empty">Nessun alert</div>`}`;
  }

  /* ---------------- init ---------------- */
  renderOverview(); renderStrategy(); renderFeed(); renderCompare(); renderAlerts();
  document.addEventListener("click", (e) => {
    if (e.target.matches(".thumbs img")) { const lb = $("#lightbox"); lb.querySelector("img").src = e.target.src; lb.hidden = false; }
    else if (e.target.closest("#lightbox")) $("#lightbox").hidden = true;
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#lightbox").hidden = true; });
  let start = "overview";
  try { start = localStorage.getItem("chento-tab") || start; } catch (e) { /* storage non disponibile */ }
  if (document.getElementById(start)) show(start);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { renderOverview(); renderStrategy(); renderCompare(); });
})();
