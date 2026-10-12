// 用 Node 執行網頁版模型，輸出結果給 tests/test_js_parity.py 比對。
// 用法：node app/parity_check.js app/web_data.json
const fs = require("fs");
const path = require("path");
const SimCore = require(path.join(__dirname, "sim_core.js"));
const D = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const t0 = Date.now();
const sim = SimCore.simulate(D, D.params, { flowMin: Infinity });
const ms = Date.now() - t0;
const n = sim.n, T = sim.T;
const last = Array.from(sim.reported.slice((T - 1) * n, T * n));
const totalInf = Array.from({ length: n }, (_, x) => { let s = 0; for (let t = 0; t < T; t++) s += sim.newInf[t * n + x]; return s; });
process.stdout.write(JSON.stringify({ ms, detect: Array.from(sim.detect), arrival: Array.from(sim.arrival), reportedLast: last, totalInf }));
