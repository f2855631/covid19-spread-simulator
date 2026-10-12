/* 個體模擬（Agent-Based Model）示範：一座縮小版的城市。
 * 每個人有家與工作地點，白天出門、晚上回家；感染者靠近易感者時有機率傳染。
 * 有些人會去機場搭機離開 —— 若他已被感染，就是「帶出城的感染者」，
 * 也就是全球模型裡「潛伏者搭機移動」那一項在個人層次的樣子。
 * 只用來示意，參數沒有用真實資料校準；潛伏期與傳染期沿用全球模型（3 天、4.5 天）。
 */
(function (root) {
  "use strict";
  const S = 0, E = 1, I = 2, R = 3;
  const TICKS = 48;            // 一天 48 步（每步 30 分鐘）

  // 城市地圖（座標 0–1）
  const PLACES = {
    homes: [
      { x: 0.06, y: 0.08, w: 0.26, h: 0.34, name: "住宅區" },
      { x: 0.06, y: 0.56, w: 0.26, h: 0.36, name: "住宅區" },
      { x: 0.40, y: 0.62, w: 0.28, h: 0.30, name: "住宅區" },
      { x: 0.40, y: 0.06, w: 0.20, h: 0.22, name: "住宅區" },
    ],
    work: [
      { x: 0.50, y: 0.40, r: 0.06, name: "商辦區" },
      { x: 0.72, y: 0.20, r: 0.05, name: "工業區" },
      { x: 0.36, y: 0.46, r: 0.035, name: "市場" },
    ],
    station: { x: 0.74, y: 0.74, r: 0.035, name: "火車站" },
    airport: { x: 0.92, y: 0.46, r: 0.05, name: "機場" },
  };

  function rng(seed) {
    let s = seed >>> 0 || 1;
    return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
  }

  function create(opts) {
    const o = Object.assign({ n: 2500, seed: 7, seeds: 3, latentDays: 3, infDays: 4.5, pInf: 0.0013, radius: 0.012 }, opts || {});
    const rand = rng(o.seed);
    const n = o.n;
    const st = {
      o, rand, n, tick: 0, day: 0,
      x: new Float32Array(n), y: new Float32Array(n), hx: new Float32Array(n), hy: new Float32Array(n),
      tx: new Float32Array(n), ty: new Float32Array(n), work: new Int8Array(n),
      state: new Uint8Array(n), timer: new Float32Array(n), traveler: new Uint8Array(n), stay: new Uint8Array(n),
      exported: 0, exportedLog: [], history: [], newToday: 0,
      ctl: { mask: 0, distancing: 0, travel: 0.01, lockdownDay: Infinity },
    };
    for (let i = 0; i < n; i++) placeHome(st, i);
    // 第一批感染者在市場附近
    const m = PLACES.work[2];
    for (let k = 0; k < o.seeds; k++) {
      const i = Math.floor(rand() * n);
      st.state[i] = I; st.timer[i] = dur(st, o.infDays); st.work[i] = 2;
      st.x[i] = m.x + (rand() - 0.5) * m.r; st.y[i] = m.y + (rand() - 0.5) * m.r;
    }
    planDay(st);
    record(st);
    return st;
  }

  function placeHome(st, i) {
    const r = st.rand, h = PLACES.homes[Math.floor(r() * PLACES.homes.length)];
    st.hx[i] = st.x[i] = h.x + r() * h.w;
    st.hy[i] = st.y[i] = h.y + r() * h.h;
    const q = r();
    st.work[i] = q < 0.55 ? 0 : q < 0.85 ? 1 : 2;
  }

  function dur(st, mean) { return mean * TICKS * (0.6 + 0.8 * st.rand()); }

  function locked(st) { return st.day >= st.ctl.lockdownDay; }

  function planDay(st) {
    const { n, rand, ctl } = st;
    const out = (1 - 0.7 * ctl.distancing) * (locked(st) ? 0.3 : 1);
    const travel = locked(st) ? ctl.travel * 0.05 : ctl.travel;
    for (let i = 0; i < n; i++) {
      st.stay[i] = rand() > out || st.state[i] === I && rand() < 0.5 ? 1 : 0;  // 一半的發病者留在家
      st.traveler[i] = !st.stay[i] && rand() < travel ? 1 : 0;
    }
    st.newToday = 0;
  }

  function target(st, i, phase) {
    if (phase === 0 || st.stay[i]) return [st.hx[i], st.hy[i]];
    if (st.traveler[i]) return [PLACES.airport.x, PLACES.airport.y];
    const w = PLACES.work[st.work[i]];
    return [w.x + (((i * 7919) % 100) / 100 - 0.5) * w.r * 1.6, w.y + (((i * 104729) % 100) / 100 - 0.5) * w.r * 1.6];
  }

  function step(st) {
    const { n, rand, o, ctl } = st;
    const t = st.tick % TICKS;
    const phase = t >= 14 && t < 36 ? 1 : 0;   // 07:00–18:00 在外
    const jitter = 0.004 * (1 - 0.6 * ctl.distancing);
    // 移動
    for (let i = 0; i < n; i++) {
      const [gx, gy] = target(st, i, phase);
      const dx = gx - st.x[i], dy = gy - st.y[i], d = Math.hypot(dx, dy);
      const sp = Math.min(d, 0.025);
      if (d > 1e-6) { st.x[i] += dx / d * sp; st.y[i] += dy / d * sp; }
      st.x[i] += (rand() - 0.5) * jitter; st.y[i] += (rand() - 0.5) * jitter;
      // 到了機場就搭機離開，換成一位新來的健康居民
      if (st.traveler[i] && phase === 1 && d < 0.02) {
        if (st.state[i] === E || st.state[i] === I) { st.exported++; st.exportedLog.push(st.day); }
        st.state[i] = S; st.timer[i] = 0; st.traveler[i] = 0; st.stay[i] = 1;
        placeHome(st, i);
      }
    }
    // 傳染：用格子加速找鄰居
    const rad = o.radius * (1 - 0.35 * ctl.distancing);
    const cell = rad, G = Math.ceil(1 / cell) + 1;
    const grid = new Map();
    for (let i = 0; i < n; i++) {
      if (st.state[i] !== S) continue;
      const k = Math.floor(st.x[i] / cell) * G + Math.floor(st.y[i] / cell);
      let a = grid.get(k); if (!a) grid.set(k, a = []); a.push(i);
    }
    const p = o.pInf * (1 - 0.5 * ctl.mask) * (1 - 0.5 * ctl.mask);  // 雙方都戴口罩的情形
    for (let i = 0; i < n; i++) {
      if (st.state[i] !== I) continue;
      const cx = Math.floor(st.x[i] / cell), cy = Math.floor(st.y[i] / cell);
      for (let ax = cx - 1; ax <= cx + 1; ax++) for (let ay = cy - 1; ay <= cy + 1; ay++) {
        const a = grid.get(ax * G + ay); if (!a) continue;
        for (const j of a) {
          if (st.state[j] !== S) continue;
          if (Math.hypot(st.x[j] - st.x[i], st.y[j] - st.y[i]) < rad && rand() < p) {
            st.state[j] = E; st.timer[j] = dur(st, o.latentDays); st.newToday++;
          }
        }
      }
    }
    // 病程
    for (let i = 0; i < n; i++) {
      if (st.state[i] === S || st.state[i] === R) continue;
      st.timer[i] -= 1;
      if (st.timer[i] <= 0) {
        if (st.state[i] === E) { st.state[i] = I; st.timer[i] = dur(st, o.infDays); }
        else st.state[i] = R;
      }
    }
    st.tick++;
    if (st.tick % TICKS === 0) { st.day++; record(st); planDay(st); }
  }

  function counts(st) {
    const c = [0, 0, 0, 0];
    for (let i = 0; i < st.n; i++) c[st.state[i]]++;
    return c;
  }
  function record(st) {
    const c = counts(st);
    st.history.push({ day: st.day, S: c[0], E: c[1], I: c[2], R: c[3], exported: st.exported, newInf: st.newToday });
  }

  const api = { create, step, counts, PLACES, TICKS, S, E, I, R };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AbmCore = api;
})(typeof window !== "undefined" ? window : globalThis);
