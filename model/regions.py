"""七個地區（參考世界銀行的分區）。

每個地區在 params.yaml 的 regions 底下有自己的
  contact：傳播倍數，β = R0 × γ × contact × (1 − k × 嚴格指數/100)
           吸收 OxCGRT 嚴格指數量不到的差異，例如東亞 2003 年 SARS 後的口罩習慣、
           大規模檢測與接觸者追蹤（台灣、南韓、新加坡），以及歐美 3 月前的無症狀擴散
  ratio：通報率（感染者中被確診的比例），反映各地區的檢測量
湖北（起點）不套用地區參數，沿用 run_hubei.py 的擬合結果。
"""

REGION_ZH = {
    "EAP": "東亞與太平洋", "ECA": "歐洲與中亞", "MENA": "中東與北非", "SAS": "南亞",
    "NAM": "北美（美加）", "LAC": "拉丁美洲與加勒比海", "SSA": "撒哈拉以南非洲",
}

_EAP = "BRN CHN CHN-HUB IDN JPN KHM KOR LAO MMR MNG MYS PHL PRK SGP THA TLS TWN VNM " \
       "AUS FJI FSM KIR MHL NRU NZL PLW PNG SLB TON TUV VUT WSM"
_SAS = "AFG BGD BTN IND LKA MDV NPL PAK"
_MENA = "ARE BHR IRN IRQ ISR JOR KWT LBN OMN PSE QAT SAU SYR YEM DZA EGY LBY MAR TUN DJI"
_ECA_ASIA = "ARM AZE GEO KAZ KGZ TJK TUR UZB XKS"
_NAM = "USA CAN"

_MAP = {}
for reg, s in [("EAP", _EAP), ("SAS", _SAS), ("MENA", _MENA), ("ECA", _ECA_ASIA), ("NAM", _NAM)]:
    for iso in s.split():
        _MAP[iso] = reg


def region_of(iso3: str, continent: str | None) -> str:
    if iso3 in _MAP:
        return _MAP[iso3]
    return {"Europe": "ECA", "Africa": "SSA", "North America": "LAC", "South America": "LAC",
            "Oceania": "EAP", "Asia": "EAP"}.get(continent or "", "ECA")
