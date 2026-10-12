"""第四階段（第二版）：用真實資料校準全球模型（只用 numpy，不需要 scipy）。

第一版只比對「中國以外加總」的確診曲線，結果亞洲高估、歐美低估剛好互相抵消
（4/30 模型 84% 的病例在亞洲，真實只有 14%）。第二版改成逐地區比對：

目標函數（越小越好）：
    J = 2 × 訓練組首例日平均誤差（天）
        + 25 × 七個地區平均的 [累計確診 log10 RMSE + 每日新增（7 日平均）log10 RMSE]
    - 訓練組：2020-02-29 前出現首例的國家（不含中國、湖北）
    - 測試組：2020-03-01 至 03-31 出現首例的國家 —— 不參與校準，用來檢查模型是否只是「背答案」
    - 地區累計：該地區累計確診達 10 例起至 04-30；每日新增：2020-03-01 至 04-30
    - 5–6 月完全不參與校準，留給 model/validate_extended.py 檢驗
    湖北的參數（R0、k、起始感染、湖北通報率）沿用 run_hubei.py 的擬合結果，不在這裡調整。

搜尋的參數：4 個全球參數 + 7 個地區的傳播倍數（contact）。
各地區的通報率（ratio）不必搜尋：給定一次模擬，確診數對通報率是線性的，
直接對每個地區做一維最佳化（profile），每次模擬都用該組最適通報率評分。

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

import regions
import seir

# (參數路徑, 下限, 上限, 尺度)
REGIONS = list(regions.REGION_ZH)
SPACE = [
    ("travel.passengers_per_route_per_day", 50, 600, "log"),
    ("travel.hubei_transit_fraction", 0.01, 0.3, "log"),
    ("reporting.import_ratio", 0.05, 0.9, "lin"),
    ("epidemiology.policy_effect_world", 0.3, 1.2, "lin"),
    ("reporting.ratio_early", 0.02, 0.6, "log"),
] + [(f"regions.{r}.contact", 0.3, 1.8, "lin") for r in REGIONS]
RATIO_RANGE = (0.03, 0.25)   # 通報率範圍：2020 年春季各地血清調查顯示確診約占感染的 3%–25%
TRAIN_END, TEST_END = "2020-02-29", "2020-03-31"
CURVE_END = "2020-04-30"
CUM_START = 10   # 地區累計確診達 10 例起才比對
DAILY = ("2020-03-01", "2020-04-30")
CURVE_WEIGHT = 25
FIRST_WEIGHT = 2   # 首例日誤差的權重：地區曲線改善不能以首例日變差為代價
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
        *secs, key = path.split(".")
        d = q
        for sec in secs:
            d = d.setdefault(sec, {})
        d[key] = v
    return q


def getp(p, path, default=None):
    d = p
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def current(p):
    return {path: getp(p, path, 1.0) for path, *_ in SPACE}


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
        cum = cases.pivot(index="date", columns="iso3", values="cum_confirmed").reindex(index=d, columns=inp.nodes).fillna(0)
        self.outside = ~np.isin(inp.nodes, excl)
        reg = np.array(inp.region)
        self.members = {r: np.where((reg == r) & self.outside)[0] for r in REGIONS}
        self.daily_mask = (d >= DAILY[0]) & (d <= DAILY[1])
        self.end = d.get_loc(pd.Timestamp(CURVE_END)) if pd.Timestamp(CURVE_END) <= d[-1] else len(d) - 1
        self.obs = {}
        for r, ix in self.members.items():
            c = cum.iloc[:, ix].sum(axis=1).to_numpy()
            new7 = pd.Series(c).diff().rolling(7).mean().to_numpy()
            cmask = (c >= CUM_START) & (np.arange(len(d)) <= self.end)
            self.obs[r] = {"cum": c, "cmask": cmask, "cum_log": np.log10(np.maximum(c[cmask], 1)),
                           "daily_log": np.log10(np.maximum(new7[self.daily_mask], 1))}
        world = cum.iloc[:, np.where(self.outside)[0]].sum(axis=1).to_numpy()
        self.world_cum = world
        rp = p["reporting"]
        self.lag, self.lag_i = rp["delay_days"], rp.get("import_delay_days", rp["delay_days"])
        self.can_test = (d >= pd.Timestamp(rp.get("testing_start", d[0]))).astype(float)
        a, b = pd.Timestamp(rp["early_ramp_start"]), pd.Timestamp(rp["early_ramp_end"])
        self.w_late = np.clip((d - a).days / max((b - a).days, 1), 0, 1).to_numpy()
        self.log = []

    @staticmethod
    def shift(x, lag):
        return np.concatenate([np.zeros((lag,) + x.shape[1:]), x[:-lag]]) if lag else x

    def fit_ratios(self, q, r):
        """給定一次模擬，對每個地區找最適通報率（log 空間黃金分割搜尋）。"""
        loc = self.shift(r.new_inf, self.lag) * self.can_test[:, None]
        imp = self.shift(r.imports, self.lag_i) * self.can_test[:, None] * q["reporting"]["import_ratio"]
        # 初期通報率的部分是已知的，併入「固定」項；只對後期（地區）通報率做最佳化
        imp = imp + loc * (1 - self.w_late)[:, None] * q["reporting"]["ratio_early"]
        loc = loc * self.w_late[:, None]
        out = {}
        for reg, ix in self.members.items():
            L, M = loc[:, ix].sum(axis=1), imp[:, ix].sum(axis=1)
            o = self.obs[reg]
            L7 = pd.Series(L).rolling(7).mean().to_numpy()[self.daily_mask]
            M7 = pd.Series(M).rolling(7).mean().to_numpy()[self.daily_mask]
            cL, cM = np.cumsum(L)[o["cmask"]], np.cumsum(M)[o["cmask"]]

            def err(lr):
                rho = np.exp(lr)
                e1 = np.log10(np.maximum(rho * L7 + M7, 1)) - o["daily_log"]
                e2 = np.log10(np.maximum(rho * cL + cM, 1)) - o["cum_log"] if len(cL) else np.zeros(1)
                return np.sqrt(np.mean(e1 ** 2)) + np.sqrt(np.mean(e2 ** 2))
            lo, hi = np.log(RATIO_RANGE[0]), np.log(RATIO_RANGE[1])
            g = (np.sqrt(5) - 1) / 2
            a, b = hi - g * (hi - lo), lo + g * (hi - lo)
            fa, fb = err(a), err(b)
            for _ in range(40):
                if fa < fb:
                    hi, b, fb = b, a, fa
                    a = hi - g * (hi - lo); fa = err(a)
                else:
                    lo, a, fa = a, b, fb
                    b = lo + g * (hi - lo); fb = err(b)
            out[reg] = float(np.exp((lo + hi) / 2))
        return out

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

    def with_ratios(self, q):
        """模擬一次並代入各地區最適通報率；回傳 (參數, 模擬結果, 通報率)。"""
        r = seir.simulate(q, self.inp, flow_min=None)
        ratios = self.fit_ratios(q, r)
        q2 = apply(q, {f"regions.{k}.ratio": v for k, v in ratios.items()})
        r.reported_cum, r.detect_day = seir.apply_reporting(q2, self.inp, r.new_inf, r.imports)
        return q2, r, ratios

    def metrics(self, q):
        q, r, ratios = self.with_ratios(q)
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
        reg_terms = []
        for reg, ix in self.members.items():
            o = self.obs[reg]
            c = r.reported_cum[:, ix].sum(axis=1)
            new7 = pd.Series(c).diff().rolling(7).mean().to_numpy()[self.daily_mask]
            ec = float(np.sqrt(np.mean((np.log10(np.maximum(c[o["cmask"]], 1)) - o["cum_log"]) ** 2))) if o["cmask"].any() else 0.0
            ed = float(np.sqrt(np.mean((np.log10(np.maximum(new7, 1)) - o["daily_log"]) ** 2)))
            m[f"{reg}_cum_rmse_log10"], m[f"{reg}_daily_rmse_log10"] = ec, ed
            m[f"{reg}_ratio_0430"] = float(c[self.end] / max(o["cum"][self.end], 1))
            m[f"{reg}_rho"] = ratios[reg]
            reg_terms.append(ec + ed)
        m["region_rmse_log10"] = float(np.mean(reg_terms))
        allc = r.reported_cum[:, self.outside].sum(axis=1)
        mask = (np.arange(len(allc)) <= self.end) & (self.world_cum >= CUM_START)
        m["curve_mape"] = float(np.mean(np.abs(allc[mask] - self.world_cum[mask]) / self.world_cum[mask]))
        m["world_ratio_0430"] = float(allc[self.end] / self.world_cum[self.end])
        m["J"] = FIRST_WEIGHT * m["train_mae"] + CURVE_WEIGHT * m["region_rmse_log10"]
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
    """一般參數就地替換；regions 區塊整段重寫。"""
    s = seir.PARAMS.read_text(encoding="utf-8")
    flat = {k: v for k, v in vals.items() if not k.startswith("regions.")}
    for path, v in flat.items():
        key = path.split(".")[-1]
        s = re.sub(rf"(\n\s*{key}:\s*)[0-9.eE+-]+", rf"\g<1>{v:.4g}", s, count=1)
    reg = {}
    for path, v in vals.items():
        if path.startswith("regions."):
            _, r, key = path.split(".")
            reg.setdefault(r, {})[key] = v
    if reg:
        block = ["regions:",
                 "  # 各地區參數（第四階段第二版校準，model/regions.py 定義分區；湖北不套用）",
                 "  #   contact：傳播倍數，吸收嚴格指數量不到的口罩、檢測、追蹤等差異",
                 "  #   ratio：通報率（感染者中被確診的比例）"]
        for r in REGIONS:
            if r in reg:
                block.append(f"  {r}: {{contact: {reg[r].get('contact', 1):.3g}, ratio: {reg[r].get('ratio', 0.04):.3g}}}"
                             f"   # {regions.REGION_ZH[r]}")
        txt = "\n".join(block) + "\n"
        if re.search(r"\nregions:\n", s):
            s = re.sub(r"\nregions:\n(?:[ #].*\n)*", "\n" + txt, s)
        else:
            s = s.rstrip("\n") + "\n\n" + txt
    seir.PARAMS.write_text(s, encoding="utf-8")


def fmt(m):
    reg = "、".join(f"{r} ×{m[f'{r}_ratio_0430']:.2f}" for r in REGIONS)
    return (f"訓練組 {m['train_n']} 國：平均誤差 {m['train_mae']:.1f} 天（偏差 {m['train_bias']:+.1f}、排序相關 {m['train_spearman']:.2f}、"
            f"未預測 {m['train_missed']}）｜測試組 {m['test_n']} 國：平均誤差 {m['test_mae']:.1f} 天（偏差 {m['test_bias']:+.1f}、"
            f"排序相關 {m['test_spearman']:.2f}、未預測 {m['test_missed']}）｜地區曲線誤差 ×{10 ** m['region_rmse_log10']:.2f}｜"
            f"中國以外 4/30 ×{m['world_ratio_0430']:.2f}、MAPE {m['curve_mape']:.0%}\n  4/30 各地區 模型/真實：{reg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", type=int, default=200)
    ap.add_argument("--random", type=int, default=None, help="隨機抽樣次數（預設為總次數的 40%）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write-params", action="store_true")
    args = ap.parse_args()

    p = seir.load_params(country=None)   # 各國倍數是下一步（fit_countries.py）的結果，校準時不套用
    inp = seir.load_inputs(p)
    obj = Objective(p, inp)
    before = obj.metrics(p)
    print("校準前：" + fmt(before))

    t0 = time.time()
    n_rand = args.random or int(args.evals * 0.4)
    rng = np.random.default_rng(args.seed)
    d = len(SPACE)
    lhs = (rng.permuted(np.tile(np.arange(n_rand), (d, 1)), axis=1).T + rng.random((n_rand, d))) / n_rand
    # 起點：目前參數、以及第一版全球參數（旅客數、轉機比例、入境驗出率）搭配目前地區參數
    v1 = {**current(p), "travel.passengers_per_route_per_day": 454.3, "travel.hubei_transit_fraction": 0.0715,
          "reporting.import_ratio": 0.1966, "epidemiology.policy_effect_world": 0.83}
    cands = [encode(current(p)), encode(v1)] + list(lhs)
    scores = [obj(u) for u in cands]
    best0 = cands[int(np.argmin(scores))]
    print(f"隨機搜尋 {len(cands)} 次：最佳 J = {min(scores):.2f}（{time.time() - t0:.0f} 秒）")
    best_u, best_J = nelder_mead(obj, best0, budget=max(args.evals - len(cands), d + 1))
    best = decode(best_u)
    _, _, ratios = obj.with_ratios(apply(p, best))
    best.update({f"regions.{k}.ratio": v for k, v in ratios.items()})
    after = obj.metrics(apply(p, best))
    print(f"局部搜尋後：J = {best_J:.2f}；共 {len(obj.log)} 次模擬，{time.time() - t0:.0f} 秒")
    print("校準後：" + fmt(after))
    cur = current(p)
    for path, v in best.items():
        print(f"  {path} = {v:.4g}（原 {cur.get(path, getp(p, path, '—'))}）")

    seir.OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(obj.log).to_csv(seir.OUT / "calibration_log.csv", index=False)
    pd.DataFrame([{"stage": "before", **current(p), **before}, {"stage": "after", **best, **after}]).to_csv(
        seir.OUT / "calibration_summary.csv", index=False)
    if args.write_params:
        write_params(best)
        print("已把最佳值寫回 model/params.yaml")


if __name__ == "__main__":
    main()
