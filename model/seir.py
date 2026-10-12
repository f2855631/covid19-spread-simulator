"""全球分區 SEIR 模型（只用 numpy）。

每個節點（國家／地區；湖北獨立為 CHN-HUB）一組 S、E、I、R：
    dS/dt = −β_i(t) S I / N
    dE/dt =  β_i(t) S I / N − σE
    dI/dt =  σE − γI
    dR/dt =  γI
    β_i(t) = R0 × γ × (1 − k × 嚴格指數_i(t) / 100)

每天先用 RK4 算本地傳播，再做一次「航班移動」：潛伏者 E 與（較少的）具傳染力者 I 依航班量
在節點間移動；為了讓每個節點人口不變，移出幾個感染者就移入同數量的易感者（S）。
某節點累計移入感染者未達 arrival_threshold 前，不發生本地傳播（避免 0.001 人也能指數成長）。

用法：
    python model/seir.py                      # 決定性模擬，輸出到 data/model_output/
    python model/seir.py --stochastic --seed 1 # 航班移入改用 Poisson 隨機抽樣
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "model_output"
PARAMS = Path(__file__).with_name("params.yaml")


def load_params(path: Path = PARAMS) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------ 輸入資料
@dataclass
class Inputs:
    nodes: list                 # 節點 ISO3
    N: np.ndarray               # 人口 (n,)
    routes: np.ndarray          # 航線數 routes[j, i] = j → i (n, n)；旅客數在模擬時依參數換算
    dates: pd.DatetimeIndex     # 模擬日期 (T,)
    stringency: np.ndarray      # 嚴格指數 0–100 (T, n)
    c8: np.ndarray              # 入境管制等級 0–4 (T, n)
    obs_first: pd.Series = field(default_factory=pd.Series)  # 觀察到的首例日

    def idx(self, iso3: str) -> int:
        return self.nodes.index(iso3)

    def subset(self, keep: list) -> "Inputs":
        ix = [self.idx(k) for k in keep]
        return Inputs(list(keep), self.N[ix], self.routes[np.ix_(ix, ix)], self.dates,
                      self.stringency[:, ix], self.c8[:, ix], self.obs_first.reindex(keep))


def load_inputs(p: dict) -> Inputs:
    cases = pd.read_csv(PROC / "cases_daily.csv", usecols=["iso3", "population"]).drop_duplicates("iso3")
    cases = cases.dropna()
    nodes = sorted(cases["iso3"])
    N = cases.set_index("iso3").loc[nodes, "population"].to_numpy(float)
    n = len(nodes)
    pos = {k: i for i, k in enumerate(nodes)}

    fm = pd.read_csv(PROC / "flight_matrix.csv")
    fm = fm[fm["from_iso3"].isin(pos) & fm["to_iso3"].isin(pos)]
    routes = np.zeros((n, n))
    routes[fm["from_iso3"].map(pos), fm["to_iso3"].map(pos)] = fm["routes"].to_numpy(float)

    dates = pd.date_range(p["simulation"]["start"], p["simulation"]["end"])
    ox = pd.read_csv(RAW / "oxcgrt" / "OxCGRT_compact_national_v1.csv",
                     usecols=["CountryCode", "Date", "StringencyIndex_Average", "C8EV_International travel controls"])
    ox["Date"] = pd.to_datetime(ox["Date"].astype(str), format="%Y%m%d")
    si = ox.pivot(index="Date", columns="CountryCode", values="StringencyIndex_Average")
    c8 = ox.pivot(index="Date", columns="CountryCode", values="C8EV_International travel controls")
    # 湖北沿用中國全國的政策指標
    for tbl in (si, c8):
        if "CHN" in tbl.columns:
            tbl["CHN-HUB"] = tbl["CHN"]
    si = si.reindex(index=dates, columns=nodes).ffill().fillna(0).to_numpy()
    c8 = c8.reindex(index=dates, columns=nodes).ffill().fillna(0).to_numpy()

    fc = pd.read_csv(PROC / "first_cases.csv", parse_dates=["first_case"]).set_index("iso3")["first_case"]
    return Inputs(nodes, N, routes, dates, si, c8, fc.reindex(nodes))


def build_travel(p: dict, inp: Inputs) -> np.ndarray:
    """依參數把航線數換算成每日旅客數 travel[j, i]；包含湖北 ↔ 中國其他省份的陸路與經中國樞紐轉機。
    放在模擬時才計算，校準調整這些參數才會生效。"""
    tr = p["travel"]
    travel = inp.routes * tr["passengers_per_route_per_day"]
    n = len(inp.nodes)
    o = p["origin"]["node"]
    if o in inp.nodes and "CHN" in inp.nodes:
        hub, chn = inp.idx(o), inp.idx("CHN")
        g = tr["hubei_china_ground_per_day"]
        travel[hub, chn] += g
        travel[chn, hub] += g
        # 轉機：中國國際航線的一部分旅客其實來自湖北（經北京、上海、廣州等樞紐出境）
        f = tr.get("hubei_transit_fraction", 0)
        intl = [i for i in range(n) if i not in (hub, chn)]
        travel[hub, intl] += f * travel[chn, intl]
        travel[chn, intl] *= 1 - f
        travel[intl, hub] += f * travel[intl, chn]
        travel[intl, chn] *= 1 - f
    return travel


# ------------------------------------------------------------------ 模型
@dataclass
class Result:
    inputs: Inputs
    S: np.ndarray
    E: np.ndarray
    I: np.ndarray
    R: np.ndarray
    new_inf: np.ndarray         # 每日本地新增感染 (T, n)
    imports: np.ndarray         # 每日移入感染者 (T, n)
    reported_cum: np.ndarray    # 預期累計確診 (T, n)
    arrival_day: np.ndarray     # 開始本地傳播的日序（-1 = 未到達）
    detect_day: np.ndarray      # 模型首例日序（預期累計確診 ≥ 門檻）
    source_share: np.ndarray    # 到達前累計移入，依來源分 (n, n)：[j, i] = j 對 i 的貢獻
    flows: list                 # 每日 (day, j, i, 移入感染者) 中較大的流量，畫地圖用


def simulate(p: dict, inp: Inputs, stochastic: bool = False, seed: int | None = None,
             flow_min: float | None = 0.05) -> Result:
    """flow_min=None 時不記錄每日流量（校準時用，較快）。"""
    rng = np.random.default_rng(seed)
    ep, tr, rp, lk = p["epidemiology"], p["travel"], p["reporting"], p["lockdown"]
    sigma, gamma = 1 / ep["latent_days"], 1 / ep["infectious_days"]
    beta0 = ep["R0"] * gamma
    T, n = len(inp.dates), len(inp.nodes)
    N = inp.N.copy()
    dt = 1 / p["simulation"]["steps_per_day"]

    S, E, I, R = N.copy(), np.zeros(n), np.zeros(n), np.zeros(n)
    out = {key: np.zeros((T, n)) for key in ["S", "E", "I", "R", "new_inf", "imports"]}
    arrived = np.zeros(n, bool)
    arrival_day = np.full(n, -1)
    cum_import = np.zeros(n)
    source = np.zeros((n, n))
    flows = []

    o = inp.idx(p["origin"]["node"]) if p["origin"]["node"] in inp.nodes else None
    N_travel = N.copy()   # 出行機率的分母；起點用武漢人口（感染集中在武漢）
    if o is not None and p["origin"].get("travel_population"):
        N_travel[o] = min(N[o], p["origin"]["travel_population"])
    seed_day = (pd.Timestamp(p["origin"]["seed_date"]) - inp.dates[0]).days
    lock_day = (pd.Timestamp(lk["wuhan_date"]) - inp.dates[0]).days
    inbound_map = np.array([tr["inbound_by_c8_level"][lv] for lv in range(5)])
    travel = build_travel(p, inp)
    k = np.full(n, ep.get("policy_effect_world", ep["policy_effect"]), dtype=float)
    if o is not None:
        k[o] = ep["policy_effect"]
    trace_c = ep.get("tracing_reduction", 0.0)
    trace_cap = ep.get("tracing_capacity_per_million", 0.0) * N / 1e6
    if o is not None:
        trace_cap[o] = 0.0   # 起點：發現病毒時武漢已大規模擴散，疫調無效
    trace_day = (pd.Timestamp(p["reporting"].get("testing_start", inp.dates[0])) - inp.dates[0]).days

    for t in range(T):
        if o is not None and t == seed_day:
            x = p["origin"]["seed_infected"]
            S[o] -= x
            I[o] += x
            arrived[o], arrival_day[o] = True, t

        # ---- 本地傳播：RK4
        beta = beta0 * np.clip(1 - k * inp.stringency[t] / 100, 0, None) * arrived
        if trace_c > 0 and t >= trace_day:
            beta = beta * (1 - trace_c * trace_cap / (trace_cap + I + 1e-12))
        new = np.zeros(n)
        for _ in range(int(round(1 / dt))):
            def f(s, e, i):
                inf = beta * s * i / N
                return -inf, inf - sigma * e, sigma * e - gamma * i, gamma * i, inf
            k1 = f(S, E, I)
            k2 = f(*(x + dt / 2 * dx for x, dx in zip((S, E, I), k1[:3])))
            k3 = f(*(x + dt / 2 * dx for x, dx in zip((S, E, I), k2[:3])))
            k4 = f(*(x + dt * dx for x, dx in zip((S, E, I), k3[:3])))
            d = [dt / 6 * (a + 2 * b + 2 * c + e_) for a, b, c, e_ in zip(k1, k2, k3, k4)]
            S, E, I, R = S + d[0], E + d[1], I + d[2], R + d[3]
            new += d[4]
        S, E, I = np.clip(S, 0, None), np.clip(E, 0, None), np.clip(I, 0, None)

        # ---- 航班移動
        out_mult = np.ones(n)
        if o is not None and t >= lock_day:
            out_mult[o] = 1 - lk["wuhan_travel_reduction"]
        in_mult = inbound_map[np.clip(inp.c8[t].astype(int), 0, 4)]
        if o is not None and t >= lock_day:
            in_mult[o] *= 1 - lk["wuhan_travel_reduction"]
        rate = travel * out_mult[:, None] * in_mult[None, :] / N_travel[:, None]   # [j, i] 每人每日出行機率
        tot = rate.sum(axis=1, keepdims=True)                                  # 每天最多一半人口出行（防呆）
        rate = np.where(tot > 0.5, rate * 0.5 / np.maximum(tot, 1e-12), rate)
        mE = rate * E[:, None]
        mI = rate * I[:, None] * tr["infectious_travel_factor"]
        if stochastic:
            mE = np.minimum(rng.poisson(mE), mE * 0 + E[:, None])
            mI = np.minimum(rng.poisson(mI), mI * 0 + I[:, None])
        moved = mE + mI
        E += mE.sum(axis=0) - mE.sum(axis=1)
        I += mI.sum(axis=0) - mI.sum(axis=1)
        S += moved.sum(axis=1) - moved.sum(axis=0)   # 與感染者交換等量易感者，人口不變
        S = np.clip(S, 0, None)
        inflow = moved.sum(axis=0)
        cum_import += inflow
        pending = ~arrived
        source[:, pending] += moved[:, pending]
        newly = pending & (cum_import >= tr["arrival_threshold"])
        arrived |= newly
        arrival_day[newly] = t
        if flow_min is not None:
            big = np.argwhere(moved >= flow_min)
            flows += [(t, j, i, moved[j, i]) for j, i in big]

        for key, val in zip(["S", "E", "I", "R", "new_inf", "imports"], [S, E, I, R, new, inflow]):
            out[key][t] = val

    reported, detect_day = apply_reporting(p, inp, out["new_inf"], out["imports"])

    return Result(inp, out["S"], out["E"], out["I"], out["R"], out["new_inf"], out["imports"],
                  reported, arrival_day, detect_day, source, flows)


def reporting_ratio(p: dict, inp: Inputs) -> np.ndarray:
    """每天、每個節點的通報率 ρ (T, n)。湖北從 early 線性升到 late。"""
    rp = p["reporting"]
    T, n = len(inp.dates), len(inp.nodes)
    ratio = np.full((T, n), rp["ratio_default"], dtype=float)
    o = p["origin"]["node"]
    if o in inp.nodes:
        a, b = pd.Timestamp(rp["hubei_ramp_start"]), pd.Timestamp(rp["hubei_ramp_end"])
        w = np.clip((inp.dates - a).days / max((b - a).days, 1), 0, 1)
        ratio[:, inp.idx(o)] = rp["ratio_hubei_early"] + w * (rp["ratio_hubei"] - rp["ratio_hubei_early"])
    return ratio


def apply_reporting(p: dict, inp: Inputs, new_inf: np.ndarray, imports: np.ndarray):
    """預期累計確診：感染後 delay 天才可能被確診，被確診的機率是「確診當天」的通報率。
    移入的感染者（旅客）也可能被驗出。"""
    rp = p["reporting"]
    n = new_inf.shape[1]

    def shift(x, lag):
        return np.vstack([np.zeros((lag, n)), x[:-lag]]) if lag else x

    local = shift(new_inf, rp["delay_days"]) * reporting_ratio(p, inp)
    imported = shift(imports, rp.get("import_delay_days", rp["delay_days"])) * rp.get("import_ratio", rp["ratio_default"])
    can_test = (inp.dates >= pd.Timestamp(rp.get("testing_start", inp.dates[0])))[:, None]
    reported = np.cumsum((local + imported) * can_test, axis=0)
    hit = reported >= rp["detect_threshold"]
    detect_day = np.where(hit.any(axis=0), hit.argmax(axis=0), -1)
    return reported, detect_day


# ------------------------------------------------------------------ 輸出
def to_tables(res: Result) -> dict:
    inp, d = res.inputs, res.inputs.dates
    T, n = len(d), len(inp.nodes)
    daily = pd.DataFrame({
        "date": np.repeat(d, n), "iso3": np.tile(inp.nodes, T),
        **{k: getattr(res, k).ravel().round(3) for k in ["S", "E", "I", "R", "new_inf", "imports"]},
        "reported_cum": res.reported_cum.ravel().round(3),
    })

    def day(x):
        return d[x].date().isoformat() if x >= 0 else None

    rows = []
    for i, iso in enumerate(inp.nodes):
        col = res.source_share[:, i]
        tot = col.sum()
        order = np.argsort(col)[::-1]
        rows.append({
            "iso3": iso, "sim_arrival": day(res.arrival_day[i]), "sim_first_case": day(res.detect_day[i]),
            "obs_first_case": inp.obs_first.iloc[i].date().isoformat() if pd.notna(inp.obs_first.iloc[i]) else None,
            "main_source": inp.nodes[order[0]] if tot > 0 else None,
            "main_share": round(col[order[0]] / tot, 3) if tot > 0 else None,
            "second_source": inp.nodes[order[1]] if tot > 0 and col[order[1]] > 0 else None,
            "second_share": round(col[order[1]] / tot, 3) if tot > 0 and col[order[1]] > 0 else None,
        })
    first = pd.DataFrame(rows)
    first["diff_days"] = (pd.to_datetime(first["sim_first_case"]) - pd.to_datetime(first["obs_first_case"])).dt.days

    flows = pd.DataFrame(res.flows, columns=["t", "j", "i", "infected_travelers"]).astype(
        {"t": int, "j": int, "i": int, "infected_travelers": float})
    flows = pd.DataFrame({"date": d[flows["t"]], "from_iso3": [inp.nodes[j] for j in flows["j"]],
                          "to_iso3": [inp.nodes[i] for i in flows["i"]],
                          "infected_travelers": flows["infected_travelers"].round(3)})
    return {"sim_daily": daily, "sim_first_cases": first, "sim_flows": flows}


def first_case_score(first: pd.DataFrame, top: int = 30) -> dict:
    """成功標準：最早出現病例的 30 個國家，模型首例日平均誤差（天）。"""
    f = first[~first["iso3"].isin(["CHN", "CHN-HUB"])].dropna(subset=["obs_first_case"])
    f = f.sort_values("obs_first_case").head(top)
    miss = f["sim_first_case"].isna().sum()
    diff = f["diff_days"].dropna()
    both = f.dropna(subset=["sim_first_case"])
    rho = pd.to_datetime(both["sim_first_case"]).rank().corr(pd.to_datetime(both["obs_first_case"]).rank())
    return {"n": len(f), "missed": int(miss), "mae_days": float(diff.abs().mean()),
            "bias_days": float(diff.mean()), "spearman": float(rho)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stochastic", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--params", type=Path, default=PARAMS)
    args = ap.parse_args()

    p = load_params(args.params)
    inp = load_inputs(p)
    res = simulate(p, inp, stochastic=args.stochastic, seed=args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    tables = to_tables(res)
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False, date_format="%Y-%m-%d")
    s = first_case_score(tables["sim_first_cases"])
    reached = (res.arrival_day >= 0).sum()
    print(f"模擬 {inp.dates[0]:%Y-%m-%d} 至 {inp.dates[-1]:%Y-%m-%d}，{len(inp.nodes)} 個節點；{reached} 個節點出現本地傳播")
    print(f"最早 {s['n']} 個國家的首例日：平均誤差 {s['mae_days']:.1f} 天、偏差 {s['bias_days']:+.1f} 天、"
          f"排序相關 {s['spearman']:.2f}、未預測到 {s['missed']} 個")
    print(f"輸出：{OUT.relative_to(ROOT)}/sim_daily.csv、sim_first_cases.csv、sim_flows.csv")


if __name__ == "__main__":
    main()
