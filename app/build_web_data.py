"""把模擬器網頁需要的資料打包成一個 JSON，並組出單檔網頁 docs/simulator.html。

網頁裡的模型（app/sim_core.js）是 model/seir.py 的 JavaScript 版本，參數相同時結果一致
（tests/test_js_parity.py 會檢查）。

輸入：data/processed/*.csv、data/raw/oxcgrt、model/params.yaml、app/world-110m.json（世界國界 TopoJSON）
輸出：app/web_data.json、docs/simulator.html（雙擊即可用瀏覽器開啟，需連網載入繪圖函式庫）
用法：python app/build_web_data.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pycountry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import seir  # noqa: E402

APP, DOCS = ROOT / "app", ROOT / "docs"

ZH = {
    "CHN-HUB": "湖北（武漢）", "CHN": "中國（湖北以外）", "TWN": "台灣", "HKG": "香港", "MAC": "澳門",
    "JPN": "日本", "KOR": "南韓", "PRK": "北韓", "MNG": "蒙古", "THA": "泰國", "VNM": "越南", "SGP": "新加坡",
    "MYS": "馬來西亞", "IDN": "印尼", "PHL": "菲律賓", "KHM": "柬埔寨", "LAO": "寮國", "MMR": "緬甸",
    "BRN": "汶萊", "TLS": "東帝汶", "IND": "印度", "PAK": "巴基斯坦", "BGD": "孟加拉", "NPL": "尼泊爾",
    "LKA": "斯里蘭卡", "BTN": "不丹", "MDV": "馬爾地夫", "AFG": "阿富汗", "IRN": "伊朗", "IRQ": "伊拉克",
    "SAU": "沙烏地阿拉伯", "ARE": "阿聯", "QAT": "卡達", "KWT": "科威特", "BHR": "巴林", "OMN": "阿曼",
    "YEM": "葉門", "JOR": "約旦", "LBN": "黎巴嫩", "SYR": "敘利亞", "ISR": "以色列", "PSE": "巴勒斯坦",
    "TUR": "土耳其", "CYP": "賽普勒斯", "GEO": "喬治亞", "ARM": "亞美尼亞", "AZE": "亞塞拜然",
    "KAZ": "哈薩克", "UZB": "烏茲別克", "KGZ": "吉爾吉斯", "TJK": "塔吉克", "RUS": "俄羅斯",
    "GBR": "英國", "IRL": "愛爾蘭", "FRA": "法國", "DEU": "德國", "ITA": "義大利", "ESP": "西班牙",
    "PRT": "葡萄牙", "NLD": "荷蘭", "BEL": "比利時", "LUX": "盧森堡", "CHE": "瑞士", "AUT": "奧地利",
    "SWE": "瑞典", "NOR": "挪威", "DNK": "丹麥", "FIN": "芬蘭", "ISL": "冰島", "POL": "波蘭",
    "CZE": "捷克", "SVK": "斯洛伐克", "HUN": "匈牙利", "ROU": "羅馬尼亞", "BGR": "保加利亞", "GRC": "希臘",
    "HRV": "克羅埃西亞", "SVN": "斯洛維尼亞", "SRB": "塞爾維亞", "BIH": "波士尼亞", "MNE": "蒙特內哥羅",
    "MKD": "北馬其頓", "ALB": "阿爾巴尼亞", "XKS": "科索沃", "UKR": "烏克蘭", "BLR": "白俄羅斯",
    "MDA": "摩爾多瓦", "LTU": "立陶宛", "LVA": "拉脫維亞", "EST": "愛沙尼亞", "MLT": "馬爾他",
    "MCO": "摩納哥", "SMR": "聖馬利諾", "VAT": "梵蒂岡", "AND": "安道爾", "LIE": "列支敦斯登",
    "USA": "美國", "CAN": "加拿大", "MEX": "墨西哥", "GTM": "瓜地馬拉", "HND": "宏都拉斯", "SLV": "薩爾瓦多",
    "NIC": "尼加拉瓜", "CRI": "哥斯大黎加", "PAN": "巴拿馬", "CUB": "古巴", "DOM": "多明尼加", "HTI": "海地",
    "JAM": "牙買加", "BHS": "巴哈馬", "TTO": "千里達及托巴哥", "BRB": "巴貝多", "BRA": "巴西",
    "ARG": "阿根廷", "CHL": "智利", "PER": "秘魯", "COL": "哥倫比亞", "VEN": "委內瑞拉", "ECU": "厄瓜多",
    "BOL": "玻利維亞", "PRY": "巴拉圭", "URY": "烏拉圭", "GUY": "蓋亞那", "SUR": "蘇利南",
    "AUS": "澳洲", "NZL": "紐西蘭", "PNG": "巴布亞紐幾內亞", "FJI": "斐濟",
    "EGY": "埃及", "DZA": "阿爾及利亞", "MAR": "摩洛哥", "TUN": "突尼西亞", "LBY": "利比亞", "SDN": "蘇丹",
    "NGA": "奈及利亞", "GHA": "迦納", "SEN": "塞內加爾", "CIV": "象牙海岸", "CMR": "喀麥隆", "ETH": "衣索比亞",
    "KEN": "肯亞", "TZA": "坦尚尼亞", "UGA": "烏干達", "RWA": "盧安達", "ZAF": "南非", "ZWE": "辛巴威",
    "ZMB": "尚比亞", "MOZ": "莫三比克", "AGO": "安哥拉", "NAM": "納米比亞", "BWA": "波札那",
    "COD": "剛果民主共和國", "COG": "剛果共和國", "MDG": "馬達加斯加", "MUS": "模里西斯", "SOM": "索馬利亞",
    "MLI": "馬利", "NER": "尼日", "BFA": "布吉納法索", "TCD": "查德", "GIN": "幾內亞", "BEN": "貝南", "TGO": "多哥",
}
CONT_ZH = {"Asia": "亞洲", "Europe": "歐洲", "North America": "北美洲", "South America": "南美洲",
           "Africa": "非洲", "Oceania": "大洋洲"}
EVENT_TYPES = {"first_case": "首例輸入", "continent_jump": "跨洲跳躍", "local_transmission_start": "本土傳播",
               "policy": "政策事件", "hub": "擴散樞紐"}


def main():
    p = seir.load_params()
    inp = seir.load_inputs(p)
    nodes, d0, T = inp.nodes, inp.dates[0], len(inp.dates)
    pos = {k: i for i, k in enumerate(nodes)}
    day = lambda x: int((pd.Timestamp(x) - d0).days)  # noqa: E731

    fc = pd.read_csv(seir.PROC / "first_cases.csv").set_index("iso3")
    cases = pd.read_csv(seir.PROC / "cases_daily.csv", parse_dates=["date"])
    cases = cases[cases["date"] <= inp.dates[-1]]

    num = {}
    for c in pycountry.countries:
        num[c.alpha_3] = c.numeric
    node_rows = []
    for i, iso in enumerate(nodes):
        r = fc.loc[iso] if iso in fc.index else None
        node_rows.append({
            "iso3": iso, "name": (r["node"] if r is not None else iso), "zh": ZH.get(iso, ""),
            "lat": round(float(r["lat"]), 3) if r is not None and pd.notna(r["lat"]) else None,
            "lon": round(float(r["lon"]), 3) if r is not None and pd.notna(r["lon"]) else None,
            "N": float(inp.N[i]),
            "cont": CONT_ZH.get(r["continent"], "") if r is not None and pd.notna(r["continent"]) else "",
            "obsFirst": day(inp.obs_first.iloc[i]) if pd.notna(inp.obs_first.iloc[i]) else None,
            "numeric": "156" if iso == "CHN" else num.get(iso),
        })

    ii, jj = np.nonzero(inp.routes)
    routes = [[int(a), int(b), int(inp.routes[a, b])] for a, b in zip(ii, jj)]

    # 觀察值：各節點累計確診（JHU 從 2020-01-22 開始）、中國以外總和
    cum = cases.pivot(index="date", columns="iso3", values="cum_confirmed").reindex(index=inp.dates, columns=nodes)
    obs_start = day(cases["date"].min())
    obs_cum = [[None if pd.isna(v) else int(v) for v in cum[iso].iloc[obs_start:]] for iso in nodes]
    outside = cum.drop(columns=["CHN", "CHN-HUB"]).sum(axis=1, min_count=1)

    ev = pd.read_csv(seir.PROC / "events.csv")
    ev = ev[(ev["date"] >= str(d0.date())) & (ev["date"] <= str(inp.dates[-1].date()))]
    events_real = [{"day": day(r["date"]), "node": pos.get(r["iso3"], -1), "type": r["event_type"],
                    "desc": r["description"]} for _, r in ev.iterrows() if r["iso3"] in pos or r["iso3"] == "WORLD"]
    ri = pd.read_csv(seir.PROC / "routes_inferred.csv").dropna(subset=["from_iso3"])
    routes_real = [{"day": day(r["date"]), "from": pos[r["from_iso3"]], "to": pos[r["to_iso3"]],
                    "prob": None if pd.isna(r["probability"]) else float(r["probability"]), "ev": r["evidence"]}
                   for _, r in ri.iterrows() if r["from_iso3"] in pos and r["to_iso3"] in pos]

    data = {
        "start": str(d0.date()), "T": T, "params": p, "nodes": node_rows, "routes": routes,
        "si": [[round(float(x), 2) for x in inp.stringency[:, i]] for i in range(len(nodes))],
        "c8": [[int(x) for x in inp.c8[:, i]] for i in range(len(nodes))],
        "obsStart": obs_start, "obsCum": obs_cum,
        "obsOutside": [None if pd.isna(v) else int(v) for v in outside.iloc[obs_start:]],
        "eventsReal": events_real, "routesReal": routes_real, "eventTypes": EVENT_TYPES,
        "globalEvents": [{"day": day("2020-01-30"), "desc": "WHO 宣布國際關注公共衛生緊急事件"},
                         {"day": day("2020-03-11"), "desc": "WHO 宣布全球大流行"}],
    }
    out = APP / "web_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"web_data.json：{len(nodes)} 個節點、{len(routes)} 個航線對、{T} 天、{out.stat().st_size / 1e6:.2f} MB")

    if not (APP / "simulator_template.html").exists():
        return
    tpl = (APP / "simulator_template.html").read_text(encoding="utf-8")
    world = (APP / "world-110m.json").read_text(encoding="utf-8")
    core = (APP / "sim_core.js").read_text(encoding="utf-8")
    abm_core = (APP / "abm_core.js").read_text(encoding="utf-8")
    abm_ui = (APP / "abm_ui.js").read_text(encoding="utf-8")
    html = (tpl.replace("/*__SIM_CORE__*/", core)
               .replace("/*__ABM_CORE__*/", abm_core)
               .replace("/*__ABM_UI__*/", abm_ui)
               .replace('"__WEB_DATA__"', json.dumps(data, ensure_ascii=False, separators=(",", ":")))
               .replace('"__WORLD__"', world))
    DOCS.mkdir(exist_ok=True)
    (DOCS / "simulator.html").write_text(html, encoding="utf-8")
    print(f"docs/simulator.html：{(DOCS / 'simulator.html').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
