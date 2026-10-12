"""爬取 WHO 早期 COVID-19 情勢報告（Situation Reports），整理成各國逐日表與擴散事件。

資料來源：WHO 每日情勢報告 PDF（2020-01-21 起），使用 JHU CSSE GitHub 上的完整備份：
https://github.com/CSSEGISandData/COVID-19/tree/master/who_covid_19_situation_reports

輸出：
    data/raw/who_sitreps/*.pdf                      原始 PDF（快取，不重複下載）
    data/processed/who_sitrep_country_daily.csv     每份報告 × 國家：累計確診、傳播分類
    data/processed/who_sitrep_events.csv            擴散事件：WHO 首次列出、開始本土傳播
    data/processed/who_sitrep_unmatched.csv         無法對應國家的表格列（人工檢查用）

用法：
    python scraper/scrape_who_sitreps.py                 # 預設第 1–71 期（至 2020-03-31）
    python scraper/scrape_who_sitreps.py --until 101     # 抓到第 101 期（2020-04-30）
"""
import argparse
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pdfplumber
import pycountry
import requests

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "data" / "raw" / "who_sitreps"
OUT_DIR = ROOT / "data" / "processed"

REPO = "CSSEGISandData/COVID-19"
FOLDER = "who_covid_19_situation_reports/who_covid_19_sit_rep_pdfs"
LIST_URL = f"https://api.github.com/repos/{REPO}/contents/{FOLDER}"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/master/{FOLDER}"

# ---------------------------------------------------------------- 國家名稱對照
# WHO 報告用的名稱與 pycountry 不同的，在這裡補上（全部小寫比對）
EXTRA_ALIASES = {
    "republic of korea": "KOR",
    "korea, republic of": "KOR",
    "the united kingdom": "GBR",
    "united kingdom": "GBR",
    "united states of america": "USA",
    "iran (islamic republic of)": "IRN",
    "iran": "IRN",
    "russian federation": "RUS",
    "viet nam": "VNM",
    "lao people's democratic republic": "LAO",
    "republic of moldova": "MDA",
    "bolivia (plurinational state of)": "BOL",
    "venezuela (bolivarian republic of)": "VEN",
    "democratic republic of the congo": "COD",
    "congo": "COG",
    "united republic of tanzania": "TZA",
    "syrian arab republic": "SYR",
    "occupied palestinian territory": "PSE",
    "palestine": "PSE",
    "kosovo": "XKX",
    "côte d'ivoire": "CIV",
    "cote d'ivoire": "CIV",
    "turkey": "TUR",
    "türkiye": "TUR",
    "czechia": "CZE",
    "czech republic": "CZE",
    "north macedonia": "MKD",
    "holy see": "VAT",
    "brunei darussalam": "BRN",
    "the bahamas": "BHS",
    "bahamas": "BHS",
    "gambia": "GMB",
    "the gambia": "GMB",
    "eswatini": "SWZ",
    "cabo verde": "CPV",
    "curaçao": "CUW",
    "curacao": "CUW",
    "sint maarten": "SXM",
    "saint martin": "MAF",
    "saint barthélemy": "BLM",
    "réunion": "REU",
    "reunion": "REU",
    "united states virgin islands": "VIR",
    "northern mariana islands (commonwealth of the)": "MNP",
    "falkland islands (malvinas)": "FLK",
    "micronesia (federated states of)": "FSM",
    "netherlands": "NLD",
    "china": "CHN",
    "hong kong sar": "HKG",
    "hong kong sar, china": "HKG",
    "macao sar": "MAC",
    "macao sar, china": "MAC",
    "macau sar": "MAC",
    "taipei and environs": "TWN",
    "taipei municipality": "TWN",
    "hong kong special administrative region": "HKG",
    "macau special administrative region": "MAC",
    "republic of singapore": "SGP",
    "cote d ivoire": "CIV",
}

# 不是國家、但要保留的特殊項目
SPECIAL = {
    "international conveyance (diamond princess)": "DIAMOND_PRINCESS",
    "international conveyance": "DIAMOND_PRINCESS",
    "others": "DIAMOND_PRINCESS",
}

# 表格列前面可能黏著 WHO 區域名稱，先剝掉
REGION_PREFIXES = [
    "who wpro region", "who searo region", "who euro region", "who emro region",
    "who amro region", "who afro region", "who paho region",
    "western pacific region", "western pacific", "wpro",
    "south-east asia region", "south-east asia", "searo",
    "european region", "europe", "euro",
    "eastern mediterranean region", "eastern mediterranean", "emro",
    "region of the americas", "americas", "amro", "paho",
    "african region", "afro",
    "territories", "subtotal for all regions",
]

# 傳播分類（WHO 自 2020-02 底起在表格列出）
TRANSMISSION = [
    ("community transmission", "community"),
    ("local transmission", "local"),
    ("imported cases only", "imported"),
    ("under investigation", "under_investigation"),
]

MONTHS = "January|February|March|April|May|June"
DATE_RE = re.compile(rf"(\d{{1,2}})\s+({MONTHS})\s+2020")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("–", "-")
    s = re.sub(r"[*†‡§¶#]+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def build_alias_table() -> dict:
    table = {}
    for c in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            v = getattr(c, attr, None)
            if v:
                table[norm(v)] = c.alpha_3
    table.update({norm(k): v for k, v in EXTRA_ALIASES.items()})
    table.update({norm(k): v for k, v in SPECIAL.items()})
    return table


ALIASES = build_alias_table()
# 由長到短比對，避免 "Congo" 先吃掉 "Democratic Republic of the Congo"
ALIAS_KEYS = sorted(ALIASES, key=len, reverse=True)


def match_country(text: str):
    """回傳 (iso3, 名稱, 剩下的字串)；比對不到回傳 None。"""
    t = norm(text)
    for p in REGION_PREFIXES:
        if t.startswith(p + " "):
            t = t[len(p) + 1:]
            break
    for k in ALIAS_KEYS:
        if t.startswith(k) and (len(t) == len(k) or not t[len(k)].isalpha()):
            return ALIASES[k], k, t[len(k):].strip()
    return None


# ---------------------------------------------------------------- 下載
def list_pdfs() -> list:
    r = requests.get(LIST_URL, timeout=60)
    r.raise_for_status()
    out = []
    for item in r.json():
        m = re.match(r"(\d{8}).*?sitrep-?(\d+)?", item["name"])
        if not m:
            continue
        num = m.group(2)
        if num is None:  # 20200501-covid-19-sitrep.pdf 沒有期數，用日期推
            continue
        out.append((int(num), datetime.strptime(m.group(1), "%Y%m%d").date(), item["name"]))
    return sorted(out)


def fetch(name: str) -> Path:
    dest = PDF_DIR / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            r = requests.get(f"{RAW_URL}/{name}", timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)
            time.sleep(1)  # 每次請求間隔 1 秒
            return dest
        except requests.RequestException as e:
            print(f"  重試 {name}：{e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"下載失敗：{name}")


# ---------------------------------------------------------------- 解析
def parse_pdf(path: Path, sitrep: int, report_date: date):
    rows, unmatched = [], []
    with pdfplumber.open(path) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    full = "\n".join(pages)

    # 「資料截至」日期：Table 1 標題裡的日期，找不到就用報告日前一天
    as_of = None
    t1 = full.find("Table 1")
    if t1 >= 0:
        m = DATE_RE.search(full, t1, t1 + 400)
        if m:
            as_of = datetime.strptime(f"{m.group(1)} {m.group(2)} 2020", "%d %B %Y").date()
    if as_of is None:
        as_of = report_date - pd.Timedelta(days=1)

    in_china_province_table = False
    china_sum = 0  # 第 1–5 期中國按省分列（如 "China – Hubei Province 258"），加總成全國
    prev = ""      # 上一行：PDF 表格中長國名常被斷成兩行
    for raw_line in full.splitlines():
        line = raw_line
        low = line.lower()
        m_cn = re.match(r"^(?:\S+\s+)?china\s*[-–]\s*[a-z ]+?\s+(\d[\d,]*)\s*$", norm(line))
        if m_cn:
            china_sum += int(m_cn.group(1).replace(",", ""))
            prev = ""
            continue
        # 跳過「中國各省」表（第一個數字是人口，不是確診）
        if "provinces, regions and cities in china" in low or "province/" in low:
            in_china_province_table = True
            continue
        if in_china_province_table:
            if low.startswith("total"):
                in_china_province_table = False
            continue

        if not re.search(r"\d", line):
            prev = line
            continue
        hit = match_country(line)
        if not hit and prev:
            # 試著把上一行接回來："Bosnia and" + "Herzegovina 233 ..."
            hit = match_country(prev + " " + line)
        prev = ""
        if not hit:
            # 看起來像表格列（名稱 + 數字）卻對不到國家，記下來人工檢查
            if re.match(r"^[A-Z][A-Za-z().,'’\- ]{2,60}\s+\d", line) and not low.startswith(("total", "table", "figure")):
                unmatched.append({"sitrep": sitrep, "line": line.strip()})
            continue
        iso3, name, rest = hit
        nums = re.findall(r"(?<![\w.])\d[\d,]*(?![\w.])", rest)
        if not nums:
            continue
        # 排除敘述句：表格列在國家名稱後應該緊接數字
        rest = re.sub(r"^total\b", "", rest).strip()  # "China Total 571*"
        if not re.match(r"^[\s\d,()]*\d", rest):
            continue
        total = int(nums[0].replace(",", ""))
        trans = next((code for key, code in TRANSMISSION if key in low), None)
        rows.append({
            "sitrep": sitrep,
            "report_date": report_date.isoformat(),
            "data_as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
            "iso3": iso3,
            "name_in_report": name,
            "total_confirmed": total,
            "transmission": trans,
        })
    if china_sum and not any(r["iso3"] == "CHN" for r in rows):
        rows.insert(0, {
            "sitrep": sitrep, "report_date": report_date.isoformat(),
            "data_as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
            "iso3": "CHN", "name_in_report": "china (sum of provinces)",
            "total_confirmed": china_sum, "transmission": None,
        })
    return rows, unmatched


def build_events(daily: pd.DataFrame) -> pd.DataFrame:
    ev = []
    d = daily.sort_values(["data_as_of", "sitrep"])
    for iso3, g in d.groupby("iso3"):
        first = g.iloc[0]
        ev.append({
            "date": first["data_as_of"], "iso3": iso3, "event_type": "first_reported_by_who",
            "sitrep": int(first["sitrep"]), "total_confirmed": int(first["total_confirmed"]),
            "note": f"首次出現在 WHO 第 {int(first['sitrep'])} 期報告",
        })
        local = g[g["transmission"].isin(["local", "community"])]
        if len(local):
            r = local.iloc[0]
            ev.append({
                "date": r["data_as_of"], "iso3": iso3, "event_type": "local_transmission_start",
                "sitrep": int(r["sitrep"]), "total_confirmed": int(r["total_confirmed"]),
                "note": "WHO 分類由境外移入轉為本土傳播",
            })
    return pd.DataFrame(ev).sort_values(["date", "event_type", "iso3"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=int, default=71, help="抓到第幾期（預設 71 = 2020-03-31）")
    ap.add_argument("--pdf-dir", type=Path, default=None, help="改用本機已下載的 PDF 資料夾（測試用）")
    args = ap.parse_args()

    if args.pdf_dir:
        items = []
        for p in sorted(args.pdf_dir.glob("*.pdf")):
            m = re.match(r"(\d{8}).*?sitrep-?(\d+)", p.name)
            if m:
                items.append((int(m.group(2)), datetime.strptime(m.group(1), "%Y%m%d").date(), p.name))
        items.sort()
    else:
        items = list_pdfs()
    items = [x for x in items if x[0] <= args.until]
    print(f"共 {len(items)} 份報告（第 {items[0][0]}–{items[-1][0]} 期）")

    all_rows, all_unmatched = [], []
    for num, rdate, name in items:
        path = (args.pdf_dir / name) if args.pdf_dir else fetch(name)
        rows, unmatched = parse_pdf(path, num, rdate)
        # 同一份報告同一國家只留第一筆（表格），避免後段敘述重複
        seen = set()
        for r in rows:
            if r["iso3"] not in seen:
                seen.add(r["iso3"])
                all_rows.append(r)
        all_unmatched += unmatched
        print(f"  第 {num:>3} 期 {rdate}：{len(seen):>3} 個國家/地區")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily = pd.DataFrame(all_rows)
    daily.to_csv(OUT_DIR / "who_sitrep_country_daily.csv", index=False, encoding="utf-8")
    events = build_events(daily)
    events.to_csv(OUT_DIR / "who_sitrep_events.csv", index=False, encoding="utf-8")
    pd.DataFrame(all_unmatched).drop_duplicates("line").to_csv(
        OUT_DIR / "who_sitrep_unmatched.csv", index=False, encoding="utf-8")
    print(f"完成：{daily['iso3'].nunique()} 個國家/地區，{len(daily)} 筆逐日資料，{len(events)} 個事件")


if __name__ == "__main__":
    main()
