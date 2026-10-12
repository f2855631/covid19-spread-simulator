"""校準結果圖：中國以外的確診曲線（模型 vs 真實），並輸出首例日對照表。

先執行 python model/seir.py（使用校準後的 params.yaml）
輸出：
    docs/fig6_calibrated_curve_outside_china.png
    data/model_output/first_case_comparison.csv   各國首例日：真實、模型、誤差、訓練 / 測試組、推定來源
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

import calibrate
import regions
import seir

ROOT = seir.ROOT
CJK = ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC", "Heiti TC", "Noto Sans CJK JP", "Noto Sans CJK SC"]
have = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [f for f in CJK if f in have] + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False})
EXCL = ["CHN", "CHN-HUB"]


def main():
    daily = pd.read_csv(seir.OUT / "sim_daily.csv", parse_dates=["date"])
    sim = daily[~daily["iso3"].isin(EXCL)].groupby("date")["reported_cum"].sum()
    cases = pd.read_csv(seir.PROC / "cases_daily.csv", usecols=["date", "iso3", "cum_confirmed"], parse_dates=["date"])
    obs = cases[~cases["iso3"].isin(EXCL)].groupby("date")["cum_confirmed"].sum().reindex(sim.index)

    a, b = pd.Timestamp("2020-02-15"), pd.Timestamp(calibrate.CURVE_END)
    w = (sim.index >= a) & (sim.index <= b)
    mape = float(np.mean(np.abs(sim[w] - obs[w]) / obs[w]))
    ratio = float(10 ** np.sqrt(np.mean((np.log10(sim[w].clip(lower=1)) - np.log10(obs[w])) ** 2)))

    fig, axes = plt.subplots(1, 3, figsize=(17, 4.8), gridspec_kw={"width_ratios": [1, 1, 0.9]})
    ax = axes[0]
    ax.plot(obs.index, obs, color="#2e4057", linewidth=2.2, label="真實（JHU）")
    ax.plot(sim.index, sim, color="#d1495b", linewidth=2.2, linestyle="--", label="模型（校準後）")
    ax.axvspan(a, b, color="#f2f2f2", zorder=0, label="校準使用的期間")
    ax.set_yscale("log")
    ax.set_ylim(1, None)
    ax.set_xlim(pd.Timestamp("2020-01-15"), sim.index[-1])
    ax.set_ylabel("累計確診（對數刻度）")
    ax.set_title("中國以外累計確診", loc="left", fontsize=12)
    ax.legend(frameon=False, fontsize=9, loc="lower right")

    ax = axes[1]
    nd_obs = obs.diff().rolling(7).mean()
    nd_sim = sim.diff().rolling(7).mean()
    ax.plot(nd_obs.index, nd_obs, color="#2e4057", linewidth=2.2, label="真實")
    ax.plot(nd_sim.index, nd_sim, color="#d1495b", linewidth=2.2, linestyle="--", label="模型")
    ax.set_xlim(pd.Timestamp("2020-02-15"), sim.index[-1])
    ax.set_ylabel("每日新增確診（7 日平均）")
    ax.set_title("中國以外每日新增", loc="left", fontsize=12)
    ax.legend(frameon=False, fontsize=9)
    for ax in axes[:2]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    # 4/30 各地區占中國以外確診的比例：模型 vs 真實
    ax = axes[2]
    reg = pd.Series({k: regions.region_of(k, None) for k in daily["iso3"].unique()})
    last = daily[(daily["date"] == b) & ~daily["iso3"].isin(EXCL)].set_index("iso3")["reported_cum"]
    oc = cases[(cases["date"] == b) & ~cases["iso3"].isin(EXCL)].set_index("iso3")["cum_confirmed"]
    inp_reg = pd.Series(seir.load_inputs(seir.load_params()).region, index=seir.load_inputs(seir.load_params()).nodes)
    ms = last.groupby(inp_reg.reindex(last.index)).sum(); ms = ms / ms.sum()
    os_ = oc.groupby(inp_reg.reindex(oc.index)).sum(); os_ = os_ / os_.sum()
    order = list(regions.REGION_ZH)
    yy = np.arange(len(order))
    ax.barh(yy - 0.2, [os_.get(r, 0) for r in order], height=0.38, color="#2e4057", label="真實")
    ax.barh(yy + 0.2, [ms.get(r, 0) for r in order], height=0.38, color="#d1495b", label="模型")
    ax.set_yticks(yy, [regions.REGION_ZH[r] for r in order], fontsize=9)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_title(f"{b:%m/%d} 各地區占中國以外確診的比例", loc="left", fontsize=12)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.suptitle(f"校準後，模型重現中國以外的疫情規模與地區分布（{a:%m/%d}–{b:%m/%d} 平均誤差 ×{ratio:.2f}，MAPE {mape:.0%}）",
                 x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    out = ROOT / "docs" / "fig6_calibrated_curve_outside_china.png"
    fig.savefig(out, dpi=150)

    f = pd.read_csv(seir.OUT / "sim_first_cases.csv")
    f = f[~f["iso3"].isin(EXCL)].dropna(subset=["obs_first_case"])
    f["group"] = np.where(f["obs_first_case"] <= calibrate.TRAIN_END, "訓練",
                          np.where(f["obs_first_case"] <= calibrate.TEST_END, "測試", "其他"))
    cols = ["iso3", "group", "obs_first_case", "sim_first_case", "diff_days", "main_source", "main_share",
            "second_source", "second_share", "sim_arrival"]
    f.sort_values("obs_first_case")[cols].to_csv(seir.OUT / "first_case_comparison.csv", index=False)
    for g in ["訓練", "測試"]:
        x = f[f["group"] == g]
        d = x["diff_days"].dropna()
        print(f"{g}組 {len(x)} 國：預測到 {len(d)} 國，平均誤差 {d.abs().mean():.1f} 天，"
              f"{(d.abs() <= 14).sum() / len(x):.0%} 在 ±14 天內")
    print(f"中國以外曲線（{a:%m/%d}–{b:%m/%d}）：MAPE {mape:.0%}，平均誤差 ×{ratio:.2f}")
    print(f"圖：{out.relative_to(ROOT)}；表：data/model_output/first_case_comparison.csv")


if __name__ == "__main__":
    main()
