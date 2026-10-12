"""全球模擬結果圖：模型預測首例日 vs 真實首例日。

先執行 python model/seir.py 產生 data/model_output/sim_first_cases.csv
輸出：docs/fig5_sim_vs_obs_first_case.png
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

import seir

ROOT = seir.ROOT
CJK = ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC", "Heiti TC", "Noto Sans CJK JP", "Noto Sans CJK SC"]
have = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [f for f in CJK if f in have] + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False})
CONT_COLORS = {"Asia": "#d1495b", "Europe": "#00798c", "North America": "#edae49",
               "South America": "#66a182", "Africa": "#8d6a9f", "Oceania": "#2e4057"}
CONT_ZH = {"Asia": "亞洲", "Europe": "歐洲", "North America": "北美洲",
           "South America": "南美洲", "Africa": "非洲", "Oceania": "大洋洲"}


def main():
    f = pd.read_csv(seir.OUT / "sim_first_cases.csv", parse_dates=["sim_first_case", "obs_first_case"])
    fc = pd.read_csv(seir.PROC / "first_cases.csv").set_index("iso3")["continent"]
    f["continent"] = f["iso3"].map(fc)
    f = f[~f["iso3"].isin(["CHN", "CHN-HUB"])].dropna(subset=["obs_first_case"])
    f = f[f["obs_first_case"] <= "2020-03-31"]
    s = seir.first_case_score(f.assign(sim_first_case=f["sim_first_case"].dt.strftime("%Y-%m-%d"),
                                       obs_first_case=f["obs_first_case"].dt.strftime("%Y-%m-%d")))
    hit = f.dropna(subset=["sim_first_case"])
    within = (hit["diff_days"].abs() <= 14).mean()

    fig, ax = plt.subplots(figsize=(8.5, 8))
    lo, hi = pd.Timestamp("2020-01-10"), pd.Timestamp("2020-05-01")
    ax.fill_between([lo, hi], [lo - pd.Timedelta(days=14), hi - pd.Timedelta(days=14)],
                    [lo + pd.Timedelta(days=14), hi + pd.Timedelta(days=14)], color="#eeeeee", label="誤差 ±14 天")
    ax.plot([lo, hi], [lo, hi], color="#999", linewidth=0.8)
    for c, g in hit.groupby("continent"):
        ax.scatter(g["obs_first_case"], g["sim_first_case"], s=24, color=CONT_COLORS.get(c, "grey"),
                   label=CONT_ZH.get(c, c), edgecolor="white", linewidth=0.5, alpha=0.9)
    for _, r in hit.sort_values("obs_first_case").head(16).iterrows():
        ax.annotate(r["iso3"], (r["obs_first_case"], r["sim_first_case"]), xytext=(4, -3),
                    textcoords="offset points", fontsize=8, color="#333")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("真實首例日")
    ax.set_ylabel("模型預測首例日")
    for a in (ax.xaxis, ax.yaxis):
        a.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_title(f"模型抓得到擴散順序（排序相關 {s['spearman']:.2f}），但整體偏晚 {s['bias_days']:.0f} 天",
                 loc="left", fontsize=13)
    ax.text(0.01, 0.99, f"最早 30 國平均誤差 {s['mae_days']:.1f} 天（目標 ≤ 14 天）\n"
                        f"3/31 前出現病例的 {len(f)} 國中，模型預測到 {len(hit)} 國，{within:.0%} 在 ±14 天內",
            transform=ax.transAxes, fontsize=9, color="#555", va="top")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    fig.tight_layout()
    out = ROOT / "docs" / "fig5_sim_vs_obs_first_case.png"
    fig.savefig(out, dpi=150)
    print(f"圖：{out.relative_to(ROOT)}；預測到 {len(hit)}/{len(f)} 國，{within:.0%} 在 ±14 天內")


if __name__ == "__main__":
    main()
