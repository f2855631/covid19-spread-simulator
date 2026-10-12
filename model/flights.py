"""由 OpenFlights 航線建立「節點對節點」的航班矩陣。

節點與確診表一致：國家 / 地區用 ISO3，湖北的機場獨立成 CHN-HUB。
權重 = 兩節點間「航空公司 × 機場對」的航線數（排除共掛班號，避免同一班機重複計算）。
注意：OpenFlights 航線資料停在 2014-06，且沒有班次與座位數，只能代表「連結強度」的相對大小。

輸出：
    data/processed/flight_matrix.csv   from_iso3, to_iso3, routes
    data/processed/airports_nodes.csv  每個機場對應的節點（除錯用）
"""
from pathlib import Path

import pandas as pd
import pycountry

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw" / "openflights", ROOT / "data" / "processed"

HUBEI_IATA = {"WUH", "ENH", "YIH", "WDS", "XFN", "SHS"}  # 武漢、恩施、宜昌、十堰、襄陽、荊州
ISO2_EXTRA = {"XK": "XKS"}  # pycountry 沒有科索沃；代碼與 JHU 一致用 XKS
# OpenFlights 國名在 countries.dat 中缺少 ISO 代碼的，手動補上
NAME_EXTRA = {
    "Congo (Kinshasa)": "COD", "Congo (Brazzaville)": "COG", "Burma": "MMR", "Kyrgyzstan": "KGZ",
    "Faroe Islands": "FRO", "Cape Verde": "CPV", "Netherlands Antilles": "CUW",
    "Saint Vincent and the Grenadines": "VCT", "Micronesia": "FSM", "Virgin Islands": "VIR",
    "East Timor": "TLS", "Swaziland": "SWZ", "Saint Pierre and Miquelon": "SPM",
    "Wallis and Futuna": "WLF", "Saint Kitts and Nevis": "KNA", "Saint Lucia": "LCA",
    "Brunei": "BRN", "Svalbard": "SJM", "Saint Helena": "SHN", "West Bank": "PSE",
    "Macau": "MAC", "Midway Islands": "UMI", "Johnston Atoll": "UMI", "Wake Island": "UMI",
}

AIRPORT_COLS = ["id", "name", "city", "country", "iata", "icao", "lat", "lon",
                "alt", "tz_offset", "dst", "tz", "type", "source"]
ROUTE_COLS = ["airline", "airline_id", "src", "src_id", "dst", "dst_id", "codeshare", "stops", "equipment"]


def iso2_to_iso3(code):
    if not isinstance(code, str):
        return None
    if code in ISO2_EXTRA:
        return ISO2_EXTRA[code]
    c = pycountry.countries.get(alpha_2=code)
    return c.alpha_3 if c else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    countries = pd.read_csv(RAW / "countries.dat", header=None, names=["name", "iso2", "dafif"],
                            na_values="\\N", keep_default_na=False)
    name2iso3 = {r["name"]: iso2_to_iso3(r["iso2"]) for _, r in countries.iterrows()}
    name2iso3.update(NAME_EXTRA)

    ap = pd.read_csv(RAW / "airports.dat", header=None, names=AIRPORT_COLS, na_values="\\N")
    ap["node"] = ap["country"].map(name2iso3)
    ap.loc[ap["iata"].isin(HUBEI_IATA), "node"] = "CHN-HUB"
    missing = ap[ap["node"].isna()]["country"].value_counts()
    if len(missing):
        print(f"  {missing.sum()} 個機場的國名對不到 ISO3：{', '.join(missing.index[:8])} …")
    ap[["id", "iata", "name", "city", "country", "node", "lat", "lon"]].to_csv(OUT / "airports_nodes.csv", index=False)

    rt = pd.read_csv(RAW / "routes.dat", header=None, names=ROUTE_COLS, na_values="\\N", keep_default_na=False)
    rt = rt[rt["codeshare"] != "Y"]
    id2node = ap.set_index("id")["node"]
    iata2node = ap.dropna(subset=["iata"]).drop_duplicates("iata").set_index("iata")["node"]
    # 優先用機場 ID 對應，沒有 ID 再用 IATA
    rt["from_iso3"] = pd.to_numeric(rt["src_id"], errors="coerce").map(id2node).fillna(rt["src"].map(iata2node))
    rt["to_iso3"] = pd.to_numeric(rt["dst_id"], errors="coerce").map(id2node).fillna(rt["dst"].map(iata2node))
    rt = rt.dropna(subset=["from_iso3", "to_iso3"])
    rt = rt[rt["from_iso3"] != rt["to_iso3"]]  # 只留跨節點（國際 + 湖北↔中國其他）

    fm = (rt.groupby(["from_iso3", "to_iso3"]).size().rename("routes").reset_index()
            .sort_values("routes", ascending=False))
    fm.to_csv(OUT / "flight_matrix.csv", index=False)

    hub = fm[(fm["from_iso3"] == "CHN-HUB") & (fm["to_iso3"] != "CHN")]
    print(f"flight_matrix.csv：{len(fm):,} 個節點對，{fm['routes'].sum():,} 條跨節點航線，"
          f"{pd.unique(fm[['from_iso3', 'to_iso3']].values.ravel()).size} 個節點")
    print(f"  湖北直飛的境外節點：{', '.join(hub['to_iso3'])}")


if __name__ == "__main__":
    main()
