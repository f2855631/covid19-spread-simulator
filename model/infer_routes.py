"""初版擴散路線推算：每個國家「最可能從哪裡被傳入」。

方法（規劃書第 2 節）：國家 i 在首例日 t 的傳入來源 j，機率正比於
    從 j 飛往 i 的航線數 × j 在 t 之前 14 天的新增確診 / j 的人口
只考慮首例日早於 i 的節點。機率最高者為推定來源。
沒有任何航線連到已感染節點的國家（多半是經陸路或轉機傳入，例如摩納哥、聖馬利諾），
改取「距離最近的已感染節點」，evidence 記為 nearest_infected。

這是用「觀察到的確診」做的粗估，之後會改用模型的潛伏者數 E_j(t)（規劃書第 3 節）。

輸出：data/processed/routes_inferred.csv
    date, to_iso3, from_iso3, probability, second_iso3, second_probability, n_candidates, routes, evidence
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
WINDOW = 14  # 用來源地過去 14 天的新增確診代表「正在流行的程度」
# 湖北是起點：WHO 於 2019-12-31 接獲武漢不明原因肺炎群聚通報（JHU 從 2020-01-22 才有資料）
ORIGIN, ORIGIN_DATE = "CHN-HUB", pd.Timestamp("2019-12-31")


def main():
    fc = pd.read_csv(PROC / "first_cases.csv", parse_dates=["first_case"]).dropna(subset=["first_case"])
    cases = pd.read_csv(PROC / "cases_daily.csv", parse_dates=["date"])
    fm = pd.read_csv(PROC / "flight_matrix.csv")

    cum = cases.pivot(index="date", columns="iso3", values="cum_confirmed")
    pop = cases.drop_duplicates("iso3").set_index("iso3")["population"]
    first = fc.set_index("iso3")["first_case"].copy()
    first[ORIGIN] = ORIGIN_DATE
    loc = fc.set_index("iso3")[["lat", "lon"]]

    def nearest(i, cands):
        if i not in loc.index:
            return None
        c = [j for j in cands if j in loc.index]
        if not c:
            return None
        lat1, lon1 = np.radians(loc.loc[i])
        lat2, lon2 = np.radians(loc.loc[c, "lat"].values), np.radians(loc.loc[c, "lon"].values)
        d = np.arccos(np.clip(np.sin(lat1) * np.sin(lat2) + np.cos(lat1) * np.cos(lat2) * np.cos(lon2 - lon1), -1, 1))
        return c[int(np.argmin(d))]
    inbound = fm.pivot(index="from_iso3", columns="to_iso3", values="routes").fillna(0)
    d0 = cum.index.min()

    rows = []
    for i, t in first.sort_values().items():
        if i == ORIGIN:
            continue  # 起點
        cands = first[(first < t) & (first.index != i)].index
        t_end = max(t - pd.Timedelta(days=1), d0)
        t_start = max(t - pd.Timedelta(days=WINDOW + 1), d0)
        scores = {}
        for j in cands:
            r = inbound.at[j, i] if (j in inbound.index and i in inbound.columns) else 0
            if r <= 0 or j not in cum.columns or pd.isna(pop.get(j)):
                continue
            recent = cum.at[t_end, j] - (cum.at[t_start, j] if t_start < t_end else 0)
            # 首例日在 JHU 開始記錄前的節點（如湖北），用第一天的累計值
            recent = recent if recent > 0 else cum.at[t_end, j]
            if recent > 0:
                scores[j] = r * recent / pop[j]
        total = sum(scores.values())
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top = ranked[0] if ranked else (None, 0)
        sec = ranked[1] if len(ranked) > 1 else (None, 0)
        if top[0]:
            src, evidence = top[0], "inferred"
        else:
            src, evidence = nearest(i, list(cands)), "nearest_infected"
        rows.append({
            "date": t.date().isoformat(), "to_iso3": i,
            "from_iso3": src, "probability": round(top[1] / total, 3) if total else None,
            "second_iso3": sec[0], "second_probability": round(sec[1] / total, 3) if total else None,
            "n_candidates": len(scores),
            "routes": int(inbound.at[top[0], i]) if top[0] else 0,
            "evidence": evidence if src else "unknown",
        })

    out = pd.DataFrame(rows)
    out.to_csv(PROC / "routes_inferred.csv", index=False)
    ok = out["from_iso3"].notna()
    print(f"routes_inferred.csv：{ok.sum()} 條路線（航線推算 {(out['evidence'] == 'inferred').sum()}、"
          f"最近已感染地區 {(out['evidence'] == 'nearest_infected').sum()}），{(~ok).sum()} 個無法判斷")
    print("  最常見的推定來源：" + "、".join(f"{k} {v}" for k, v in out["from_iso3"].value_counts().head(6).items()))
    print(f"  機率 ≥ 50% 的路線：{(out['probability'] >= 0.5).sum()} 條；< 30%（不確定）：{(out['probability'] < 0.3).sum()} 條")


if __name__ == "__main__":
    main()
