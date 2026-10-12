/* 全球分區 SEIR 模型 —— model/seir.py 的 JavaScript 版本（決定性模式）。
 * 預設參數下兩者結果一致，由 tests/test_js_parity.py 檢查。
 * 在瀏覽器中提供全域物件 SimCore；在 Node 中可用 require() 載入。
 *
 * 網頁版多了兩個情境參數（Python 版沒有，預設不啟用，不影響一致性）：
 *   scen.intlCutDay / scen.intlCutKeep：從某天起國際航班只保留一定比例
 *   scen.origin：病毒起點（預設湖北）；湖北特有的設定（陸路、轉機、封城、通報率爬升）仍套在湖北
 */
(function (root) {
  "use strict";
  const HUB = "CHN-HUB", CHN = "CHN";

  function dayOf(D, iso) {
    return Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(D.start + "T00:00:00Z")) / 864e5);
  }

  function prepare(D) {
    if (D._prep) return D._prep;
    const n = D.nodes.length, idx = {};
    D.nodes.forEach((x, i) => { idx[x.iso3] = i; });
    const routes = new Float64Array(n * n);
    for (const [j, i, c] of D.routes) routes[j * n + i] = c;
    const N = Float64Array.from(D.nodes, x => x.N);
    D._prep = { n, idx, routes, N };
    return D._prep;
  }

  function buildTravel(D, P) {
    const { n, idx, routes } = prepare(D);
    const tr = P.travel, pax = tr.passengers_per_route_per_day;
    const t = new Float64Array(n * n);
    for (let k = 0; k < n * n; k++) t[k] = routes[k] * pax;
    const hub = idx[HUB], chn = idx[CHN];
    if (hub !== undefined && chn !== undefined) {
      const g = tr.hubei_china_ground_per_day;
      t[hub * n + chn] += g;
      t[chn * n + hub] += g;
      const f = tr.hubei_transit_fraction || 0;
      for (let i = 0; i < n; i++) {
        if (i === hub || i === chn) continue;
        t[hub * n + i] += f * t[chn * n + i];
        t[chn * n + i] *= 1 - f;
      }
      for (let i = 0; i < n; i++) {
        if (i === hub || i === chn) continue;
        t[i * n + hub] += f * t[i * n + chn];
        t[i * n + chn] *= 1 - f;
      }
    }
    return t;
  }

  function simulate(D, P, scen) {
    scen = scen || {};
    const { n, idx, N } = prepare(D);
    const T = D.T, ep = P.epidemiology, tr = P.travel, rp = P.reporting, lk = P.lockdown;
    const sigma = 1 / ep.latent_days, gamma = 1 / ep.infectious_days, beta0 = ep.R0 * gamma;
    const steps = Math.round(P.simulation.steps_per_day), dt = 1 / steps;
    const hub = idx[HUB], chn = idx[CHN];
    const o = idx[scen.origin || P.origin.node];
    const travel = buildTravel(D, P);
    // 只處理有航線的節點對（約 4,500 / 38,809），結果與完整矩陣相同
    const nzStart = new Int32Array(n + 1), nzList = [];
    for (let j = 0; j < n; j++) {
      nzStart[j] = nzList.length;
      for (let i = 0; i < n; i++) if (travel[j * n + i] !== 0) nzList.push(i);
    }
    nzStart[n] = nzList.length;
    const nzI = Int32Array.from(nzList), nzRate = new Float64Array(nzI.length);

    const S = Float64Array.from(N), E = new Float64Array(n), I = new Float64Array(n), R = new Float64Array(n);
    const out = {};
    for (const k of ["S", "E", "I", "R", "newInf", "imports"]) out[k] = new Float64Array(T * n);
    const arrived = new Uint8Array(n), arrival = new Int32Array(n).fill(-1);
    const cumImport = new Float64Array(n), source = new Float64Array(n * n);
    const flows = [], flowMin = scen.flowMin === undefined ? 0.2 : scen.flowMin;

    const seedDay = dayOf(D, P.origin.seed_date), lockDay = dayOf(D, lk.wuhan_date);
    const traceDay = dayOf(D, rp.testing_start || D.start);
    const inboundMap = [0, 1, 2, 3, 4].map(l => tr.inbound_by_c8_level[l]);
    const k = new Float64Array(n).fill(ep.policy_effect_world ?? ep.policy_effect);
    if (hub !== undefined) k[hub] = ep.policy_effect;
    const traceC = ep.tracing_reduction || 0;
    const traceCap = Float64Array.from(N, x => (ep.tracing_capacity_per_million || 0) * x / 1e6);
    if (hub !== undefined) traceCap[hub] = 0;
    const Ntr = Float64Array.from(N);
    if (hub !== undefined && P.origin.travel_population) Ntr[hub] = Math.min(N[hub], P.origin.travel_population);
    const itf = tr.infectious_travel_factor, thr = tr.arrival_threshold;
    const cutDay = scen.intlCutDay === undefined ? Infinity : scen.intlCutDay, cutKeep = scen.intlCutKeep ?? 1;

    const beta = new Float64Array(n), newD = new Float64Array(n);
    const kS = [0, 0, 0, 0].map(() => new Float64Array(n)), kE = kS.map(() => new Float64Array(n));
    const kI = kS.map(() => new Float64Array(n)), kInf = kS.map(() => new Float64Array(n));
    const kR = kS.map(() => new Float64Array(n));
    const tS = new Float64Array(n), tE = new Float64Array(n), tI = new Float64Array(n);
    const outM = new Float64Array(n), inM = new Float64Array(n);
    const rowOut = new Float64Array(n), colIn = new Float64Array(n), rowOutE = new Float64Array(n);
    const colInE = new Float64Array(n), rowOutI = new Float64Array(n), colInI = new Float64Array(n);

    function f(s, e, i, q) {
      for (let x = 0; x < n; x++) {
        const inf = beta[x] * s[x] * i[x] / N[x];
        kS[q][x] = -inf; kE[q][x] = inf - sigma * e[x]; kI[q][x] = sigma * e[x] - gamma * i[x];
        kR[q][x] = gamma * i[x]; kInf[q][x] = inf;
      }
    }

    for (let t = 0; t < T; t++) {
      if (o !== undefined && t === seedDay) {
        const x = P.origin.seed_infected;
        S[o] -= x; I[o] += x; arrived[o] = 1; arrival[o] = t;
      }
      for (let x = 0; x < n; x++) {
        const si = D.si[x][t];
        let b = beta0 * Math.max(1 - k[x] * si / 100, 0) * arrived[x];
        if (traceC > 0 && t >= traceDay) b = b * (1 - traceC * traceCap[x] / (traceCap[x] + I[x] + 1e-12));
        beta[x] = b;
      }
      newD.fill(0);
      for (let st = 0; st < steps; st++) {
        f(S, E, I, 0);
        for (let x = 0; x < n; x++) { tS[x] = S[x] + dt / 2 * kS[0][x]; tE[x] = E[x] + dt / 2 * kE[0][x]; tI[x] = I[x] + dt / 2 * kI[0][x]; }
        f(tS, tE, tI, 1);
        for (let x = 0; x < n; x++) { tS[x] = S[x] + dt / 2 * kS[1][x]; tE[x] = E[x] + dt / 2 * kE[1][x]; tI[x] = I[x] + dt / 2 * kI[1][x]; }
        f(tS, tE, tI, 2);
        for (let x = 0; x < n; x++) { tS[x] = S[x] + dt * kS[2][x]; tE[x] = E[x] + dt * kE[2][x]; tI[x] = I[x] + dt * kI[2][x]; }
        f(tS, tE, tI, 3);
        for (let x = 0; x < n; x++) {
          const dS = dt / 6 * (kS[0][x] + 2 * kS[1][x] + 2 * kS[2][x] + kS[3][x]);
          const dE = dt / 6 * (kE[0][x] + 2 * kE[1][x] + 2 * kE[2][x] + kE[3][x]);
          const dI = dt / 6 * (kI[0][x] + 2 * kI[1][x] + 2 * kI[2][x] + kI[3][x]);
          const dInf = dt / 6 * (kInf[0][x] + 2 * kInf[1][x] + 2 * kInf[2][x] + kInf[3][x]);
          const dR = dt / 6 * (kR[0][x] + 2 * kR[1][x] + 2 * kR[2][x] + kR[3][x]);
          S[x] += dS; E[x] += dE; I[x] += dI; R[x] += dR; newD[x] += dInf;
        }
      }
      for (let x = 0; x < n; x++) { if (S[x] < 0) S[x] = 0; if (E[x] < 0) E[x] = 0; if (I[x] < 0) I[x] = 0; }

      // ---- 航班移動
      outM.fill(1);
      if (hub !== undefined && t >= lockDay) outM[hub] = 1 - lk.wuhan_travel_reduction;
      for (let i = 0; i < n; i++) {
        const lv = Math.min(Math.max(Math.trunc(D.c8[i][t]), 0), 4);
        inM[i] = inboundMap[lv];
      }
      if (hub !== undefined && t >= lockDay) inM[hub] *= 1 - lk.wuhan_travel_reduction;
      const cut = t >= cutDay;
      for (let j = 0; j < n; j++) {
        let tot = 0;
        const base = j * n;
        for (let q = nzStart[j]; q < nzStart[j + 1]; q++) {
          const i = nzI[q];
          let r = travel[base + i] * outM[j] * inM[i] / Ntr[j];
          if (cut && !((j === hub && i === chn) || (j === chn && i === hub))) r *= cutKeep;
          nzRate[q] = r; tot += r;
        }
        if (tot > 0.5) { const sc = 0.5 / Math.max(tot, 1e-12); for (let q = nzStart[j]; q < nzStart[j + 1]; q++) nzRate[q] *= sc; }
      }
      rowOutE.fill(0); colInE.fill(0); rowOutI.fill(0); colInI.fill(0); rowOut.fill(0); colIn.fill(0);
      const pending = Uint8Array.from(arrived, a => 1 - a);
      for (let j = 0; j < n; j++) {
        if (E[j] === 0 && I[j] === 0) continue;
        const base = j * n;
        for (let q = nzStart[j]; q < nzStart[j + 1]; q++) {
          const i = nzI[q], r = nzRate[q];
          if (r === 0) continue;
          const me = r * E[j], mi = r * I[j] * itf, m = me + mi;
          rowOutE[j] += me; colInE[i] += me; rowOutI[j] += mi; colInI[i] += mi;
          rowOut[j] += m; colIn[i] += m;
          if (pending[i]) source[base + i] += m;
          if (m >= flowMin) flows.push([t, j, i, m]);
        }
      }
      for (let x = 0; x < n; x++) {
        E[x] += colInE[x] - rowOutE[x];
        I[x] += colInI[x] - rowOutI[x];
        S[x] += rowOut[x] - colIn[x];
        if (S[x] < 0) S[x] = 0;
        cumImport[x] += colIn[x];
        if (pending[x] && cumImport[x] >= thr) { arrived[x] = 1; arrival[x] = t; }
      }
      const b = t * n;
      for (let x = 0; x < n; x++) {
        out.S[b + x] = S[x]; out.E[b + x] = E[x]; out.I[b + x] = I[x]; out.R[b + x] = R[x];
        out.newInf[b + x] = newD[x]; out.imports[b + x] = colIn[x];
      }
    }

    const rep = applyReporting(D, P, out.newInf, out.imports);
    return { ...out, reported: rep.reported, detect: rep.detect, arrival, source, flows, n, T, origin: o };
  }

  function applyReporting(D, P, newInf, imports) {
    const { n, idx } = prepare(D);
    const T = D.T, rp = P.reporting, hub = idx[HUB];
    const a = dayOf(D, rp.hubei_ramp_start), b = dayOf(D, rp.hubei_ramp_end);
    const lag = rp.delay_days, lagI = rp.import_delay_days ?? lag;
    const iratio = rp.import_ratio ?? rp.ratio_default, test0 = dayOf(D, rp.testing_start || D.start);
    const reported = new Float64Array(T * n), detect = new Int32Array(n).fill(-1);
    const acc = new Float64Array(n), thr = rp.detect_threshold;
    for (let t = 0; t < T; t++) {
      const w = Math.min(Math.max((t - a) / Math.max(b - a, 1), 0), 1);
      for (let x = 0; x < n; x++) {
        if (t >= test0) {
          const ratio = x === hub ? rp.ratio_hubei_early + w * (rp.ratio_hubei - rp.ratio_hubei_early) : rp.ratio_default;
          const loc = t - lag >= 0 ? newInf[(t - lag) * n + x] * ratio : 0;
          const imp = t - lagI >= 0 ? imports[(t - lagI) * n + x] * iratio : 0;
          acc[x] += loc + imp;
        }
        reported[t * n + x] = acc[x];
        if (detect[x] < 0 && acc[x] >= thr) detect[x] = t;
      }
    }
    return { reported, detect };
  }

  /* 擴散路線：每個節點「到達前累計移入」最多的來源 */
  function mainSources(sim) {
    const { n, source } = sim, res = new Array(n);
    for (let i = 0; i < n; i++) {
      let tot = 0, best = -1, bv = 0;
      for (let j = 0; j < n; j++) { const v = source[j * n + i]; tot += v; if (v > bv) { bv = v; best = j; } }
      res[i] = best >= 0 ? { from: best, share: bv / tot } : null;
    }
    return res;
  }

  /* 關鍵擴散時機點（規劃書第 2 節）
   * 輸入：每個節點的首例日 first[i]、推定來源 src[i]、各節點所屬洲、額外事件（政策、全球、本土傳播）
   * 重要度 = 0.5 × 之後 14 天新增受感染國家數（標準化）+ 0.3 × log 人口（標準化）+ 0.2 × 類型權重
   * 「之後新增國家數」：全球事件（WHO 宣告、起點封城）算全球；單一國家的事件只算由該國傳出的國家 */
  const TYPE_W = { policy: 1.0, continent_jump: 0.9, hub: 0.8, local_transmission_start: 0.6, first_case: 0.5 };
  function keyMoments(D, first, src, extra, opts) {
    const { n } = prepare(D);
    const skip = new Set(opts && opts.skip || []);
    const ev = [];
    for (let i = 0; i < n; i++) if (first[i] >= 0 && !skip.has(i)) ev.push({ day: first[i], node: i, type: "first_case", src: src[i] });
    const byCont = {};
    for (let i = 0; i < n; i++) {
      const c = D.nodes[i].cont;
      if (first[i] < 0 || skip.has(i) || !c || c === "亞洲") continue;
      (byCont[c] = byCont[c] || []).push(i);
    }
    for (const [c, arr] of Object.entries(byCont)) {
      const d = Math.min(...arr.map(i => first[i]));
      const tied = arr.filter(i => first[i] === d);
      for (const i of tied) ev.push({ day: d, node: i, type: "continent_jump", desc: `病毒首次到達${c}：${tied.map(nm).join("、")}` });
    }
    const kids = {};
    for (let i = 0; i < n; i++) if (src[i] !== null && src[i] !== undefined && first[i] >= 0) (kids[src[i]] = kids[src[i]] || []).push(first[i]);
    for (const [j, days] of Object.entries(kids)) {
      days.sort((a, b) => a - b);
      for (let q = 4; q < days.length; q++) {
        if (days[q] - days[q - 4] <= 14) { ev.push({ day: days[q], node: +j, type: "hub", desc: `${nm(+j)} 14 天內傳入第 5 個國家` }); break; }
      }
    }
    for (const e of extra) ev.push(e);
    // 重要度
    const firsts = first.map((d, i) => ({ d, i })).filter(x => x.d >= 0);
    const origin = opts && opts.origin;
    const isGlobal = e => e.node === undefined || e.node < 0 || (e.type === "policy" && e.node === origin);
    const logN = D.nodes.map(x => Math.log10(Math.max(x.N, 1))), maxLog = Math.max(...logN);
    for (const e of ev) {
      let down;
      if (isGlobal(e)) down = firsts.filter(x => x.d > e.day && x.d <= e.day + 14).length;
      else down = (kids[e.node] || []).filter(d => d > e.day && d <= e.day + 14).length;
      e.down = down;
      e.popW = e.node >= 0 ? logN[e.node] / maxLog : 1;
    }
    const maxDown = Math.max(1, ...ev.map(e => e.down));
    // 單一國家的政策（如某國禁止入境）權重較低，全球性政策最高
    const w = e => e.type === "policy" ? (isGlobal(e) ? 1.0 : 0.4) : (TYPE_W[e.type] ?? 0.5);
    for (const e of ev) e.score = 0.5 * e.down / maxDown + 0.3 * e.popW + 0.2 * w(e);
    ev.sort((a, b) => a.day - b.day || b.score - a.score);
    return ev;
    function nm(i) { return D.nodes[i].zh || D.nodes[i].name; }
  }

  const api = { simulate, applyReporting, buildTravel, mainSources, keyMoments, dayOf, prepare };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SimCore = api;
})(typeof window !== "undefined" ? window : globalThis);
