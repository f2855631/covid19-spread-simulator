/* 個體模擬分頁的畫面：畫城市、居民、機場起飛，以及 SEIR 曲線。 */
(function () {
  "use strict";
  const A = window.AbmCore;
  const canvas = document.getElementById("city"), ctx = canvas.getContext("2d");
  const $ = id => document.getElementById(id);
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let st = null, running = !reduce, raf = 0, W = 760, H = 470, flights = [], lastExp = 0, started = false;

  function size() {
    const box = canvas.parentElement.clientWidth || 760;
    W = box; H = Math.round(box * 0.62);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const X = x => 10 + x * (W - 20), Y = y => 10 + y * (H - 20);

  function restart() {
    st = A.create({ seed: Math.floor(Math.random() * 1e9) });
    st.ctl.mask = +$("a-mask").value; st.ctl.distancing = +$("a-dist").value; st.ctl.travel = +$("a-travel").value;
    flights = []; lastExp = 0;
    $("a-lock").disabled = false; $("a-lock").textContent = "立即封城";
    draw(); stats();
  }

  function draw() {
    const P = A.PLACES, f = css("--font-body");
    ctx.fillStyle = css("--ocean"); ctx.fillRect(0, 0, W, H);
    ctx.font = `12px ${f}`; ctx.textBaseline = "top";
    for (const h of P.homes) {
      ctx.fillStyle = css("--land"); ctx.strokeStyle = css("--border");
      ctx.beginPath(); ctx.roundRect(X(h.x), Y(h.y), h.w * (W - 20), h.h * (H - 20), 6); ctx.fill(); ctx.stroke();
      ctx.fillStyle = css("--muted"); ctx.fillText(h.name, X(h.x) + 6, Y(h.y) + 5);
    }
    const ring = (p, label, strong) => {
      ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), p.r * (W - 20) * 1.15, 0, 2 * Math.PI);
      ctx.fillStyle = css("--land"); ctx.fill(); ctx.strokeStyle = strong ? css("--ink") : css("--border"); ctx.lineWidth = strong ? 1.5 : 1; ctx.stroke(); ctx.lineWidth = 1;
      ctx.fillStyle = strong ? css("--ink") : css("--muted"); ctx.textAlign = "center";
      ctx.fillText(label, X(p.x), Y(p.y) + p.r * (W - 20) * 1.15 + 4); ctx.textAlign = "left";
    };
    P.work.forEach(w => ring(w, w.name, false));
    ring(P.station, P.station.name, false);
    ring(P.airport, (st && st.day >= st.ctl.lockdownDay) ? "機場（停飛）" : P.airport.name, true);
    // 起飛的感染旅客
    const ax = X(P.airport.x), ay = Y(P.airport.y);
    flights = flights.filter(fl => fl.t < 1);
    for (const fl of flights) {
      ctx.strokeStyle = css("--infect"); ctx.globalAlpha = 1 - fl.t; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.quadraticCurveTo(ax + 40, ay - 60 * fl.dir, ax + 40 + 200 * fl.t, ay - 140 * fl.dir * fl.t - 20);
      ctx.stroke(); ctx.globalAlpha = 1; ctx.lineWidth = 1;
      fl.t += 0.03;
    }
    if (!st) return;
    const col = [css("--muted"), css("--event"), css("--infect"), css("--obs")];
    const r = W < 500 ? 1.3 : 1.8;
    for (const s of [0, 3, 1, 2]) {
      ctx.fillStyle = col[s]; ctx.globalAlpha = s === 0 ? 0.55 : 0.95;
      for (let i = 0; i < st.n; i++) if (st.state[i] === s) { ctx.beginPath(); ctx.arc(X(st.x[i]), Y(st.y[i]), s === 2 ? r + 0.6 : r, 0, 6.283); ctx.fill(); }
    }
    ctx.globalAlpha = 1;
    const t = st.tick % A.TICKS, hh = String(Math.floor(t / 2)).padStart(2, "0"), mm = t % 2 ? "30" : "00";
    ctx.fillStyle = css("--ink"); ctx.font = `13px ${css("--font-data")}`; ctx.textAlign = "right";
    ctx.fillText(`第 ${st.day} 天 ${hh}:${mm}`, W - 14, H - 24); ctx.textAlign = "left";
  }

  function stats() {
    const c = A.counts(st), n = st.n;
    $("a-day").textContent = `第 ${st.day} 天`;
    $("a-exp").textContent = st.exported;
    $("a-inf").textContent = c[2];
    $("a-ever").textContent = Math.round(100 * (c[1] + c[2] + c[3]) / n) + "%";
    chart();
  }

  function chart() {
    const el = $("abm-chart"), w = el.clientWidth || 300, h = 160, m = { l: 34, r: 8, t: 8, b: 18 };
    const svg = d3.select(el).attr("viewBox", `0 0 ${w} ${h}`); svg.selectAll("*").remove();
    const hist = st.history, days = Math.max(60, hist.length + 5);
    const x = d3.scaleLinear().domain([0, days]).range([m.l, w - m.r]);
    const y = d3.scaleLinear().domain([0, st.n]).range([h - m.b, m.t]);
    [0, 0.5, 1].forEach(q => {
      svg.append("line").attr("x1", m.l).attr("x2", w - m.r).attr("y1", y(q * st.n)).attr("y2", y(q * st.n)).attr("stroke", "var(--rule)");
      svg.append("text").attr("x", m.l - 4).attr("y", y(q * st.n) + 3).attr("text-anchor", "end").text(Math.round(q * st.n));
    });
    d3.range(0, days - 4, 20).forEach(d => svg.append("text").attr("x", x(d)).attr("y", h - 4).attr("text-anchor", "middle").text(`${d} 天`));
    const series = [["S", "--muted"], ["E", "--event"], ["I", "--infect"], ["R", "--obs"]];
    for (const [k, c] of series) {
      svg.append("path").attr("d", d3.line().x(d => x(d.day)).y(d => y(d[k]))(hist)).attr("fill", "none").attr("stroke", `var(${c})`).attr("stroke-width", k === "I" ? 2.2 : 1.6);
    }
    if (st.ctl.lockdownDay < Infinity) {
      svg.append("line").attr("x1", x(st.ctl.lockdownDay)).attr("x2", x(st.ctl.lockdownDay)).attr("y1", m.t).attr("y2", h - m.b).attr("stroke", "var(--ink)").attr("stroke-dasharray", "3 3");
      svg.append("text").attr("x", x(st.ctl.lockdownDay) + 4).attr("y", m.t + 10).text("封城");
    }
  }

  function loop() {
    if (running && !document.getElementById("tab-abm").hidden) {
      const k = +$("abm-speed").value;
      const before = st.day;
      for (let q = 0; q < k; q++) A.step(st);
      while (st.exported > lastExp) { flights.push({ t: 0, dir: Math.random() < 0.5 ? 1 : -1 }); lastExp++; }
      draw();
      if (st.day !== before) stats();
      if (st.day >= 150) { running = false; $("abm-play").textContent = "▶ 播放"; }
    }
    raf = requestAnimationFrame(loop);
  }

  function init() {
    if (started) { size(); draw(); stats(); return; }
    started = true;
    size(); restart();
    $("abm-play").textContent = running ? "❚❚ 暫停" : "▶ 播放";
    $("abm-play").addEventListener("click", () => { running = !running; $("abm-play").textContent = running ? "❚❚ 暫停" : "▶ 播放"; });
    $("abm-restart").addEventListener("click", restart);
    const bind = (id, out, key, fmt) => $(id).addEventListener("input", e => { st.ctl[key] = +e.target.value; $(out).textContent = fmt(+e.target.value); });
    bind("a-mask", "o-mask", "mask", v => Math.round(v * 100) + "%");
    bind("a-dist", "o-dist", "distancing", v => Math.round(v * 100) + "%");
    bind("a-travel", "o-travel", "travel", v => (v * 100).toFixed(1) + "%");
    $("a-lock").addEventListener("click", () => {
      st.ctl.lockdownDay = st.day + 1;
      $("a-lock").disabled = true; $("a-lock").textContent = `已於第 ${st.day + 1} 天封城`;
    });
    window.addEventListener("resize", () => { if (!document.getElementById("tab-abm").hidden) { size(); draw(); chart(); } });
    raf = requestAnimationFrame(loop);
  }
  window.__showAbm = init;
})();
