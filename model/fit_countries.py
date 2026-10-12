"""第四階段（第二版）之二：各國傳播倍數。

地區參數（calibrate.py）把各洲的病例比例校準對了，但同一地區內仍差很多：
例如義大利、西班牙只有真實的 2%，俄羅斯、中亞卻高好幾倍。航班網路只決定「病毒什麼時候到」，
到了之後長多快，還取決於各國自己的人口密度、社交習慣、隱性傳播鏈與檢測量，這些資料裡都量不到。

做法：每個國家乘上一個傳播倍數（各國倍數 × 地區 contact），反覆模擬並調整，
讓模型 2020-03-01 至 04-30 的累計確診（對數，4/17–4/30 的平均）貼近 JHU 的數字。
    - 只用到 4/30 的資料；5–6 月與 3 月首例日都不參與，留給 validate.py、validate_extended.py 檢驗
    - 倍數限制在 0.25–3 之間；湖北（起點）不調整
    - 到 4/30 模型都還沒傳入、或真實確診不到 10 例的國家，不調整（倍數 = 1）

輸出：model/country_contact.csv（seir.load_params 會自動讀入）
用法：python model/fit_countries.py [--iters 40]
"""
import argparse
import copy

import numpy as np
import pandas as pd

import seir

WINDOW = ("2020-03-01", "2020-04-30")
MIN_CASES = 10
BOUNDS = (0.25, 3.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=40)
    args = ap.parse_args()

    p = seir.load_params(country=None)
    inp = seir.load_inputs(p)
    d = inp.dates
    cases = pd.read_csv(seir.PROC / "cases_daily.csv", usecols=["date", "iso3", "cum_confirmed"], parse_dates=["date"])
    obs = cases.pivot(index="date", columns="iso3", values="cum_confirmed").reindex(index=d, columns=inp.nodes).fillna(0).to_numpy()
    win = (d >= WINDOW[0]) & (d <= WINDOW[1])
    end = np.where(win)[0][-1]
    o = inp.idx(p["origin"]["node"])

    f = np.ones(len(inp.nodes))
    hist = []
    for it in range(args.iters + 1):
        q = copy.deepcopy(p)
        q["country_contact"] = dict(zip(inp.nodes, f))
        r = seir.simulate(q, inp, flow_min=None)
        m = r.reported_cum
        err = np.full(len(f), np.nan)
        for i in range(len(f)):
            if i == o or r.arrival_day[i] < 0 or obs[end, i] < MIN_CASES:
                continue
            mask = win & (obs[:, i] >= MIN_CASES)
            e = np.log10(m[mask, i] + 1) - np.log10(obs[mask, i] + 1)
            w = np.where(np.arange(len(e)) >= len(e) - 14, 1.0, 0.0)   # 只看最後 14 天（4/17–4/30）
            err[i] = np.sum(w * e) / np.sum(w)
        ok = ~np.isnan(err)
        e430 = np.log10(m[end] + 1) - np.log10(obs[end] + 1)
        hist.append({"iter": it, "n": int(ok.sum()), "median_abs_log10": float(np.median(np.abs(err[ok]))),
                     "within_2x": float(np.mean(np.abs(err[ok]) <= np.log10(2))),
                     "within_2x_0430": float(np.mean(np.abs(e430[ok]) <= np.log10(2)))})
        print(f"第 {it:2d} 輪：{ok.sum()} 國，誤差中位數 ×{10 ** hist[-1]['median_abs_log10']:.2f}，"
              f"±2 倍內 {hist[-1]['within_2x']:.0%}（4/30 累計 ±2 倍內 {hist[-1]['within_2x_0430']:.0%}）")
        if it == 0:
            err0 = err.copy()
        if it == args.iters:
            break
        # 敏感度：傳入後成長的天數越多，倍數的影響越大（約 0.15 × 天數）
        grow = np.maximum(end - np.maximum(r.arrival_day, 0), 1)
        step = -err * np.log(10) / np.maximum(0.15 * grow, 2.0) * 0.7
        step = np.clip(np.nan_to_num(step), -0.3, 0.3)
        f = np.clip(f * np.exp(step), *BOUNDS)

    region_c = seir.region_values(p, inp, "contact", 1.0)
    out = pd.DataFrame({"iso3": inp.nodes, "region": inp.region, "contact": np.round(f, 4),
                        "contact_total": np.round(f * region_c, 4),
                        "obs_0430": obs[end].astype(int), "model_0430": np.round(m[end]).astype(int),
                        "log10_err_before": np.round(err0, 3), "log10_err_after": np.round(err, 3)})
    out.loc[out["iso3"] == p["origin"]["node"], "contact"] = 1.0
    out[["iso3", "contact"]].to_csv(seir.COUNTRY, index=False)
    out.to_csv(seir.OUT / "country_fit.csv", index=False)
    pd.DataFrame(hist).to_csv(seir.OUT / "country_fit_log.csv", index=False)
    print(f"→ {seir.COUNTRY}（{(np.abs(f - 1) > 1e-3).sum()} 國調整）、data/model_output/country_fit.csv")
    at = out[out["iso3"].isin(["ITA", "ESP", "DEU", "FRA", "GBR", "USA", "RUS", "TWN", "THA", "JPN", "KOR", "BRA", "IRN", "TUR"])]
    print(at.to_string(index=False))


if __name__ == "__main__":
    main()
