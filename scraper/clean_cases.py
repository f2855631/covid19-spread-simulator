"""把 JHU 累計確診 / 死亡整理成「日期 × 節點」的乾淨表。

節點（node）= 國家或地區，以 ISO3 表示；湖北獨立為 CHN-HUB，CHN 代表中國其他省份。

輸出：
    data/processed/cases_daily.csv        長表：date, iso3, node, cum_confirmed, new_confirmed,
                                          new_confirmed_7d, cum_deaths, new_deaths, new_deaths_7d,
                                          population, new_confirmed_7d_per_million
    data/processed/cases_wide_2020H1.csv  寬表：2020-01-22 至 2020-06-30 每日累計確診（列 = 日期，欄 = iso3），
                                          給模型校準用
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw" / "jhu", ROOT / "data" / "processed"


def load_series(fname: str) -> pd.DataFrame:
    """讀 JHU 時間序列，回傳 列 = 節點、欄 = 日期 的累計值。"""
    ts = pd.read_csv(RAW / fname).copy()
    ts["node"] = ts["Country/Region"]
    hubei = (ts["Country/Region"] == "China") & (ts["Province/State"] == "Hubei")
    ts.loc[hubei, "node"] = "China-Hubei"
    agg = ts.groupby("node")[list(ts.columns[4:-1])].sum().copy()
    agg.columns = pd.to_datetime(agg.columns, format="%m/%d/%y")
    return agg


def node_table() -> pd.DataFrame:
    uid = pd.read_csv(RAW / "UID_ISO_FIPS_LookUp_Table.csv")
    nat = uid[uid["Province_State"].isna()][["Country_Region", "iso3", "Population"]]
    nat = nat.rename(columns={"Country_Region": "node", "Population": "population"}).copy()
    hub = uid[(uid["Country_Region"] == "China") & (uid["Province_State"] == "Hubei")].iloc[0]
    nat.loc[nat["node"] == "China", "population"] -= hub["Population"]
    nat = pd.concat([nat, pd.DataFrame([{"node": "China-Hubei", "iso3": "CHN-HUB", "population": hub["Population"]}])])
    return nat.dropna(subset=["iso3"]).set_index("node")


def to_long(cum: pd.DataFrame, name: str) -> pd.DataFrame:
    cum = cum.copy()
    # 修正：累計值偶有下修，先做「累計最大值往回填」再差分，避免負的每日新增
    fixed = cum.iloc[:, ::-1].cummin(axis=1).iloc[:, ::-1]
    new = fixed.diff(axis=1)
    new.iloc[:, 0] = 0  # 第一天（2020-01-22）沒有前一天可比較
    new7 = new.T.rolling(7, min_periods=1).mean().T
    long = pd.DataFrame({
        f"cum_{name}": cum.stack(),
        f"new_{name}": new.stack(),
        f"new_{name}_7d": new7.stack(),
    })
    long.index.names = ["node", "date"]
    n_down = int((cum.diff(axis=1) < 0).sum().sum())
    print(f"  {name}：{n_down} 個「累計值下修」的日子已平滑處理")
    return long


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    nodes = node_table()
    conf = load_series("time_series_covid19_confirmed_global.csv")
    death = load_series("time_series_covid19_deaths_global.csv")
    conf = conf[conf.index.isin(nodes.index)]
    death = death[death.index.isin(nodes.index)]

    df = to_long(conf, "confirmed").join(to_long(death, "deaths")).reset_index()
    df["iso3"] = df["node"].map(nodes["iso3"])
    df["population"] = df["node"].map(nodes["population"])
    df["new_confirmed_7d_per_million"] = df["new_confirmed_7d"] / df["population"] * 1e6
    df = df[["date", "iso3", "node", "cum_confirmed", "new_confirmed", "new_confirmed_7d",
             "cum_deaths", "new_deaths", "new_deaths_7d", "population", "new_confirmed_7d_per_million"]]
    df = df.sort_values(["date", "iso3"])
    for c in ["new_confirmed_7d", "new_deaths_7d", "new_confirmed_7d_per_million"]:
        df[c] = df[c].round(2)
    df.to_csv(OUT / "cases_daily.csv", index=False, date_format="%Y-%m-%d")

    wide = conf.T.loc[:"2020-06-30"]
    wide.columns = [nodes.loc[n, "iso3"] for n in wide.columns]
    wide.index.name = "date"
    wide.to_csv(OUT / "cases_wide_2020H1.csv", date_format="%Y-%m-%d")

    print(f"cases_daily.csv：{df['iso3'].nunique()} 個節點 × {df['date'].nunique()} 天 = {len(df):,} 列"
          f"（{df['date'].min():%Y-%m-%d} 至 {df['date'].max():%Y-%m-%d}）")
    print(f"cases_wide_2020H1.csv：{wide.shape[0]} 天 × {wide.shape[1]} 個節點")


if __name__ == "__main__":
    main()
