"""下載全球 COVID-19 擴散模擬器所需的原始資料到 data/raw/。

用法：
    python scraper/download_data.py           # 已存在的檔案會略過
    python scraper/download_data.py --force   # 全部重新下載

每次下載都會記錄到 data/raw/manifest.csv（來源網址、下載時間、大小、SHA-256）。
"""
import argparse
import csv
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GEO = ROOT / "data" / "geo"

JHU = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master"
OWID = "https://raw.githubusercontent.com/owid/covid-19-data/master/public/data"
OPENFLIGHTS = "https://raw.githubusercontent.com/jpatokal/openflights/master/data"
NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
OXCGRT = "https://raw.githubusercontent.com/OxCGRT/covid-policy-dataset/main/data"

# (本機路徑, 網址, 說明)
SOURCES = [
    # 1. 各國每日確診 / 死亡（含中國各省，如湖北）— JHU CSSE，2023-03-10 封存
    (RAW / "jhu" / "time_series_covid19_confirmed_global.csv",
     f"{JHU}/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv",
     "JHU 各國/省 累計確診（日）"),
    (RAW / "jhu" / "time_series_covid19_deaths_global.csv",
     f"{JHU}/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_deaths_global.csv",
     "JHU 各國/省 累計死亡（日）"),
    (RAW / "jhu" / "UID_ISO_FIPS_LookUp_Table.csv",
     f"{JHU}/csse_covid_19_data/UID_ISO_FIPS_LookUp_Table.csv",
     "JHU 國家/省 對 ISO3、經緯度、人口 對照表"),
    # 2. OWID 總表：確診、死亡、人口、疫苗、OxCGRT 嚴格指數（WHO 來源）
    (RAW / "owid" / "owid-covid-data.csv", f"{OWID}/owid-covid-data.csv",
     "OWID 各國每日總表（含人口與嚴格指數）"),
    (RAW / "owid" / "vaccinations.csv", f"{OWID}/vaccinations/vaccinations.csv",
     "OWID 各國疫苗接種"),
    # 3. 國際航線網路（OpenFlights，航線資料截至 2014-06）
    (RAW / "openflights" / "routes.dat", f"{OPENFLIGHTS}/routes.dat", "OpenFlights 航線"),
    (RAW / "openflights" / "airports.dat", f"{OPENFLIGHTS}/airports.dat", "OpenFlights 機場"),
    (RAW / "openflights" / "countries.dat", f"{OPENFLIGHTS}/countries.dat", "OpenFlights 國家名對照"),
    # 4. 世界國界（Natural Earth 1:50m）
    (GEO / "ne_50m_admin_0_countries.geojson",
     f"{NATURAL_EARTH}/ne_50m_admin_0_countries.geojson", "Natural Earth 國界"),
    # 5. 各國防疫政策（OxCGRT）
    (RAW / "oxcgrt" / "OxCGRT_compact_national_v1.csv",
     f"{OXCGRT}/OxCGRT_compact_national_v1.csv", "OxCGRT 各國每日政策指標"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, retries: int = 3) -> None:
    """下載到 .part 暫存檔；中斷後重跑會從已下載的位置續傳。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            done = tmp.stat().st_size if tmp.exists() else 0
            headers = {"Range": f"bytes={done}-"} if done else {}
            with requests.get(url, stream=True, timeout=60, headers=headers) as r:
                if r.status_code == 416:  # 已經下載完整
                    tmp.replace(dest)
                    return
                r.raise_for_status()
                mode = "ab" if (done and r.status_code == 206) else "wb"
                with tmp.open(mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.replace(dest)
            return
        except requests.RequestException as e:
            print(f"  第 {attempt} 次失敗：{e}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"下載失敗：{url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已存在也重新下載")
    args = ap.parse_args()

    manifest = RAW / "manifest.csv"
    rows = []
    if manifest.exists():
        with manifest.open(encoding="utf-8") as f:
            rows = {r["path"]: r for r in csv.DictReader(f)}
    else:
        rows = {}

    for dest, url, desc in SOURCES:
        rel = dest.relative_to(ROOT).as_posix()
        if dest.exists() and not args.force:
            print(f"略過（已存在）：{rel}")
            if rel not in rows:  # 補上先前漏記的紀錄
                rows[rel] = {"path": rel, "url": url, "description": desc,
                             "downloaded_utc": datetime.fromtimestamp(dest.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "bytes": dest.stat().st_size, "sha256": sha256(dest)}
            continue
        print(f"下載：{desc} → {rel}")
        download(url, dest)
        rows[rel] = {
            "path": rel,
            "url": url,
            "description": desc,
            "downloaded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bytes": dest.stat().st_size,
            "sha256": sha256(dest),
        }
        time.sleep(1)  # 對伺服器客氣一點

    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["path", "url", "description", "downloaded_utc", "bytes", "sha256"])
        w.writeheader()
        w.writerows(rows.values())
    print(f"完成，紀錄寫入 {manifest.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
