# COVID-19 Web Scraped Data — 全球病毒擴散模擬器

從武漢出發、沿國際航線擴散到全球的 COVID-19 模擬器。
主畫面：世界地圖 + 關鍵擴散時機點 + 擴散點 + 擴散路線。

**線上版：** [互動模擬器](https://f2855631.github.io/covid19-spread-simulator/simulator.html)　·　[各國首例擴散地圖](https://f2855631.github.io/covid19-spread-simulator/first_case_spread_map.html)


## 目前進度
- [x] 階段一：資料收集（`scraper/`）
- [x] 階段二：清理與探索（`scraper/clean_cases.py`、`model/flights.py`、`model/infer_routes.py`、`notebooks/01_explore.py`）
- [x] 階段三：建立模型（`model/seir.py`、`model/params.yaml`、`tests/test_seir.py`）
- [x] 階段四：校準（`model/calibrate.py`，600 次模擬約 2 分鐘）
- [x] 階段五：互動模擬器（`docs/simulator.html`；模型移植到 `app/sim_core.js`，與 Python 版結果一致）
- [x] 階段六：驗證與展示（`model/validate.py` 驗證報告數據；`app/abm_core.js`、`app/abm_ui.js` 個體模擬分頁；簡報）

## 快速開始
```
pip install -r requirements.txt
python scraper/download_data.py        # 下載原始資料到 data/raw/
python scraper/scrape_who_sitreps.py   # 爬 WHO 早期情勢報告 → 事件時間線
python scraper/build_first_cases.py    # 產出各國首例日表與事件表
python scraper/clean_cases.py          # 整理每日確診表
python model/flights.py                # 建立國家間航班矩陣
python model/infer_routes.py           # 推算初版擴散路線
python notebooks/01_explore.py         # 探索分析圖表 → docs/
python app/first_case_map.py           # 動態世界地圖 → docs/first_case_spread_map.html
python model/run_hubei.py              # 湖北單一區域 SEIR 擬合 → docs/fig4（加 --write-params 寫回參數檔）
python model/seir.py                   # 全球模擬 → data/model_output/（加 --stochastic --seed 1 為隨機版）
python model/calibrate.py --write-params  # 校準 7 個全球參數並寫回 params.yaml（約 2–5 分鐘）
python model/plot_global.py            # 模型 vs 真實首例日 → docs/fig5
python model/plot_calibration.py       # 中國以外確診曲線 → docs/fig6、首例日對照表
python model/validate.py               # 驗證：基準比較、分洲誤差、50 次隨機模擬、敏感度 → data/model_output/validation_*
python app/build_web_data.py           # 組出互動模擬器 → docs/simulator.html
python -m pytest tests/ -q             # 單元測試（含網頁版與 Python 版一致性檢查，需 Node.js）
```

## 互動模擬器
雙擊 `docs/simulator.html` 用瀏覽器開啟（需連網載入 d3 與字型）。
- 世界地圖：國家依每百萬人確診著色；擴散點依首例日出現；紅色弧線為近 7 天的擴散路線。
- 時間軸：關鍵擴散時機點（首例輸入、跨洲跳躍、擴散樞紐、本土傳播、政策事件），可依類型篩選、只顯示重要度前 N 名，點一下跳到當天。
- 情境參數：R0、防疫效果、武漢封城日期與強度、國際航班量、全球航班管制、病毒起點；與校準基準並列比較。
- 「模擬 / 真實資料」切換；點國家可看首例日（模型 vs 真實）與感染來源鏈。
- 「個體模擬」分頁：2,500 人在家、工作、商店間移動的城市示意模型，可設定封城日，比較早封與晚封的感染人數（示意用，未校準）。
- 修改模型後：`python app/build_web_data.py` 重新產生網頁；`app/sim_core.js` 若有改動，務必跑 `python -m pytest tests/` 確認與 Python 版一致。

## 目前成果
- `docs/first_case_spread_map.html`：雙擊用瀏覽器開啟，按「播放」看病毒從武漢擴散到全球（需連網載入底圖）
- `docs/fig1–3_*.png`、`docs/explore_summary.md`：探索分析
- `docs/fig4_hubei_seir_fit.png`：湖北 SEIR 與真實確診疊圖（誤差約 ×1.37）
- `docs/fig5_sim_vs_obs_first_case.png`：校準後各國首例日 vs 真實（最早 30 國平均誤差 5.8 天；177 國中 84% 在 ±14 天內）
- `docs/fig6_calibrated_curve_outside_china.png`：校準後中國以外確診曲線（每日新增誤差約 ×1.22；4 月的趨平未完全重現）
- `data/model_output/first_case_comparison.csv`：各國首例日對照表（訓練 / 測試組、誤差、推定來源）

## 校準結果（第四階段）
| 指標 | 校準前 | 校準後 | 目標 |
| --- | --- | --- | --- |
| 最早 30 國首例日平均誤差 | 17.5 天 | 5.8 天 | ≤ 14 天 ✔ |
| 訓練組（2/29 前首例，59 國）平均誤差 | — | 6.4 天，86% 在 ±14 天內 | |
| 測試組（3 月首例，118 國，未參與校準） | — | 11.4 天，75% 在 ±14 天內 | |
| 中國以外累計確診 MAPE（2/15–4/15） | — | 43% | < 30% ✘ |
| 一次全球模擬時間 | — | 約 2–5 秒 | < 5 秒 ✔ |

已知限制：4 月歐美封城後的每日新增趨平未完全重現（只用單一嚴格指數，且未模擬檢測量上限）；
「疫調量能」機制被校準為 ≈ 0，表示目前資料無法支持它。

## 模型重點（詳見 `model/params.yaml` 註解）
- 每個國家一組 SEIR，湖北獨立；國家之間用 OpenFlights 航線 × 每航線每日 150 人連動，並納入經中國樞紐轉機。
- 傳播率隨 OxCGRT 嚴格指數下降：β(t) = R0·γ·(1 − k·嚴格指數/100)；入境旅客依 C8 入境管制等級打折。
- 2020-01-23 武漢封城後湖北對外移動減少 95%；病毒基因序列 2020-01-11 公開前無法確診。
- 只依賴 numpy / pandas / pyyaml；不需要 scipy。
資料來源與欄位說明見 `data/README.md`。
