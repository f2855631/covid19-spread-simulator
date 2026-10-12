"""初版動態世界地圖：擴散點依首例日出現，擴散路線由推定來源畫到目的地。

輸入：data/processed/first_cases.csv、routes_inferred.csv、cases_daily.csv、events.csv
輸出：docs/first_case_spread_map.html（單一檔案，雙擊即可用瀏覽器開啟）

用法：python app/first_case_map.py [--start 2020-01-20] [--end 2020-04-30]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
PROC, DOCS = ROOT / "data" / "processed", ROOT / "docs"

ORIGIN = "CHN-HUB"
CONT_COLORS = {"Asia": "#d1495b", "Europe": "#00798c", "North America": "#edae49",
               "South America": "#66a182", "Africa": "#8d6a9f", "Oceania": "#2e4057"}
CONT_ZH = {"Asia": "亞洲", "Europe": "歐洲", "North America": "北美洲",
           "South America": "南美洲", "Africa": "非洲", "Oceania": "大洋洲"}
RECENT_DAYS = 7  # 首例在 7 天內的路線用醒目顏色
EVIDENCE_ZH = {"inferred": "航線推算", "nearest_infected": "最近已感染地區（陸路或轉機）"}


def arc_lists(df, loc):
    lons, lats = [], []
    for _, r in df.iterrows():
        if r["from_iso3"] in loc.index and r["to_iso3"] in loc.index:
            a, b = loc.loc[r["from_iso3"]], loc.loc[r["to_iso3"]]
            lons += [a["lon"], b["lon"], None]
            lats += [a["lat"], b["lat"], None]
    return lons, lats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-20")
    ap.add_argument("--end", default="2020-04-30")
    args = ap.parse_args()

    fc = pd.read_csv(PROC / "first_cases.csv", parse_dates=["first_case"]).dropna(subset=["first_case", "lat"])
    routes = pd.read_csv(PROC / "routes_inferred.csv", parse_dates=["date"]).dropna(subset=["from_iso3"])
    cases = pd.read_csv(PROC / "cases_daily.csv", parse_dates=["date"])
    events = pd.read_csv(PROC / "events.csv", parse_dates=["date"])
    cum = cases.pivot(index="date", columns="iso3", values="cum_confirmed")

    loc = fc.set_index("iso3")[["lat", "lon", "node", "continent", "first_case"]]
    src = routes.set_index("to_iso3")
    first = loc["first_case"].copy()
    first[ORIGIN] = pd.Timestamp("2019-12-31")

    # 標題只顯示全球性事件與跨洲跳躍（各國政策太多，留給之後的時機點篩選）
    key_events = events[(events["event_type"] == "continent_jump") | events["iso3"].isin(["WORLD", "CHN-HUB"])]
    key_events = key_events.drop_duplicates(["date", "description"])

    days = pd.date_range(args.start, args.end)
    frames = []
    for d in days:
        on = first[first <= d].index
        pts = loc.loc[loc.index.intersection(on)].copy()
        c_d = cum.loc[min(d, cum.index.max())] if d >= cum.index.min() else cum.iloc[0] * 0
        pts["cases"] = [c_d.get(i, 0) for i in pts.index]
        pts["size"] = 5 + 4 * np.log10(pts["cases"].clip(lower=1))
        pts["color"] = pts["continent"].map(CONT_COLORS).fillna("#888")
        pts["hover"] = [
            f"<b>{r['node']}</b>（{i}）<br>首例：{r['first_case']:%Y-%m-%d}<br>累計確診：{int(r['cases']):,}"
            + (f"<br>推定來源：{src.loc[i, 'from_iso3']}（{EVIDENCE_ZH.get(src.loc[i, 'evidence'], '')}"
               + (f"，機率 {src.loc[i, 'probability']:.0%}" if pd.notna(src.loc[i, 'probability']) else "") + "）"
               if i in src.index else "<br>起點")
            for i, r in pts.iterrows()]
        live = routes[routes["date"] <= d]
        recent = live[live["date"] > d - pd.Timedelta(days=RECENT_DAYS)]
        old = live[live["date"] <= d - pd.Timedelta(days=RECENT_DAYS)]
        o_lon, o_lat = arc_lists(old, loc)
        r_lon, r_lat = arc_lists(recent, loc)
        today = key_events[(key_events["date"] <= d) & (key_events["date"] > d - pd.Timedelta(days=4))]
        note = "；".join(today["description"].unique())
        title = f"<b>{d:%Y-%m-%d}</b>　已有 {len(pts) - 1} 個國家／地區出現病例" + (f"　｜　{note}" if note else "")
        frames.append(go.Frame(name=d.strftime("%m/%d"), layout=go.Layout(title_text=title), data=[
            go.Scattergeo(lon=o_lon, lat=o_lat, mode="lines", line=dict(width=0.6, color="rgba(120,120,120,0.35)"), hoverinfo="skip"),
            go.Scattergeo(lon=r_lon, lat=r_lat, mode="lines", line=dict(width=1.8, color="rgba(209,73,91,0.85)"), hoverinfo="skip"),
            go.Scattergeo(lon=pts["lon"], lat=pts["lat"], mode="markers", text=pts["hover"], hoverinfo="text",
                          marker=dict(size=pts["size"], color=pts["color"], line=dict(width=0.6, color="white"), opacity=0.9)),
        ]))

    o = loc.loc[ORIGIN]
    fig = go.Figure(data=list(frames[0].data) + [
        go.Scattergeo(lon=[o["lon"]], lat=[o["lat"]], mode="markers+text", text=["武漢（起點）"],
                      textposition="bottom center", hoverinfo="skip",
                      marker=dict(size=16, symbol="star", color="#d1495b", line=dict(width=1, color="white")))],
        frames=frames)
    # 圖例（用不顯示資料的假 trace）
    for c, col in CONT_COLORS.items():
        fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="markers", marker=dict(size=9, color=col), name=CONT_ZH[c]))
    fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="lines", line=dict(width=2, color="rgba(209,73,91,0.85)"), name=f"近 {RECENT_DAYS} 天的擴散路線"))
    fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="lines", line=dict(width=1, color="rgba(120,120,120,0.5)"), name="較早的擴散路線"))
    for i in range(4):
        fig.data[i].showlegend = False

    fig.update_layout(
        title=dict(text=frames[0].layout.title.text, x=0.01, y=0.975, font=dict(size=16)),
        geo=dict(projection_type="natural earth", showcountries=True, countrycolor="#d9d9d9",
                 showland=True, landcolor="#f4f1ea", showocean=True, oceancolor="#ffffff",
                 coastlinecolor="#cccccc", showframe=False),
        height=720, margin=dict(l=10, r=10, t=96, b=56),
        legend=dict(orientation="h", x=0.01, y=1.0, xanchor="left", yanchor="bottom", font=dict(size=12)),
        font=dict(family="Microsoft JhengHei, PingFang TC, Noto Sans TC, sans-serif"),
        annotations=[dict(text="初版：路線由航線數 × 來源地近 14 天新增確診推算，非確定的傳播紀錄。資料：JHU CSSE、WHO、OpenFlights",
                          x=0.01, y=-0.075, yanchor="top", xref="paper", yref="paper", showarrow=False, font=dict(size=11, color="#777"))],
        updatemenus=[dict(type="buttons", x=0.01, y=0.93, xanchor="left", showactive=False, buttons=[
            dict(label="▶ 播放", method="animate", args=[None, dict(frame=dict(duration=180, redraw=True), fromcurrent=True, transition=dict(duration=0))]),
            dict(label="⏸ 暫停", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
        ])],
        sliders=[dict(active=0, x=0.1, len=0.88, y=0.06, currentvalue=dict(visible=False), steps=[
            dict(label=f.name, method="animate", args=[[f.name], dict(frame=dict(duration=0, redraw=True), mode="immediate")])
            for f in frames])],
    )
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "first_case_spread_map.html"
    fig.write_html(out, include_plotlyjs=True, full_html=True, auto_play=False,
                   config={"displaylogo": False, "scrollZoom": True})
    print(f"完成：{out.relative_to(ROOT)}（{len(frames)} 天，{out.stat().st_size / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
