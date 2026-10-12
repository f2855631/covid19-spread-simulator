# %% [markdown]
# # 01 探索分析：病毒如何從武漢擴散到全球
# 可直接 `python notebooks/01_explore.py` 執行，或在 VS Code 用「Run Cell」逐格執行。
# 圖存到 docs/，摘要數字印在終端機並存到 docs/explore_summary.md。

# %%
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd().parent
PROC, DOCS = ROOT / "data" / "processed", ROOT / "docs"
DOCS.mkdir(exist_ok=True)

# 中文字型：Windows 用微軟正黑體，Linux / macOS 用 Noto / 蘋方
CJK = ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC", "Heiti TC", "Noto Sans CJK JP", "Noto Sans CJK SC"]
have = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [f for f in CJK if f in have] + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 110})

CONT_COLORS = {"Asia": "#d1495b", "Europe": "#00798c", "North America": "#edae49",
               "South America": "#66a182", "Africa": "#8d6a9f", "Oceania": "#2e4057"}
CONT_ZH = {"Asia": "亞洲", "Europe": "歐洲", "North America": "北美洲",
           "South America": "南美洲", "Africa": "非洲", "Oceania": "大洋洲"}
EVENTS = [("2020-01-23", "武漢封城"), ("2020-01-30", "WHO 宣布 PHEIC"), ("2020-03-11", "WHO 宣布大流行")]

fc = pd.read_csv(PROC / "first_cases.csv", parse_dates=["first_case"])
fm = pd.read_csv(PROC / "flight_matrix.csv")
cases = pd.read_csv(PROC / "cases_daily.csv", parse_dates=["date"])
routes = pd.read_csv(PROC / "routes_inferred.csv")
summary = []

# %% [markdown]
# ## 圖 1：與中國的航線越多，首例出現得越早嗎？

# %%
china = fm[fm["from_iso3"].isin(["CHN", "CHN-HUB"])].groupby("to_iso3")["routes"].sum()
d = fc[~fc["iso3"].isin(["CHN", "CHN-HUB"])].copy()
d["routes_from_china"] = d["iso3"].map(china).fillna(0)
d["day"] = (d["first_case"] - pd.Timestamp("2019-12-31")).dt.days
early = d[d["first_case"] <= "2020-03-31"].dropna(subset=["continent"])

rho_all = early[["routes_from_china", "day"]].corr(method="spearman").iloc[0, 1]
linked = early[early["routes_from_china"] > 0]
rho_linked = linked[["routes_from_china", "day"]].corr(method="spearman").iloc[0, 1]
med_with = linked["first_case"].median()
med_without = early[early["routes_from_china"] == 0]["first_case"].median()
summary += [
    f"- 2020-03-31 前出現首例的國家／地區：{len(early)} 個，其中 {len(linked)} 個有直飛中國的航線",
    f"- 與中國航線數 vs 首例日的 Spearman 相關係數：{rho_all:.2f}（全部）、{rho_linked:.2f}（有直飛者）"
    "；負值代表航線越多、首例越早",
    f"- 首例日中位數：有直飛中國 {med_with:%Y-%m-%d}，沒有直飛 {med_without:%Y-%m-%d}"
    f"（相差 {(med_without - med_with).days} 天）",
]

fig, ax = plt.subplots(figsize=(10, 6))
for c, g in early.groupby("continent"):
    ax.scatter(g["routes_from_china"] + 1, g["first_case"], s=28, alpha=0.8,
               color=CONT_COLORS.get(c, "grey"), label=CONT_ZH.get(c, c), edgecolor="white", linewidth=0.5)
for _, r in early.nlargest(14, "routes_from_china").iterrows():
    ax.annotate(r["iso3"], (r["routes_from_china"] + 1, r["first_case"]), xytext=(4, 2),
                textcoords="offset points", fontsize=8, color="#333")
ax.set_xscale("log")
ax.set_xticks([1, 2, 6, 11, 51, 101, 201])
ax.set_xticklabels(["0", "1", "5", "10", "50", "100", "200"])
ax.minorticks_off()
ax.set_xlabel("從中國（含湖北）飛來的航線數（對數刻度，OpenFlights 2014）")
ax.set_ylabel("首例日")
ax.yaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
ax.invert_yaxis()
ax.set_title(f"與中國航線越多的國家，首例越早出現（Spearman ρ = {rho_all:.2f}）", loc="left", fontsize=13)
ax.legend(frameon=False, fontsize=9, ncol=3)
fig.tight_layout()
fig.savefig(DOCS / "fig1_first_case_vs_china_routes.png", dpi=150)

# %% [markdown]
# ## 圖 2：湖北、中國其他地區與全球其他地區的每日新增確診

# %%
c = cases[(cases["date"] > "2020-01-22") & (cases["date"] <= "2020-04-30")].copy()
c["group"] = c["iso3"].map(lambda x: "湖北" if x == "CHN-HUB" else ("中國其他地區" if x == "CHN" else "全球其他地區"))
g = c.groupby(["date", "group"])["new_confirmed_7d"].sum().unstack()

fig, ax = plt.subplots(figsize=(10, 5))
colors = {"湖北": "#d1495b", "中國其他地區": "#edae49", "全球其他地區": "#00798c"}
for col in ["湖北", "中國其他地區", "全球其他地區"]:
    ax.plot(g.index, g[col].where(g[col] >= 1), label=col, color=colors[col], linewidth=2)
ax.set_yscale("log")
ax.set_ylim(bottom=1)
ax.annotate("4/17 武漢修正\n確診數據", (pd.Timestamp("2020-04-20"), 46), xytext=(0, 18),
            textcoords="offset points", ha="center", fontsize=8, color="#d1495b")
ax.set_ylabel("每日新增確診（7 日平均，對數刻度）")
for dt, label in EVENTS:
    ax.axvline(pd.Timestamp(dt), color="#999", linestyle="--", linewidth=0.8)
    ax.text(pd.Timestamp(dt), ax.get_ylim()[1], f" {label}", fontsize=8, color="#555", va="top", rotation=90)
cross = g[g["全球其他地區"] > g["湖北"] + g["中國其他地區"]].index.min()
summary.append(f"- 全球其他地區的每日新增在 {cross:%Y-%m-%d} 首次超過整個中國")
ax.set_title(f"{cross:%m/%d} 起，中國以外的每日新增超過中國", loc="left", fontsize=13)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(DOCS / "fig2_daily_cases_hubei_vs_world.png", dpi=150)

# %% [markdown]
# ## 圖 3：病毒抵達的國家數，依大洲

# %%
days = pd.date_range("2020-01-20", "2020-04-30")
f3 = fc.dropna(subset=["first_case", "continent"])
counts = pd.DataFrame({cn: [(g3["first_case"] <= d_).sum() for d_ in days]
                       for cn, g3 in f3.groupby("continent")}, index=days)
order = ["Asia", "Europe", "North America", "Oceania", "Africa", "South America"]
counts = counts[[o for o in order if o in counts.columns]]

fig, ax = plt.subplots(figsize=(10, 5))
ax.stackplot(counts.index, counts.T.values, labels=[CONT_ZH[o] for o in counts.columns],
             colors=[CONT_COLORS[o] for o in counts.columns], alpha=0.85)
for dt, label in EVENTS:
    ax.axvline(pd.Timestamp(dt), color="#555", linestyle="--", linewidth=0.8)
    ax.text(pd.Timestamp(dt), counts.sum(axis=1).max() * 0.98, f" {label}", fontsize=8, color="#333", va="top", rotation=90)
n_mar1, n_apr1 = (f3["first_case"] <= "2020-03-01").sum(), (f3["first_case"] <= "2020-04-01").sum()
summary.append(f"- 已出現病例的國家／地區：2020-03-01 為 {n_mar1} 個，2020-04-01 為 {n_apr1} 個")
ax.set_title(f"三月一個月內，出現病例的國家從 {n_mar1} 個增加到 {n_apr1} 個", loc="left", fontsize=13)
ax.set_ylabel("已出現病例的國家／地區數")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
handles, labels = ax.get_legend_handles_labels()
ax.legend(handles[::-1], labels[::-1], frameon=False, loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=9)
fig.tight_layout()
fig.savefig(DOCS / "fig3_countries_reached_by_continent.png", dpi=150)

# %% [markdown]
# ## 推定擴散路線：誰是主要的「擴散樞紐」

# %%
hubs = routes.dropna(subset=["from_iso3"]).groupby("from_iso3").size().sort_values(ascending=False)
summary.append("- 初版推定路線中，傳入最多國家的來源：" +
               "、".join(f"{k}（{v} 國）" for k, v in hubs.head(6).items()))
direct_hubei = routes[routes["from_iso3"] == "CHN-HUB"]["to_iso3"].tolist()
summary.append(f"- 推定直接由湖北傳入：{'、'.join(direct_hubei)}")

# %%
text = "# 探索分析摘要\n\n" + "\n".join(summary) + "\n"
(DOCS / "explore_summary.md").write_text(text, encoding="utf-8")
print(text)
