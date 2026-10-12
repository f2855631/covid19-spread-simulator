"""第六階段補充：把模擬延長到 2020-06-30，檢查沒拿來校準的 5–6 月。

校準只用到 4/30；這裡用同一組參數往後多跑兩個月，比較歐美主要國家
每日新增確診（7 日平均）的模型值與 JHU 真實值：
  - 4 月、5 月、6 月各月的模型 / 真實比值
  - 每日新增的高峰日（模型 vs 真實）
  - 6/30 累計確診的模型 / 真實比值

輸出：data/model_output/validation_extended.csv、validation_extended_daily.csv、
      docs/fig7_extended_validation.png
用法：python model/validate_extended.py [--end 2020-06-30]
"""
import argparse
import copy
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

import seir

CJK = ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC", "Heiti TC", "Noto Sans CJK JP", "Noto Sans CJK SC"]
have = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [f for f in CJK if f in have] + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False})

# 4–6 月歐美的主要爆發國，加上兩個 5–6 月才升溫的大國作對照
COUNTRIES = [("USA", "美國"), ("ITA", "義大利"), ("ESP", "西班牙"), ("DEU", "德國"), ("FRA", "法國"),
             ("GBR", "英國"), ("BRA", "巴西"), ("RUS", "俄羅斯")]
MONTHS = [("2020-04", "4 月"), ("2020-05", "5 月"), ("2020-06", "6 月")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="2020-06-30")
    args = ap.parse_args()

    p = copy.deepcopy(seir.load_params())
    p["simulation"]["end"] = args.end
    inp = seir.load_inputs(p)
    res = seir.simulate(p, inp)
    dates = inp.dates

    cases = pd.read_csv(seir.PROC / "cases_daily.csv", usecols=["date", "iso3", "cum_confirmed"], parse_dates=["date"])
    obs_cum = cases.pivot(index="date", columns="iso3", values="cum_confirmed").reindex(dates)

    rows, daily = [], []
    for iso, zh in COUNTRIES:
        i = inp.idx(iso)
        mod = pd.Series(np.diff(res.reported_cum[:, i], prepend=0), index=dates).rolling(7).mean()
        obs = obs_cum[iso].diff().clip(lower=0).rolling(7).mean()
        r = {"iso3": iso, "country": zh}
        for m, lab in MONTHS:
            sel = dates.strftime("%Y-%m") == m
            a, b = mod[sel].sum(), obs[sel].sum()
            r[f"ratio_{m}"] = round(a / b, 2) if b > 0 else np.nan
        win = (dates >= "2020-03-01")
        r["peak_model"] = mod[win].idxmax().date().isoformat()
        r["peak_obs"] = obs[win].idxmax().date().isoformat()
        r["peak_diff_days"] = (mod[win].idxmax() - obs[win].idxmax()).days
        r["model_still_rising_at_end"] = bool(mod.iloc[-1] >= 0.95 * mod[win].max())
        last_obs = obs_cum[iso].iloc[-1]
        r["cum_ratio_end"] = round(res.reported_cum[-1, i] / last_obs, 2) if last_obs > 0 else np.nan
        rows.append(r)
        daily.append(pd.DataFrame({"date": dates, "iso3": iso, "model_new_7d": mod.round(1), "obs_new_7d": obs.round(1)}))

    tab = pd.DataFrame(rows)
    tab.to_csv(seir.OUT / "validation_extended.csv", index=False)
    pd.concat(daily).dropna().to_csv(seir.OUT / "validation_extended_daily.csv", index=False)

    # 病例分配：4/30（校準的最後一天）各國累計確診，模型 vs 真實
    t430 = dates.get_loc(pd.Timestamp("2020-04-30"))
    cont = pd.read_csv(seir.PROC / "first_cases.csv", usecols=["iso3", "continent"]).set_index("iso3")["continent"] \
        if "continent" in pd.read_csv(seir.PROC / "first_cases.csv", nrows=0).columns else pd.Series(dtype=str)
    alloc = pd.DataFrame({"model": res.reported_cum[t430], "obs": obs_cum.iloc[t430].reindex(inp.nodes).to_numpy()},
                         index=inp.nodes).fillna(0).drop(["CHN", "CHN-HUB"])
    alloc["continent"] = cont.reindex(alloc.index)
    alloc["ratio"] = (alloc["model"] / alloc["obs"].replace(0, np.nan)).round(3)
    top = alloc.sort_values("model", ascending=False).head(10).index.union(alloc.sort_values("obs", ascending=False).head(10).index)
    alloc.loc[top].sort_values("obs", ascending=False).round({"model": 0, "obs": 0}).rename_axis("iso3").reset_index() \
        .to_csv(seir.OUT / "validation_allocation_0430.csv", index=False)
    by_cont = alloc.groupby("continent")[["model", "obs"]].sum()
    by_cont["model_share"] = (by_cont["model"] / by_cont["model"].sum()).round(3)
    by_cont["obs_share"] = (by_cont["obs"] / by_cont["obs"].sum()).round(3)
    print(by_cont)

    # 匯總：月比值的幾何平均（對數平均，避免高估與低估互相抵銷看不出來；比值下限 0.01）
    summ = {"end": args.end,
            "outside_china_total_ratio_0430": round(float(alloc["model"].sum() / alloc["obs"].sum()), 2),
            "continent_share_0430": by_cont[["model_share", "obs_share"]].to_dict(orient="index")}
    for m, lab in MONTHS:
        v = tab[f"ratio_{m}"].dropna().clip(lower=0.01)
        summ[f"geo_mean_ratio_{m}"] = round(float(np.exp(np.log(v).mean())), 2)
        summ[f"within_2x_{m}"] = int(((v >= 0.5) & (v <= 2)).sum())
    summ["n_countries"] = len(tab)
    summ["median_abs_peak_diff_days"] = float(tab["peak_diff_days"].abs().median())
    summ["still_rising_at_end"] = int(tab["model_still_rising_at_end"].sum())
    (seir.OUT / "validation_extended_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=2), encoding="utf-8")

    # 圖：每國一格，模型 vs 真實每日新增
    fig, axes = plt.subplots(2, 4, figsize=(15, 6.6), sharex=True)
    for ax, (iso, zh) in zip(axes.flat, COUNTRIES):
        d = daily[[c for c, _ in COUNTRIES].index(iso)]
        d = d[d["date"] >= "2020-03-01"]
        ax.plot(d["date"], d["obs_new_7d"], color="#2f6f8f", lw=2, label="真實（JHU）")
        ax.plot(d["date"], d["model_new_7d"], color="#c42f3a", lw=2, label="模型")
        ax.axvspan(pd.Timestamp("2020-05-01"), dates[-1], color="#eef2f1", zorder=0)
        ax.set_title(zh, fontsize=12, loc="left")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.tick_params(labelsize=9)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k" if v >= 1000 else f"{v:.0f}"))
    axes.flat[0].legend(frameon=False, fontsize=9)
    fig.suptitle(f"延長驗證：每日新增確診（7 日平均），灰底 = 校準沒用到的 5/1–{args.end[5:].replace('-', '/')}", fontsize=13, x=0.01, ha="left")
    fig.tight_layout()
    out = seir.ROOT / "docs" / "fig7_extended_validation.png"
    fig.savefig(out, dpi=130)

    pd.set_option("display.width", 200)
    print(tab.to_string(index=False))
    print(json.dumps(summ, ensure_ascii=False, indent=2))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
