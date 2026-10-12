# COVID-19 Web Scraped Data — 全球病毒擴散模擬器

從武漢出發、沿國際航線擴散到全球的 COVID-19 模擬器。
主畫面：世界地圖 + 關鍵擴散時機點 + 擴散點 + 擴散路線。

**線上版：** [互動模擬器](https://f2855631.github.io/covid19-spread-simulator/simulator.html)　·　[各國首例擴散地圖](https://f2855631.github.io/covid19-spread-simulator/first_case_spread_map.html)


## 目前進度
- [x] 階段一：資料收集（`scraper/`）
- [x] 階段二：清理與探索（`scraper/clean_cases.py`、`model/flights.py`、`model/infer_routes.py`、`notebooks/01_explore.py`）
- [x] 階段三：建立模型（`model/seir.py`、`model/params.yaml`、`tests/test_seir.py`）
- [x] 階段四：校準（`model/calibrate.py` 全球與七個地區參數；`model/fit_countries.py` 各國傳播倍數）
- [x] 階段五：互動模擬器（`docs/simulator.html`；模型移植到 `app/sim_core.js`，與 Python 版結果一致）
- [x] 階段六：驗證與展示（`model/validate.py`、`model/validate_extended.py` 驗證；`app/abm_core.js`、`app/abm_ui.js` 個體模擬分頁；`docs/demo_script.md` 操作影片腳本；簡報）

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
python model/calibrate.py --write-params  # 校準 5 個全球參數 + 7 個地區的傳播倍數與通報率，寫回 params.yaml（約 5 分鐘）
python model/fit_countries.py          # 各國傳播倍數，讓 4/17–4/30 累計確診貼近真實 → model/country_contact.csv（約 15 秒）
python model/plot_global.py            # 模型 vs 真實首例日 → docs/fig5
python model/plot_calibration.py       # 中國以外確診曲線 → docs/fig6、首例日對照表
python model/validate.py               # 驗證：基準比較、分洲誤差、50 次隨機模擬、敏感度 → data/model_output/validation_*
python model/validate_extended.py      # 延長驗證：模擬到 6/30，比較沒用來校準的 5–6 月 → docs/fig7
python app/build_web_data.py           # 組出互動模擬器 → docs/simulator.html
python -m pytest tests/ -q             # 單元測試（含網頁版與 Python 版一致性檢查，需 Node.js）
```

## 互動模擬器
雙擊 `docs/simulator.html` 用瀏覽器開啟（需連網載入 d3 與字型）。
- 世界地圖：國家依每百萬人確診著色；擴散點依首例日出現；紅色弧線為近 7 天的擴散路線。
- 時間軸：關鍵擴散時機點（首例輸入、跨洲跳躍、擴散樞紐、本土傳播、政策事件），可依類型篩選、只顯示重要度前 N 名，點一下跳到當天。
- 情境參數：R0、防疫效果、武漢封城日期與強度、國際航班量、全球航班管制、病毒起點；與校準基準並列比較。
- 「模擬 / 真實資料」切換。
- 點國家：該國每日確診曲線（模型 vs 真實）或 SEIR 曲線、感染高峰日、高峰人數、總感染數、首例日與感染來源鏈。
- 情境比較：調整參數後逐國列出首例日差幾天；可按「設為比較基準 A」把目前情境存成 A，再和新的情境 B 比較。
- 匯出 CSV：各國結果（首例日、累計確診、總感染、高峰），以及選取國家的每日資料。
- 「個體模擬」分頁：2,500 人在家、工作、商店間移動的城市示意模型，可設定封城日，比較早封與晚封的感染人數（示意用，未校準）。
- 修改模型後：`python app/build_web_data.py` 重新產生網頁；`app/sim_core.js` 若有改動，務必跑 `python -m pytest tests/` 確認與 Python 版一致。

## 目前成果
- `docs/first_case_spread_map.html`：雙擊用瀏覽器開啟，按「播放」看病毒從武漢擴散到全球（需連網載入底圖）
- `docs/fig1–3_*.png`、`docs/explore_summary.md`：探索分析
- `docs/fig4_hubei_seir_fit.png`：湖北 SEIR 與真實確診疊圖（誤差約 ×1.37）
- `docs/fig5_sim_vs_obs_first_case.png`：各國首例日 vs 真實
- `docs/fig6_calibrated_curve_outside_china.png`：中國以外確診曲線與 4/30 各地區病例比例
- `docs/fig7_extended_validation.png`：延長驗證，8 個主要國家 3–6 月每日新增
- `data/model_output/first_case_comparison.csv`：各國首例日對照表（訓練 / 測試組、誤差、推定來源）

## 校準與驗證結果
第一版只比對「中國以外加總」的確診曲線，延長驗證時發現病例分到錯的國家：4/30 模型把 84% 的病例放在亞洲（真實 14%），
台灣 66.8 萬（真實 429）、義大利只有真實的 1%，總數卻因為高估與低估互相抵消而看起來正確。
第二版改成逐地區校準，並加上各國傳播倍數：

| 指標 | 第一版 | 第二版 | 目標 |
| --- | --- | --- | --- |
| 訓練組（2/29 前首例，59 國）平均誤差 | 6.4 天 | 7.0 天，81% 在 ±14 天內 | |
| 測試組（3 月首例，118 國，未參與校準） | 11.4 天，75% | **9.7 天，76% 在 ±14 天內** | |
| 基準：只看航線數／一律猜中位數（測試組） | 18.6／17.6 天 | 同左 | |
| 中國以外累計確診 MAPE（2/15–4/30） | 43% | **15%** | < 30% ✔ |
| 4/30 累計確診在真實 ±2 倍內的國家 | 12% | **84%（177 國）** | |
| 4/30 亞洲占中國以外病例 | 84%（真實 14%） | 18% | |
| 一次全球模擬時間（網頁） | 0.1–0.3 秒 | 同左 | < 5 秒 ✔ |

**沒用來校準的 5–6 月（`validate_extended.py`）：** 8 個主要國家 4 月的每日新增平均為真實的 ×1.00，
但 5 月 ×2.8、6 月 ×6.4。模型沒有重現歐洲封城後的下降：義大利、德國在 5–6 月出現模型裡才有的第二波。
結論：模型適合回答「病毒什麼時候、從哪裡到達各國」與「封城早晚的差別」，不適合預測各國每日病例數。

其他限制：
- 各國傳播倍數是為了讓 4 月底的累計確診對上而擬合的，吸收了模型沒描述的因素（隱性傳播鏈、檢測量、人口密度）；
  義大利需要 3.3 倍，反映模型讓病毒到義大利的時間太晚。
- 東亞與歐洲的地區通報率卡在 3% 下限，表示通報率與傳播倍數難以單獨分辨；歐洲的感染人數因此偏高
  （例如模型 4/30 義大利已有 24% 人口感染，2020 年 7 月義大利血清調查約 2.5%）。
- 隨機版的 10–90% 範圍只涵蓋 20% 的真實首例日，隨機版還需要另外校準。

## 模型重點（詳見 `model/params.yaml` 註解）
- 每個國家一組 SEIR，湖北獨立；國家之間用 OpenFlights 航線 × 每航線每日旅客數（校準值）連動，並納入經中國樞紐轉機。
- 傳播率：β(t) = R0·γ·地區倍數·各國倍數·(1 − k·嚴格指數/100)，嚴格指數來自 OxCGRT；入境旅客依 C8 入境管制等級打折。
- 通報率：3/1 前各國共用初期通報率，3/1–3/15 過渡到各地區通報率（七個地區見 `model/regions.py`）。
- 2020-01-23 武漢封城後湖北對外移動減少 95%；病毒基因序列 2020-01-11 公開前無法確診。
- 只依賴 numpy / pandas / pyyaml；不需要 scipy。
資料來源與欄位說明見 `data/README.md`。
