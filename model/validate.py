"""第六階段：模型驗證。

1. 首例日：模型 vs 兩個不用模型的基準方法（訓練組 / 測試組分開）
     基準 A「中位數」：所有國家都猜訓練組首例日的中位數
     基準 B「航線迴歸」：用「從中國飛來的航線數（log）」對首例日做線性迴歸（只用訓練組擬合）
2. 各洲首例日誤差
3. 隨機模擬 N 次（航班移入改為 Poisson 抽樣）：各國首例日的 10%–90% 範圍、真實值落在範圍內的比例
4. 敏感度分析：每個參數調低 / 調高，看首例日中位數平移幾天、最早 30 國誤差變多少

輸出：data/model_output/validation_*.csv、validation_summary.json
用法：python model/validate.py [--runs 50]
"""
import argparse
import copy
import json

import numpy as np
import pandas as pd

import calibrate
import seir

EXCL = ["CHN", "CHN-HUB"]

SENS = [  # (名稱, 參數路徑, 調低值的倍數或函數, 調高)
    ("R0", "epidemiology.R0", 0.8, 1.2),
    ("防疫措施效果 k", "epidemiology.policy_effect_world", 0.8, 1.2),
    ("每航線旅客數", "travel.passengers_per_route_per_day", 0.5, 2.0),
    ("經中國轉機比例", "travel.hubei_transit_fraction", 0.5, 2.0),
    ("入境旅客驗出率", "reporting.import_ratio", 0.5, 2.0),
    ("初期通報率", "reporting.ratio_early", 0.5, 2.0),
    ("封城減少移動", "lockdown.wuhan_travel_reduction", 0.85 / 0.95, 0.99 / 0.95),
    ("湖北起始感染數", "origin.seed_infected", 1, 5),
    ("感染到確診延遲", "reporting.delay_days", 6 / 8, 10 / 8),
]


def get(p, path):
    a, b = path.split(".")
    return p[a][b]


def put(p, path, v):
    q = copy.deepcopy(p)
    a, b = path.split(".")
    q[a][b] = v
    return q


def first_days(res):
    return np.where(res.detect_day >= 0, res.detect_day, np.nan).astype(float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=50)
    args = ap.parse_args()

    p = seir.load_params()
    inp = seir.load_inputs(p)
    d0 = inp.dates[0]
    nodes = np.array(inp.nodes)
    obs = np.array([(x - d0).days if pd.notna(x) else np.nan for x in inp.obs_first], dtype=float)
    valid = ~np.isin(nodes, EXCL) & ~np.isnan(obs) & (obs <= (pd.Timestamp(calibrate.TEST_END) - d0).days)
    train = valid & (obs <= (pd.Timestamp(calibrate.TRAIN_END) - d0).days)
    test = valid & ~train
    fc = pd.read_csv(seir.PROC / "first_cases.csv").set_index("iso3")["continent"]
    cont = np.array([fc.get(x, None) for x in nodes], dtype=object)
    OUT = seir.OUT
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}

    # ---------------------------------------------------------- 1. 模型 vs 基準
    base = seir.simulate(p, inp, flow_min=None)
    sim = first_days(base)
    routes_cn = inp.routes[[inp.idx("CHN"), inp.idx("CHN-HUB")]].sum(axis=0)
    xr = np.log1p(routes_cn)
    slope, icpt = np.polyfit(xr[train], obs[train], 1)
    preds = {
        "模型（校準後 SEIR）": sim,
        "基準 B：只看與中國的航線數": icpt + slope * xr,
        "基準 A：一律猜中位數": np.full(len(nodes), np.median(obs[train])),
    }
    rows = []
    for name, pr in preds.items():
        for g, mask in [("訓練組（2/29 前首例）", train), ("測試組（3 月首例）", test)]:
            e = pr[mask] - obs[mask]
            hit = ~np.isnan(e)
            rows.append({"method": name, "group": g, "n": int(mask.sum()), "predicted": int(hit.sum()),
                         "mae_days": round(float(np.nanmean(np.abs(e))), 1),
                         "within14": round(float((np.abs(e[hit]) <= 14).sum() / mask.sum()), 3),
                         "spearman": round(float(pd.Series(pr[mask]).rank().corr(pd.Series(obs[mask]).rank())), 2)
                         if np.nanstd(pr[mask]) > 0 else None})
    bench = pd.DataFrame(rows)
    bench.to_csv(OUT / "validation_benchmark.csv", index=False)
    summary["benchmark"] = rows
    print(bench.to_string(index=False))

    # ---------------------------------------------------------- 2. 各洲
    crow = []
    for c in ["Asia", "Europe", "Africa", "North America", "South America", "Oceania"]:
        m = valid & (cont == c)
        e = sim[m] - obs[m]
        hit = ~np.isnan(e)
        crow.append({"continent": c, "n": int(m.sum()), "predicted": int(hit.sum()),
                     "mae_days": round(float(np.nanmean(np.abs(e))), 1), "bias_days": round(float(np.nanmean(e)), 1),
                     "within14": round(float((np.abs(e[hit]) <= 14).sum() / max(m.sum(), 1)), 3)})
    cdf = pd.DataFrame(crow)
    cdf.to_csv(OUT / "validation_by_continent.csv", index=False)
    summary["by_continent"] = crow
    print(cdf.to_string(index=False))

    # ---------------------------------------------------------- 3. 隨機模擬
    runs = np.full((args.runs, len(nodes)), np.nan)
    for k in range(args.runs):
        runs[k] = first_days(seir.simulate(p, inp, stochastic=True, seed=k, flow_min=None))
    reached = (~np.isnan(runs)).mean(axis=0)
    filled = np.where(np.isnan(runs), len(inp.dates) + 14, runs)
    q10, q50, q90 = (np.percentile(filled, q, axis=0) for q in (10, 50, 90))
    ens = pd.DataFrame({"iso3": nodes, "obs_day": obs, "det_day": sim, "p10": q10, "p50": q50, "p90": q90,
                        "reached_share": reached, "continent": cont})
    for col in ["obs_day", "det_day", "p10", "p50", "p90"]:
        ens[col.replace("_day", "") + "_date"] = [(d0 + pd.Timedelta(days=int(v))).date().isoformat()
                                                  if pd.notna(v) and v < len(inp.dates) else None for v in ens[col]]
    ens = ens[valid]
    cover = float(((ens["obs_day"] >= ens["p10"]) & (ens["obs_day"] <= ens["p90"])).mean())
    width = float((ens["p90"] - ens["p10"]).median())
    ens.to_csv(OUT / "validation_ensemble.csv", index=False)
    summary["ensemble"] = {"runs": args.runs, "coverage_p10_p90": round(cover, 3), "median_width_days": width}
    print(f"隨機模擬 {args.runs} 次：真實首例日落在 10–90% 範圍內的比例 {cover:.0%}，範圍寬度中位數 {width:.0f} 天")

    # ---------------------------------------------------------- 4. 敏感度
    base_score = seir.first_case_score(seir.to_tables(base)["sim_first_cases"])["mae_days"]
    srows = []
    for label, path, lo, hi in SENS:
        v0 = get(p, path)
        for side, mult in [("low", lo), ("high", hi)]:
            v = v0 * mult
            if path == "origin.seed_infected":
                v = max(1, round(v))
            if path == "reporting.delay_days":
                v = int(round(v))
            if path == "lockdown.wuhan_travel_reduction":
                v = min(v, 0.99)
            r = seir.simulate(put(p, path, v), inp, flow_min=None)
            f = first_days(r)
            m = valid & ~np.isnan(f) & ~np.isnan(sim)
            shift = float(np.median(f[m] - sim[m])) if m.any() else np.nan
            sc = seir.first_case_score(seir.to_tables(r)["sim_first_cases"])
            srows.append({"param": label, "path": path, "side": side, "value": round(float(v), 4),
                          "base_value": v0, "median_shift_days": shift,
                          "top30_mae": round(sc["mae_days"], 1), "top30_mae_change": round(sc["mae_days"] - base_score, 1),
                          "reached_by_0331": int(((f <= (pd.Timestamp('2020-03-31') - d0).days) & valid).sum())})
    sdf = pd.DataFrame(srows)
    sdf.to_csv(OUT / "validation_sensitivity.csv", index=False)
    summary["sensitivity_base_top30_mae"] = base_score
    print(sdf[["param", "side", "value", "median_shift_days", "top30_mae", "reached_by_0331"]].to_string(index=False))

    # ---------------------------------------------------------- 曲線
    # 確診曲線（直接用參數檔的值，不重新擬合通報率）：中國以外總和、各地區、各國 4/30
    cases = pd.read_csv(seir.PROC / "cases_daily.csv", usecols=["date", "iso3", "cum_confirmed"], parse_dates=["date"])
    oc = cases.pivot(index="date", columns="iso3", values="cum_confirmed").reindex(index=inp.dates, columns=inp.nodes).fillna(0).to_numpy()
    t430 = inp.dates.get_loc(pd.Timestamp(calibrate.CURVE_END))
    out_mask = ~np.isin(nodes, EXCL)
    wm, wo = base.reported_cum[:, out_mask].sum(axis=1), oc[:, out_mask].sum(axis=1)
    cm = (wo >= 10) & (np.arange(len(wo)) <= t430)
    reg = np.array(inp.region)
    regs = {r: round(float(base.reported_cum[t430, out_mask & (reg == r)].sum() / max(oc[t430, out_mask & (reg == r)].sum(), 1)), 2)
            for r in calibrate.REGIONS}
    ok = out_mask & (oc[t430] >= 10)
    ratio_c = (base.reported_cum[t430, ok] + 1) / (oc[t430, ok] + 1)
    summary["curves"] = {
        "outside_china_mape": round(float(np.mean(np.abs(wm[cm] - wo[cm]) / wo[cm])), 3),
        "outside_china_ratio_0430": round(float(wm[t430] / wo[t430]), 2),
        "region_ratio_0430": regs,
        "countries_with_10plus_cases": int(ok.sum()),
        "countries_within_2x_0430": round(float(np.mean((ratio_c >= 0.5) & (ratio_c <= 2))), 3),
    }
    print("確診曲線：", summary["curves"])
    (OUT / "validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成：data/model_output/validation_*.csv、validation_summary.json")


if __name__ == "__main__":
    main()
