"""湖北單一區域 SEIR：與 JHU 湖北累計確診疊圖，並做初步網格搜尋。

只模擬湖北一個節點（不含航班），用網格搜尋找出讓「預期累計確診」最貼近真實曲線的
起始感染數、R0、防疫效果 k 與通報率。正式校準在第四階段（model/calibrate.py）。

輸出：
    docs/fig4_hubei_seir_fit.png
    data/model_output/hubei_grid.csv   每組參數的誤差（log 尺度 RMSE）
用法：python model/run_hubei.py [--write-params]   # 加上 --write-params 會把最佳值寫回 params.yaml
"""
import argparse
import copy
import itertools
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

import seir

ROOT = seir.ROOT
DOCS, OUT = ROOT / "docs", seir.OUT
FIT_START, FIT_END = "2020-01-22", "2020-03-31"

# k > 1 代表除了全國性措施外還有額外效果（湖北 2 月起的集中隔離等）；β 最低為 0
# 傳播參數（要重跑模擬）
GRID_DYN = {
    "seed_infected": [1, 3, 10],
    "R0": [2.2, 2.6, 3.0, 3.4],
    "policy_effect": [0.9, 1.0, 1.1, 1.2],
}
# 通報參數（只影響「感染 → 確診」的換算，不必重跑模擬）
GRID_REP = {
    "ratio_hubei_early": [0.01, 0.02, 0.05, 0.1],
    "ratio_hubei": [0.1, 0.2, 0.35, 0.5],
}

CJK = ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC", "Heiti TC", "Noto Sans CJK JP", "Noto Sans CJK SC"]
have = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [f for f in CJK if f in have] + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False})


def with_values(p, v):
    q = copy.deepcopy(p)
    q["origin"]["seed_infected"] = v["seed_infected"]
    q["epidemiology"]["R0"] = v["R0"]
    q["epidemiology"]["policy_effect"] = v["policy_effect"]
    q["reporting"]["ratio_hubei"] = v["ratio_hubei"]
    q["reporting"]["ratio_hubei_early"] = v["ratio_hubei_early"]
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-params", action="store_true")
    args = ap.parse_args()

    p = seir.load_params()
    inp = seir.load_inputs(p).subset(["CHN-HUB"])
    obs = pd.read_csv(seir.PROC / "cases_daily.csv", parse_dates=["date"])
    obs = obs[obs["iso3"] == "CHN-HUB"].set_index("date")["cum_confirmed"]
    obs = obs[obs.index <= inp.dates[-1]]
    window = (inp.dates >= FIT_START) & (inp.dates <= FIT_END)
    y = np.log10(obs.reindex(inp.dates[window]).to_numpy())

    rows = []
    rep_combos = [dict(zip(GRID_REP, c)) for c in itertools.product(*GRID_REP.values())]
    for combo in itertools.product(*GRID_DYN.values()):
        vd = dict(zip(GRID_DYN, combo))
        r = seir.simulate(with_values(p, {**vd, **rep_combos[0]}), inp)
        for vr in rep_combos:
            v = {**vd, **vr}
            rep, _ = seir.apply_reporting(with_values(p, v), inp, r.new_inf, r.imports)
            yhat = np.log10(np.maximum(rep[window, 0], 1))
            rows.append({**v, "rmse_log10": float(np.sqrt(np.mean((yhat - y) ** 2)))})
    grid = pd.DataFrame(rows).sort_values("rmse_log10")
    OUT.mkdir(parents=True, exist_ok=True)
    grid.to_csv(OUT / "hubei_grid.csv", index=False)
    best = grid.iloc[0].to_dict()
    print(f"試了 {len(grid)} 組參數；最佳：起始感染 {best['seed_infected']:.0f} 人、R0 {best['R0']}、"
          f"防疫效果 k {best['policy_effect']}、通報率 {best['ratio_hubei_early']} → {best['ratio_hubei']}"
          f"（log10 RMSE {best['rmse_log10']:.3f}，"
          f"約 ×{10 ** best['rmse_log10']:.2f} 倍誤差）")

    pb = with_values(p, best)
    r = seir.simulate(pb, inp)
    d = inp.dates
    infected = np.cumsum(r.new_inf[:, 0])
    sel = d >= "2020-01-01"

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(d[sel], infected[sel], color="#bbbbbb", linewidth=1.5, label="模型：累計感染（含未確診）")
    ax.plot(d[sel], r.reported_cum[sel, 0], color="#d1495b", linewidth=2.2, label="模型：預期累計確診")
    ax.scatter(obs.index, obs.values, s=10, color="#2e4057", zorder=3, label="真實：JHU 湖北累計確診")
    ax.set_yscale("log")
    ax.set_ylim(10, None)
    ax.axvline(pd.Timestamp(p["lockdown"]["wuhan_date"]), color="#999", linestyle="--", linewidth=0.8)
    ax.text(pd.Timestamp(p["lockdown"]["wuhan_date"]), 20, " 武漢封城", fontsize=9, color="#555")
    ax.annotate("2/12 湖北納入臨床診斷病例", (pd.Timestamp("2020-02-13"), obs.loc["2020-02-13"]),
                xytext=(20, -30), textcoords="offset points", fontsize=8, color="#2e4057",
                arrowprops=dict(arrowstyle="-", color="#2e4057", lw=0.6))
    final_ratio = r.reported_cum[sel, 0][-1] / infected[sel][-1]
    ax.set_title(f"湖北：模型累計感染約為確診的 {1 / final_ratio:.0f} 倍，封城後約兩週曲線趨平",
                 loc="left", fontsize=13)
    ax.set_ylabel("人數（對數刻度）")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.legend(frameon=False, loc="lower right")
    txt = (f"R0 = {best['R0']}　k = {best['policy_effect']}　起始感染 {best['seed_infected']:.0f} 人（{p['origin']['seed_date']}）"
           f"　通報率 {best['ratio_hubei_early']:.0%} → {best['ratio_hubei']:.0%}　誤差 ×{10 ** best['rmse_log10']:.2f}")
    ax.text(0.01, 0.97, txt, transform=ax.transAxes, fontsize=9, color="#555", va="top")
    fig.tight_layout()
    DOCS.mkdir(exist_ok=True)
    fig.savefig(DOCS / "fig4_hubei_seir_fit.png", dpi=150)
    print(f"圖：docs/fig4_hubei_seir_fit.png（模型到 {d[-1]:%m/%d} 累計感染 {infected[sel][-1]:,.0f} 人，確診比例 {final_ratio:.0%}）")

    if args.write_params:
        import re
        path = seir.PARAMS
        s = path.read_text(encoding="utf-8")
        for key, val in [("seed_infected", int(best["seed_infected"])), ("R0", best["R0"]),
                         ("policy_effect", best["policy_effect"]), ("ratio_hubei", best["ratio_hubei"]),
                         ("ratio_hubei_early", best["ratio_hubei_early"])]:
            s = re.sub(rf"(\n\s*{key}:\s*)[0-9.]+", rf"\g<1>{val}", s, count=1)
        path.write_text(s, encoding="utf-8")
        print("已把最佳值寫回 model/params.yaml")


if __name__ == "__main__":
    main()
