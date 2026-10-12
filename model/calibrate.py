"""第四階段：用真實資料校準全球模型的 7 個參數（只用 numpy，不需要 scipy）。

目標函數（越小越好）：
    J = 訓練組首例日平均誤差（天） + 40 × 中國以外累計確診的 log10 RMSE
          + 40 × 中國以外每日新增確診（7 日平均）的 log10 RMSE
    - 訓練組：2020-02-29 前出現首例的國家（不含中國、湖北）
    - 測試組：2020-03-01 至 03-31 出現首例的國家 —— 不參與校準，用來檢查模型是否只是「背答案」
    - 累計曲線：2020-02-15 至 04-15 中國以外各國累計確診總和
    - 每日新增：2020-03-01 至 04-30，讓模型學到 4 月歐美封城後的趨平
    湖北的參數（R0、k、起始感染、湖北通報率）沿用 run_hubei.py 的擬合結果，不在這裡調整。

方法：先在參數空間隨機抽樣（拉丁超立方），再從最佳點做 Nelder–Mead 局部搜尋。
「模型首例日」用內插取得小數天數，讓目標函數連續，搜尋比較穩定。

用法：
    python model/calibrate.py                   # 預設 200 次模擬（約 5–10 分鐘）
    python model/calibrate.py --evals 60        # 快速試跑
    python model/calibrate.py --write-params    # 把最佳值寫回 params.yaml
輸出：data/model_output/calibration_log.csv、calibration_summary.csv
"""
import argparse
import copy
import re
import time

import numpy as np
import pandas as pd

import seir

# (參數路徑, 下限, 上限, 尺度)
SPACE = [
    ("travel.passengers_per_route_per_day", 50, 600, "log"),
    ("travel.hubei_transit_fraction", 0.01, 0.3, "log"),
    ("reporting.import_ratio", 0.05, 0.9, "lin"),
    ("reporting.ratio_default", 0.02, 0.5, "log"),
    ("epidemiology.policy_effect_world", 0.3, 1.2, "lin"),
    ("epidemiology.tracing_reduction", 0.0, 0.9, "lin"),
    ("epidemiology.tracing_capacity_per_million", 1, 300, "log"),
]
TRAIN_END, TEST_END = "2020-02-29", "2020-03-31"
CURVE = ("2020-02-15", "2020-04-15")
DAILY = ("2020-03-01", "2020-04-30")
CURVE_WEIGHT = 40
MISS_PENALTY = 14  # 到模擬結束都沒預測到首例：當作「結束日 + 14 天」


def decode(u):
    vals = {}
    for x, (path, lo, hi, scale) in zip(np.clip(u, 0, 1), SPACE):
        vals[path] = float(np.exp(np.log(lo) + x * (np.log(hi) - np.log(lo)))) if scale == "log" else lo + x * (hi - lo)
    return vals


def encode(vals):
    u = []
    for path, lo, hi, scale in SPACE:
        v = vals[path]
        u.append((np.log(v) - np.log(lo)) / (np.log(hi) - np.log(lo)) if scale == "log" else (v - lo) / (hi - lo))
    return np.clip(np.array(u), 0, 1)


def apply(p, vals):
    q = copy.deepcopy(p)
    for path, v in vals.items():
        sec, key = path.split(".")
        q[sec][key] = v
    return q


def current(p):
    return {path: p[path.split(".")[0]][path.split(".")[1]] for path, *_ in SPACE}


class Objective:
    def __init__(self, p, inp):
        self.p, self.inp = p, inp
        d = inp.dates
        obs = inp.obs_first
        excl = ["CHN", "CHN-HUB"]
        self.obs_day = np.array([(x - d[0]).days if pd.notna(x) else np.nan for x in obs])
        valid = ~np.isin(inp.nodes, excl) & ~np.isnan(self.obs_day)
        self.train = valid & (obs <= TRAIN_END).to_numpy()
        self.test = valid & (obs > TRAIN_END).to_numpy() & (obs <= TEST_END).to_numpy()
        cases = pd.read_csv(seir.PROC / "cases_daily.csv", usecols=["date", "iso3", "cum_confirmed"], parse_dates=["date"])
        world = cases[~cases["iso3"].isin(excl)].groupby("date")["cum_confirmed"].sum()
        self.curve_mask = (d >= CURVE[0]) & (d <= CURVE[1])
        self.curve_obs = np.log10(world.reindex(d[self.curve_mask]).to_numpy())
        new7 = world.reindex(d).diff().rolling(7).mean()
        self.daily_mask = (d >= DAILY[0]) & (d <= DAILY[1])
        self.daily_obs = np.log10(new7[self.daily_mask].clip(lower=1).to_numpy())
        self.outside = ~np.isin(inp.nodes, excl)
        self.log = []

    def detect_frac(self, rep):
        thr = self.p["reporting"]["detect_threshold"]
        T = rep.shape[0]
        out = np.full(rep.shape[1], T - 1 + MISS_PENALTY, dtype=float)
        hit = rep >= thr
        for i in np.where(hit.any(axis=0))[0]:
            t = hit[:, i].argmax()
            if t == 0:
                out[i] = 0
            else:
                a, b = rep[t - 1, i], rep[t, i]
                out[i] = t - 1 + (thr - a) / max(b - a, 1e-12)
        return out

    def metrics(self, q):
        r = seir.simulate(q, self.inp, flow_min=None)
        sim = self.detect_frac(r.reported_cum)
        err = sim - self.obs_day
        m = {}
        for name, mask in [("train", self.train), ("test", self.test)]:
            e = err[mask]
            m[f"{name}_mae"] = float(np.abs(e).mean())
            m[f"{name}_bias"] = float(e.mean())
            m[f"{name}_spearman"] = float(pd.Series(sim[mask]).rank().corr(pd.Series(self.obs_day[mask]).rank()))
            m[f"{name}_missed"] = int((sim[mask] >= len(self.inp.dates) - 1 + MISS_PENALTY - 1e-9).sum())
            m[f"{name}_n"] = int(mask.sum())
        curve = r.reported_cum[self.curve_mask][:, self.outside].sum(axis=1)
        m["curve_rmse_log10"] = float(np.sqrt(np.mean((np.log10(np.maximum(curve, 1)) - self.curve_obs) ** 2)))
        obs_lin, sim_lin = 10 ** self.curve_obs, curve
        m["curve_mape"] = float(np.mean(np.abs(sim_lin - obs_lin) / obs_lin))
        all_cum = r.reported_cum[:, self.outside].sum(axis=1)
        sim7 = pd.Series(all_cum).diff().rolling(7).mean().to_numpy()[self.daily_mask]
        m["daily_rmse_log10"] = float(np.sqrt(np.mean((np.log10(np.maximum(sim7, 1)) - self.daily_obs) ** 2)))
        m["J"] = m["train_mae"] + CURVE_WEIGHT * (m["curve_rmse_log10"] + m["daily_rmse_log10"])
        return m

    def __call__(self, u):
        vals = decode(u)
        m = self.metrics(apply(self.p, vals))
        self.log.append({**vals, **m})
        return m["J"]


def nelder_mead(f, x0, budget, step=0.15):
    d = len(x0)
    pts = [np.clip(x0, 0, 1)] + [np.clip(x0 + step * np.eye(d)[i] * (1 if x0[i] < 0.5 else -1), 0, 1) for i in range(d)]
    vals = [f(x) for x in pts]
    used = len(pts)
    while used < budget:
        order = np.argsort(vals)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        c = np.mean(pts[:-1], axis=0)
        xr = np.clip(c + (c - pts[-1]), 0, 1); fr = f(xr); used += 1
        if fr < vals[0]:
            xe = np.clip(c + 2 * (c - pts[-1]), 0, 1); fe = f(xe); used += 1
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = np.clip(c + 0.5 * (pts[-1] - c), 0, 1); fc = f(xc); used += 1
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, len(pts)):
                    pts[i] = pts[0] + 0.5 * (pts[i] - pts[0])
                    vals[i] = f(pts[i]); used += 1
        if np.std(vals) < 1e-3:
            break
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def write_params(vals):
    s = seir.PARAMS.read_text(encoding="utf-8")
    for path, v in vals.items():
        key = path.split(".")[1]
        s = re.sub(rf"(\n\s*{key}:\s*)[0-9.eE+-]+", rf"\g<1>{v:.4g}", s, count=1)
    seir.PARAMS.write_text(s, encoding="utf-8")


def fmt(m):
    return (f"訓練組 {m['train_n']} 國：平均誤差 {m['train_mae']:.1f} 天（偏差 {m['train_bias']:+.1f}、排序相關 {m['train_spearman']:.2f}、"
            f"未預測 {m['train_missed']}）｜測試組 {m['test_n']} 國：平均誤差 {m['test_mae']:.1f} 天（偏差 {m['test_bias']:+.1f}、"
            f"排序相關 {m['test_spearman']:.2f}、未預測 {m['test_missed']}）｜中國以外曲線：誤差 ×{10 ** m['curve_rmse_log10']:.2f}、"
            f"MAPE {m['curve_mape']:.0%}｜每日新增誤差 ×{10 ** m['daily_rmse_log10']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", type=int, default=200)
    ap.add_argument("--random", type=int, default=None, help="隨機抽樣次數（預設為總次數的 40%）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write-params", action="store_true")
    args = ap.parse_args()

    p = seir.load_params()
    inp = seir.load_inputs(p)
    obj = Objective(p, inp)
    before = obj.metrics(p)
    print("校準前：" + fmt(before))

    t0 = time.time()
    n_rand = args.random or int(args.evals * 0.4)
    rng = np.random.default_rng(args.seed)
    d = len(SPACE)
    lhs = (rng.permuted(np.tile(np.arange(n_rand), (d, 1)), axis=1).T + rng.random((n_rand, d))) / n_rand
    cands = [encode(current(p))] + list(lhs)
    scores = [obj(u) for u in cands]
    best0 = cands[int(np.argmin(scores))]
    print(f"隨機搜尋 {len(cands)} 次：最佳 J = {min(scores):.2f}（{time.time() - t0:.0f} 秒）")
    best_u, best_J = nelder_mead(obj, best0, budget=max(args.evals - len(cands), d + 1))
    best = decode(best_u)
    after = obj.metrics(apply(p, best))
    print(f"局部搜尋後：J = {best_J:.2f}；共 {len(obj.log)} 次模擬，{time.time() - t0:.0f} 秒")
    print("校準後：" + fmt(after))
    for path, v in best.items():
        print(f"  {path} = {v:.4g}（原 {current(p)[path]}）")

    seir.OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(obj.log).to_csv(seir.OUT / "calibration_log.csv", index=False)
    pd.DataFrame([{"stage": "before", **current(p), **before}, {"stage": "after", **best, **after}]).to_csv(
        seir.OUT / "calibration_summary.csv", index=False)
    if args.write_params:
        write_params(best)
        print("已把最佳值寫回 model/params.yaml")


if __name__ == "__main__":
    main()
