"""合併各來源，產出模擬器第一版需要的「擴散點」與「關鍵擴散時機點」資料。

輸入（先執行 download_data.py 與 scrape_who_sitreps.py）：
    data/raw/jhu/*.csv, data/raw/owid/owid-covid-data.csv, data/raw/oxcgrt/*.csv
    data/processed/who_sitrep_events.csv
輸出：
    data/processed/first_cases.csv   各國/地區：首例日（JHU、WHO 報告）、洲、經緯度、人口
    data/processed/events.csv        關鍵擴散時機點（初版，尚未計算重要度）
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"

CONT_ZH = {"Asia": "亞洲", "Europe": "歐洲", "North America": "北美洲",
           "South America": "南美洲", "Africa": "非洲", "Oceania": "大洋洲"}
# JHU 與 WHO 首例日衝突、經人工確認改採 WHO 報告日期的國家
#   CHL：JHU 事後回溯在 2020-02-23 補登 2 例，WHO 報告與智利官方首例均為 3 月初
USE_WHO_DATE = {"CHL"}

# 全球性事件：日期為 WHO 官方宣告日
GLOBAL_EVENTS = [
    ("2020-01-23", "CHN-HUB", "policy", "武漢封城（湖北省停止對外交通）"),
    ("2020-01-30", "WORLD", "policy", "WHO 宣布國際關注公共衛生緊急事件（PHEIC）"),
    ("2020-03-11", "WORLD", "policy", "WHO 宣布 COVID-19 為全球大流行"),
]


def jhu_first_cases() -> pd.DataFrame:
    ts = pd.read_csv(RAW / "jhu" / "time_series_covid19_confirmed_global.csv")
    uid = pd.read_csv(RAW / "jhu" / "UID_ISO_FIPS_LookUp_Table.csv")
    date_cols = ts.columns[4:]
    # 湖北獨立成一個節點，其餘中國省份合併
    ts["node"] = ts["Country/Region"]
    ts.loc[(ts["Country/Region"] == "China") & (ts["Province/State"] == "Hubei"), "node"] = "China-Hubei"
    agg = ts.groupby("node")[list(date_cols)].sum()
    first = (agg > 0).idxmax(axis=1)
    first = pd.to_datetime(first, format="%m/%d/%y")
    first[(agg.max(axis=1) == 0)] = pd.NaT

    nat = uid[uid["Province_State"].isna()].set_index("Country_Region")
    df = pd.DataFrame({"node": agg.index, "first_case_jhu": first.values})
    df["iso3"] = df["node"].map(nat["iso3"])
    df["lat"] = df["node"].map(nat["Lat"])
    df["lon"] = df["node"].map(nat["Long_"])
    df["population"] = df["node"].map(nat["Population"])
    hub = uid[(uid["Country_Region"] == "China") & (uid["Province_State"] == "Hubei")].iloc[0]
    m = df["node"] == "China-Hubei"
    df.loc[m, ["iso3", "lat", "lon", "population"]] = ["CHN-HUB", hub["Lat"], hub["Long_"], hub["Population"]]
    # 中國其他省份 = 全國人口 − 湖北
    df.loc[df["node"] == "China", "population"] -= hub["Population"]
    return df.dropna(subset=["iso3"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fc = jhu_first_cases()

    owid = pd.read_csv(RAW / "owid" / "owid-covid-data.csv", usecols=["iso_code", "continent"]).drop_duplicates("iso_code")
    cont = owid.set_index("iso_code")["continent"]
    fc["continent"] = fc["iso3"].map(cont)
    fc.loc[fc["iso3"] == "CHN-HUB", "continent"] = "Asia"

    who = pd.read_csv(OUT / "who_sitrep_events.csv")
    w_first = who[who["event_type"] == "first_reported_by_who"].set_index("iso3")["date"]
    w_local = who[who["event_type"] == "local_transmission_start"].set_index("iso3")["date"]
    fc["first_reported_who"] = fc["iso3"].map(w_first)
    fc["local_transmission_who"] = fc["iso3"].map(w_local)
    # JHU 從 2020-01-22 才開始記錄，更早的病例要靠 WHO 報告補：首例日取兩者較早者
    fc["first_case"] = pd.concat([fc["first_case_jhu"], pd.to_datetime(fc["first_reported_who"])], axis=1).min(axis=1)
    # 兩個來源相差超過 7 天 → 標記，清理階段人工確認（例：JHU 事後回溯補登智利 2020-02-23 的 2 例）
    gap = (pd.to_datetime(fc["first_reported_who"]) - fc["first_case_jhu"]).dt.days.abs()
    fc["first_case_conflict"] = gap > 7
    m = fc["iso3"].isin(USE_WHO_DATE)
    fc.loc[m, "first_case"] = pd.to_datetime(fc.loc[m, "first_reported_who"])
    fc["first_case_censored"] = fc["first_case"] <= pd.Timestamp("2020-01-22")  # 真正首例可能更早
    # WHO 從第 38 期（資料截至 2020-02-27）才開始標註傳播分類 → 該日的「本土傳播」只代表「最晚此日」
    class_start = pd.to_datetime(w_local).min()
    fc["local_transmission_censored"] = pd.to_datetime(fc["local_transmission_who"]) == class_start
    fc = fc.sort_values("first_case")
    fc.to_csv(OUT / "first_cases.csv", index=False, encoding="utf-8")

    # ------------------------------------------------ 關鍵擴散時機點（初版）
    ev = []
    for _, r in fc.dropna(subset=["first_case"]).iterrows():
        note = "（實際可能更早）" if r["first_case_censored"] else ""
        ev.append((r["first_case"].date().isoformat(), r["iso3"], "first_case", f"{r['node']} 首例{note}"))
    # 跨洲跳躍：亞洲以外各洲第一個出現病例的國家；同日多國並列
    outside = fc[fc["continent"].notna() & (fc["continent"] != "Asia")].dropna(subset=["first_case"])
    for c, g in outside.groupby("continent"):
        d0 = g["first_case"].min()
        tied = g[g["first_case"] == d0]
        names = "、".join(tied["node"])
        for _, r in tied.iterrows():
            ev.append((d0.date().isoformat(), r["iso3"], "continent_jump", f"病毒首次到達{CONT_ZH.get(c, c)}：{names}"))
    for iso3, d in w_local.items():
        note = "（WHO 自此日起才標註分類，實際可能更早）" if pd.Timestamp(d) == class_start else ""
        ev.append((d, iso3, "local_transmission_start", f"WHO 分類轉為本土傳播{note}"))
    # 各國防疫政策：首次「國際旅行管制 ≥ 3（禁止部分入境）」與「居家令 ≥ 2」
    ox = pd.read_csv(RAW / "oxcgrt" / "OxCGRT_compact_national_v1.csv",
                     usecols=["CountryCode", "Date", "C8EV_International travel controls", "C6M_Stay at home requirements"])
    ox["Date"] = pd.to_datetime(ox["Date"].astype(str), format="%Y%m%d")
    for col, lvl, label in [("C8EV_International travel controls", 3, "開始禁止部分國家旅客入境"),
                            ("C6M_Stay at home requirements", 2, "首次實施居家令")]:
        hit = ox[ox[col] >= lvl].groupby("CountryCode")["Date"].min()
        for iso3, d in hit.items():
            ev.append((d.date().isoformat(), iso3, "policy", label))
    ev += GLOBAL_EVENTS

    events = pd.DataFrame(ev, columns=["date", "iso3", "event_type", "description"])
    events = events.sort_values(["date", "event_type", "iso3"]).reset_index(drop=True)
    events.to_csv(OUT / "events.csv", index=False, encoding="utf-8")

    print(f"first_cases.csv：{len(fc)} 個節點，最早 {fc['first_case_jhu'].min().date()}")
    print(f"events.csv：{len(events)} 個事件")
    print(events["event_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
