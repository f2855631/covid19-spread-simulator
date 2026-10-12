# 資料說明

所有原始檔放在 `raw/`（永不手動修改），下載紀錄（網址、時間、SHA-256）見 `raw/manifest.csv`。

## 原始資料（raw/、geo/）

| 檔案 | 來源 | 內容 | 時間範圍 / 注意 |
| --- | --- | --- | --- |
| `raw/jhu/time_series_covid19_confirmed_global.csv` | Johns Hopkins CSSE（GitHub） | 各國／省每日累計確診 | 2020-01-22 起；2023-03-10 封存 |
| `raw/jhu/time_series_covid19_deaths_global.csv` | 同上 | 各國／省每日累計死亡 | 同上 |
| `raw/jhu/UID_ISO_FIPS_LookUp_Table.csv` | 同上 | 國家／省 ↔ ISO3、經緯度、人口 | |
| `raw/owid/owid-covid-data.csv` | Our World in Data（GitHub） | 各國每日總表：確診、死亡、人口、洲、OxCGRT 嚴格指數等 | 確診資料來自 WHO |
| `raw/owid/vaccinations.csv` | 同上 | 各國疫苗接種 | |
| `raw/openflights/routes.dat`、`airports.dat`、`countries.dat` | OpenFlights（GitHub） | 67,663 條航線、機場座標 | 航線資料僅到 2014-06 |
| `geo/ne_50m_admin_0_countries.geojson` | Natural Earth（GitHub） | 世界國界 1:50m | |
| `raw/oxcgrt/OxCGRT_compact_national_v1.csv` | Oxford COVID-19 Government Response Tracker（GitHub） | 各國每日防疫政策指標 | |
| `raw/who_sitreps/*.pdf` | WHO 情勢報告（JHU GitHub 備份） | 第 1–71 期，2020-01-21 至 2020-03-31 | 爬蟲來源 |

## 整理後資料（processed/）

| 檔案 | 產生程式 | 欄位 |
| --- | --- | --- |
| `who_sitrep_country_daily.csv` | `scrape_who_sitreps.py` | sitrep、report_date、data_as_of、iso3、name_in_report、total_confirmed、transmission |
| `who_sitrep_events.csv` | 同上 | date、iso3、event_type（first_reported_by_who / local_transmission_start）、sitrep、total_confirmed、note |
| `who_sitrep_unmatched.csv` | 同上 | 對應不到國家的表格列，人工檢查用 |
| `first_cases.csv` | `build_first_cases.py` | node、iso3（湖北 = CHN-HUB）、first_case、first_case_jhu、first_reported_who、local_transmission_who、lat、lon、population、continent、各種旗標 |
| `events.csv` | 同上 | date、iso3、event_type（first_case / continent_jump / local_transmission_start / policy）、description |
| `cases_daily.csv` | `clean_cases.py` | date、iso3、node、cum/new confirmed、new_confirmed_7d、cum/new deaths、population、new_confirmed_7d_per_million（2020-01-22 至 2023-03-09，198 節點） |
| `cases_wide_2020H1.csv` | 同上 | 列 = 日期（2020-01-22 至 06-30），欄 = iso3，值 = 累計確診；模型校準用 |
| `flight_matrix.csv` | `model/flights.py` | from_iso3、to_iso3、routes（航線數，排除共掛班號；湖北機場獨立為 CHN-HUB） |
| `airports_nodes.csv` | 同上 | 機場 → 節點對照（除錯用） |
| `routes_inferred.csv` | `model/infer_routes.py` | date、to_iso3、from_iso3、probability、second_iso3、second_probability、n_candidates、routes、evidence（inferred / nearest_infected） |

## 模型輸出（model_output/，由 `model/seir.py`、`model/run_hubei.py` 產生）

| 檔案 | 欄位 |
| --- | --- |
| `sim_daily.csv` | date、iso3、S、E、I、R、new_inf（本地新增感染）、imports（移入感染者）、reported_cum（預期累計確診） |
| `sim_first_cases.csv` | iso3、sim_arrival（開始本地傳播）、sim_first_case（模型首例日）、obs_first_case、main_source / main_share、second_source / second_share、diff_days |
| `sim_flows.csv` | date、from_iso3、to_iso3、infected_travelers（≥ 0.05 人的每日感染者移動，畫擴散路線用） |
| `hubei_grid.csv` | 湖北網格搜尋每組參數的 log10 RMSE |
| `calibration_log.csv` | 校準每一次模擬的參數與指標（訓練 / 測試誤差、曲線誤差、目標函數 J） |
| `calibration_summary.csv` | 校準前後的參數與指標 |
| `first_case_comparison.csv` | iso3、group（訓練 / 測試 / 其他）、obs / sim 首例日、diff_days、推定來源 |

## 已知限制

- JHU 從 2020-01-22 才開始記錄；`first_case_censored = True` 代表真正首例可能更早。
- WHO 從資料截至 2020-02-27 的報告起才標註「傳播分類」；`local_transmission_censored = True` 代表「最晚在此日已本土傳播」。
- `first_case_conflict = True`：JHU 與 WHO 首例日相差超過 7 天（例如 JHU 事後回溯補登），清理階段需人工確認。
- WHO 早期報告把台灣、香港、澳門列在中國之下，JHU 則分開列；本專案依 JHU 分開處理。
- 累計值偶有下修（確診 172 天次、死亡 199 天次），`clean_cases.py` 以「之後的最小值往回填」平滑，避免負的每日新增。
- 智利首例改採 WHO 報告日期（JHU 事後回溯補登 2020-02-23 的 2 例）。
- 初版擴散路線是「航線數 × 來源地近 14 天新增確診 ÷ 人口」的粗估；起點湖北設為 2019-12-31（WHO 接獲武漢群聚通報）。
- 世界銀行航空旅客量（IS.AIR.PSGR）因網路限制尚未下載，需手動從 data.worldbank.org 下載後放到 `raw/worldbank/`。
