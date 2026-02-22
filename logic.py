"""
세금 계산기 API (2025년 기준)
- 양도소득세 계산기
- 증여세 계산기
- 취득세 계산기

실행 방법:
  uvicorn logic:app --reload --port 8000

필요 패키지:
  pip install fastapi uvicorn aiofiles
"""

import math
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="세금 계산기 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 세율표 데이터 (2025년)
# ============================================================

# 양도소득세: 일반 주택/상가/토지 기본세율
BASIC_TAX_TABLE = [
    {"min": 0,             "max": 14_000_000,    "rate": 0.06, "deduction": 0},
    {"min": 14_000_000,    "max": 50_000_000,    "rate": 0.15, "deduction": 1_260_000},
    {"min": 50_000_000,    "max": 88_000_000,    "rate": 0.24, "deduction": 5_760_000},
    {"min": 88_000_000,    "max": 150_000_000,   "rate": 0.35, "deduction": 15_440_000},
    {"min": 150_000_000,   "max": 300_000_000,   "rate": 0.38, "deduction": 19_940_000},
    {"min": 300_000_000,   "max": 500_000_000,   "rate": 0.40, "deduction": 25_940_000},
    {"min": 500_000_000,   "max": 1_000_000_000, "rate": 0.42, "deduction": 35_940_000},
    {"min": 1_000_000_000, "max": float("inf"),  "rate": 0.45, "deduction": 65_940_000},
]

# 양도소득세: 비사업용 토지 (기본세율+10%)
NON_BUSINESS_LAND_TABLE = [
    {"min": 0,             "max": 14_000_000,    "rate": 0.16, "deduction": 0},
    {"min": 14_000_000,    "max": 50_000_000,    "rate": 0.25, "deduction": 1_260_000},
    {"min": 50_000_000,    "max": 88_000_000,    "rate": 0.34, "deduction": 5_760_000},
    {"min": 88_000_000,    "max": 150_000_000,   "rate": 0.45, "deduction": 15_440_000},
    {"min": 150_000_000,   "max": 300_000_000,   "rate": 0.48, "deduction": 19_940_000},
    {"min": 300_000_000,   "max": 500_000_000,   "rate": 0.50, "deduction": 25_940_000},
    {"min": 500_000_000,   "max": 1_000_000_000, "rate": 0.52, "deduction": 35_940_000},
    {"min": 1_000_000_000, "max": float("inf"),  "rate": 0.55, "deduction": 65_940_000},
]

# 양도소득세: 단기 양도 세율
SHORT_TERM_RATES = {
    "2년 미만 주택":      0.60,
    "2년 미만 건물 토지": 0.40,
    "1년 미만 주택":      0.70,
    "1년 미만 건물 토지": 0.50,
}

# 증여세 세율표
GIFT_TAX_TABLE = [
    {"min": 0,             "max": 100_000_000,   "rate": 0.10, "deduction": 0},
    {"min": 100_000_000,   "max": 500_000_000,   "rate": 0.20, "deduction": 10_000_000},
    {"min": 500_000_000,   "max": 1_000_000_000, "rate": 0.30, "deduction": 60_000_000},
    {"min": 1_000_000_000, "max": 3_000_000_000, "rate": 0.40, "deduction": 160_000_000},
    {"min": 3_000_000_000, "max": float("inf"),  "rate": 0.50, "deduction": 460_000_000},
]

# 증여재산공제 (10년 합산, 관계별)
GIFT_DEDUCTIONS = {
    "배우자":            600_000_000,
    "직계비속 (성인)":   50_000_000,
    "직계비속 (미성년)": 20_000_000,
    "직계존속":          50_000_000,
    "기타 친족":         10_000_000,
    "관계 없음":         0,
}


# ============================================================
# 공통 유틸: 세율표 적용
# ============================================================

def apply_tax_table(taxable: int, table: list) -> tuple:
    """세율표에서 (세액, 세율, 누진공제) 반환"""
    if taxable <= 0:
        return 0, table[0]["rate"], 0
    for b in table:
        if taxable <= b["max"]:
            tax = int(taxable * b["rate"] - b["deduction"])
            return tax, b["rate"], b["deduction"]
    last = table[-1]
    return int(taxable * last["rate"] - last["deduction"]), last["rate"], last["deduction"]


# ============================================================
# 양도소득세 계산
# ============================================================

def calc_special_deduction_rate(표구분: str, 보유기간: int, 거주기간: int) -> float:
    """장기보유특별공제율 계산
    - 표1 (일반): 보유기간 × 2% (3년 이상, 최대 15년 = 30%)
    - 표2 (1세대1주택): 보유기간 × 4% + 거주기간 × 4% (최대 80%)
    """
    if 표구분 == "표1":
        if 보유기간 < 3:
            return 0.0
        return min(보유기간, 15) * 0.02
    elif 표구분 == "표2":
        if 보유기간 < 3:
            return 0.0
        hold = min(보유기간, 10) * 0.04
        live = min(거주기간, 10) * 0.04 if 거주기간 >= 2 else 0.0
        return hold + live
    return 0.0


def calc_capital_gains_tax(
    양도물건: str,
    비과세여부: bool,
    보유기간: int,
    거주기간: int,
    장특공제표: str,
    공동명의: bool,
    중과세유형: str,
    양도가액: int,
    매입가액: int,
) -> dict:
    """양도소득세 계산 (2025년 기준)"""

    # ① 전체 양도차익 (공동명의 시 1/2)
    전체_양도차익 = (양도가액 - 매입가액) * (0.5 if 공동명의 else 1.0)

    # ② 비과세 양도차익 (1세대1주택, 12억 이하 전액 / 초과 시 비례 공제)
    비과세_양도차익 = 0.0
    if 비과세여부:
        if 양도가액 <= 1_200_000_000:
            비과세_양도차익 = 전체_양도차익
        else:
            비과세_양도차익 = 전체_양도차익 * (1_200_000_000 / 양도가액)

    # ③ 과세 양도차익
    과세_양도차익 = 전체_양도차익 - 비과세_양도차익

    # ④ 장기보유특별공제 (중과세 적용 시 배제)
    공제율 = 0.0
    장특공제 = 0
    if 중과세유형 == "없음":
        공제율 = calc_special_deduction_rate(장특공제표, 보유기간, 거주기간)
        장특공제 = int(과세_양도차익 * 공제율)

    # ⑤ 양도소득금액
    양도소득금액 = 과세_양도차익 - 장특공제

    # ⑥ 기본공제 (연 250만원)
    기본공제 = max(0, min(int(양도소득금액), 2_500_000))

    # ⑦ 과세표준
    과세표준 = max(0, int(양도소득금액) - 기본공제)

    # ⑧ 세율 적용 및 기본세액
    if 양도물건 in SHORT_TERM_RATES:
        단일세율 = SHORT_TERM_RATES[양도물건]
        기본세액 = int(과세표준 * 단일세율)
        적용세율, 누진공제 = 단일세율, 0
        세율라벨 = f"{int(단일세율 * 100)}% (단기세율)"
    elif 양도물건 == "비사업용 토지":
        기본세액, 적용세율, 누진공제 = apply_tax_table(과세표준, NON_BUSINESS_LAND_TABLE)
        세율라벨 = "기본세율 + 10%"
    else:
        기본세액, 적용세율, 누진공제 = apply_tax_table(과세표준, BASIC_TAX_TABLE)
        세율라벨 = "기본세율"

    # ⑨ 중과세 적용
    산출세액 = 기본세액
    if 중과세유형 == "20% 중과세":
        산출세액 = 기본세액 + int(과세표준 * 0.20)
    elif 중과세유형 == "30% 중과세":
        산출세액 = 기본세액 + int(과세표준 * 0.30)

    # ⑩ 지방소득세 (10%)
    지방소득세 = math.floor(산출세액 * 0.1)
    지방세포함_세액 = 산출세액 + 지방소득세

    # ⑪ 공동명의 시 전체 세금 (×2)
    최종세액 = 지방세포함_세액 * 2 if 공동명의 else 지방세포함_세액

    return {
        "전체_양도차익":   int(전체_양도차익),
        "비과세_양도차익": int(비과세_양도차익),
        "과세_양도차익":   int(과세_양도차익),
        "장특공제_공제율": 공제율,
        "장특공제":        장특공제,
        "양도소득금액":    int(양도소득금액),
        "기본공제":        기본공제,
        "과세표준":        과세표준,
        "세율라벨":        세율라벨,
        "적용세율":        적용세율,
        "누진공제":        int(누진공제),
        "기본세액":        int(기본세액),
        "산출세액":        int(산출세액),
        "지방소득세":      int(지방소득세),
        "지방세포함_세액": int(지방세포함_세액),
        "최종세액":        int(최종세액),
        "공동명의":        공동명의,
    }


# ============================================================
# 증여세 계산
# ============================================================

def calc_gift_tax(
    수증자_관계: str,
    증여재산가액: int,
    재차증여재산: int,
    비과세: int,
    과세가액_불산입: int,
    채무: int,
    납부세액공제: int,
) -> dict:
    """증여세 계산 (2025년 기준)"""

    # ① 증여세 과세가액
    증여세_과세가액 = 증여재산가액 + 재차증여재산 - 비과세 - 과세가액_불산입 - 채무

    # ② 증여재산공제 (관계별)
    증여재산공제 = GIFT_DEDUCTIONS.get(수증자_관계, 0)

    # ③ 과세표준
    과세표준 = max(0, 증여세_과세가액 - 증여재산공제)

    # ④ 산출세액
    산출세액, 적용세율, 누진공제 = apply_tax_table(과세표준, GIFT_TAX_TABLE)

    # ⑤ 신고세액공제 (3%)
    신고세액공제 = int(산출세액 * 0.03)

    # ⑥ 납부세액
    납부세액 = max(0, 산출세액 - 납부세액공제 - 신고세액공제)

    return {
        "증여세_과세가액":   int(증여세_과세가액),
        "증여재산공제":      int(증여재산공제),
        "과세표준":          int(과세표준),
        "적용세율":          적용세율,
        "누진공제":          int(누진공제),
        "산출세액":          int(산출세액),
        "납부세액공제":      int(납부세액공제),
        "신고세액공제":      int(신고세액공제),
        "납부세액":          int(납부세액),
    }


# ============================================================
# 취득세 계산
# ============================================================

def _housing_sale_1h(is_national: bool, nong: float, 취득가액: int) -> tuple:
    """주택 매매 1주택 (또는 비조정 2주택) 세율 반환"""
    if 취득가액 <= 600_000_000:
        return (0.01, nong, 0.001)           # 1.1% / 1.3%
    elif 취득가액 <= 900_000_000:
        # 6억 초과 9억 이하: (취득가액/3억 × 2 - 3)%
        rate = (취득가액 / 300_000_000 * 2 - 3) / 100
        edu  = rate * 0.1
        return (rate, nong, edu)
    else:
        return (0.03, nong, 0.003)           # 3.3% / 3.5%


def get_acquisition_rates(
    취득물건: str,
    취득원인: str,
    주택수: str,
    조정대상지역: bool,
    취득가액: int,
    기준시가_3억이상: bool,
    가구1주택_상속: bool,
) -> tuple:
    """(취득세율, 농특세율, 지방교육세율) 반환"""

    # ─── 일반 건물/토지 ───────────────────────────────────────
    if 취득물건 == "일반 건물/토지":
        return {
            "매매": (0.04,  0.002, 0.004),
            "증여": (0.035, 0.002, 0.003),
            "상속": (0.028, 0.002, 0.0016),
            "신축": (0.028, 0.002, 0.0016),
        }.get(취득원인, (0.04, 0.002, 0.004))

    # ─── 농지 ────────────────────────────────────────────────
    if 취득물건 == "농지":
        return {
            "매매": (0.03,  0.002, 0.002),
            "증여": (0.035, 0.002, 0.003),
            "상속": (0.023, 0.002, 0.0006),
        }.get(취득원인, (0.03, 0.002, 0.002))

    # ─── 주택 (국민주택 또는 국민주택 초과) ──────────────────
    is_national = "85이하" in 취득물건 or "85㎡이하" in 취득물건 or 취득물건 == "국민주택"
    nong = 0.0 if is_national else 0.002   # 농특세: 국민주택 면제

    if 취득원인 == "신축":
        return (0.028, nong, 0.0016)

    if 취득원인 == "상속":
        if 가구1주택_상속:
            return (0.008, 0.0, 0.0016)    # 0.96% (농특 면제)
        return (0.028, nong, 0.0016)       # 일반 상속

    if 취득원인 == "증여":
        if 조정대상지역 and 기준시가_3억이상:
            heavy_nong = 0.0 if is_national else 0.01
            return (0.12, heavy_nong, 0.004)   # 12.4% / 13.4%
        return (0.035, nong, 0.003)            # 3.8% / 4.0%

    # 매매
    if 주택수 == "1주택":
        return _housing_sale_1h(is_national, nong, 취득가액)

    if 주택수 == "2주택":
        if 조정대상지역:
            heavy_nong = 0.0 if is_national else 0.006
            return (0.08, heavy_nong, 0.004)   # 8.4% / 9.0%
        return _housing_sale_1h(is_national, nong, 취득가액)   # 비조정 → 1주택 동일

    if 주택수 == "3주택":
        if 조정대상지역:
            heavy_nong = 0.0 if is_national else 0.01
            return (0.12, heavy_nong, 0.004)   # 12.4% / 13.4%
        mid_nong = 0.0 if is_national else 0.006
        return (0.08, mid_nong, 0.004)         # 8.4% / 9.0%

    # 4주택 이상
    heavy_nong = 0.0 if is_national else 0.01
    return (0.12, heavy_nong, 0.004)           # 12.4% / 13.4%


def calc_acquisition_tax(
    취득물건: str,
    취득원인: str,
    주택수: str,
    조정대상지역: bool,
    취득가액: int,
    기준시가_3억이상: bool,
    가구1주택_상속: bool,
) -> dict:
    """취득세 계산 (2025년 기준)"""

    r_취득, r_농특, r_교육 = get_acquisition_rates(
        취득물건, 취득원인, 주택수, 조정대상지역,
        취득가액, 기준시가_3억이상, 가구1주택_상속,
    )

    취득세    = int(취득가액 * r_취득)
    농특세    = int(취득가액 * r_농특)
    지방교육세 = int(취득가액 * r_교육)
    합계      = 취득세 + 농특세 + 지방교육세

    return {
        "취득세율":     r_취득,
        "농특세율":     r_농특,
        "지방교육세율": r_교육,
        "합계세율":     r_취득 + r_농특 + r_교육,
        "취득세":       취득세,
        "농특세":       농특세,
        "지방교육세":   지방교육세,
        "합계":         합계,
    }


# ============================================================
# 재건축 양도소득세 계산
# ============================================================

def _years_between(start_date, end_date) -> int:
    """두 날짜 사이의 만 연수 (Excel DATEDIF "Y" 와 동일)"""
    years = end_date.year - start_date.year
    if (end_date.month, end_date.day) < (start_date.month, start_date.day):
        years -= 1
    return max(0, years)


def calc_reconstruction_deduction_rate(표구분: str, 보유기간: int, 거주기간: int) -> float:
    """재건축 장기보유특별공제율
    - 표1: 보유기간 × 2% (최대 15년 = 30%), 최소 보유 요건 없음
    - 표2: 보유 × 4% + 거주 × 4% (각 최대 10년), 보유 3년·거주 2년 미만 시 해당분 0
    """
    if 표구분 == "표1":
        return min(max(0, 보유기간), 15) * 0.02
    elif 표구분 == "표2":
        if 보유기간 < 3:
            return 0.0
        hold = min(보유기간, 10) * 0.04
        live = min(거주기간, 10) * 0.04 if 거주기간 >= 2 else 0.0
        return hold + live
    return 0.0


def calc_reconstruction_capital_gains_tax(
    신축양도가액:         int,
    신축필요경비:         int,
    권리가액:             int,
    청산금납부액:         int,
    종전취득가액:         int,
    종전필요경비:         int,
    신축양도일:           str,
    관리처분계획인가일:   str,
    종전취득일:           str,
    비과세여부:           bool,
    기존표구분:           str,
    기존거주기간:         int,
    청산금표구분:         str,
    청산금거주기간:       int,
    공동명의:             bool,
) -> dict:
    """재건축 양도소득세 계산 (원조합원 · 신축 주택 양도 · 청산금 납부 유형)"""
    from datetime import date, timedelta

    def parse_date(s: str) -> date:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))

    sale_date  = parse_date(신축양도일)
    mgmt_date  = parse_date(관리처분계획인가일)
    acq_date   = parse_date(종전취득일)
    sale_plus1 = sale_date + timedelta(days=1)   # DATEDIF "Y": 양도일 다음날 기준

    # ① 보유기간
    기존보유기간   = _years_between(acq_date,  sale_plus1)
    청산금보유기간 = _years_between(mgmt_date, sale_plus1)

    # ② 장특공제율
    기존공제율   = calc_reconstruction_deduction_rate(기존표구분,   기존보유기간,   기존거주기간)
    청산금공제율 = calc_reconstruction_deduction_rate(청산금표구분, 청산금보유기간, 청산금거주기간)

    # ③ 양도차익 구분
    전체양도차익      = 신축양도가액 - 신축필요경비 - 청산금납부액 - 종전취득가액 - 종전필요경비
    관처일전_양도차익 = 권리가액 - 종전취득가액 - 종전필요경비
    관처일후_양도차익 = 신축양도가액 - (권리가액 + 청산금납부액) - 신축필요경비

    총가액 = 권리가액 + 청산금납부액
    if 총가액 > 0:
        종전분_양도차익   = 관처일전_양도차익 + 관처일후_양도차익 * 권리가액   / 총가액
        청산금분_양도차익 = 관처일후_양도차익 * 청산금납부액 / 총가액
    else:
        종전분_양도차익   = float(전체양도차익)
        청산금분_양도차익 = 0.0

    # ④ 공동명의 (50%)
    factor = 0.5 if 공동명의 else 1.0
    종전분_양도차익   *= factor
    청산금분_양도차익 *= factor
    합계양도차익 = 종전분_양도차익 + 청산금분_양도차익

    # ⑤ 비과세 (1세대1주택 12억 한도)
    if 비과세여부:
        if 신축양도가액 <= 1_200_000_000:
            비과세양도차익 = 합계양도차익
        else:
            비과세양도차익 = 합계양도차익 * 1_200_000_000 / 신축양도가액
    else:
        비과세양도차익 = 0.0

    과세양도차익 = 합계양도차익 - 비과세양도차익

    # ⑥ 장특공제 (종전분·청산금분 비율로 분리 적용)
    if 합계양도차익 != 0:
        종전분_과세   = 과세양도차익 * 종전분_양도차익   / 합계양도차익
        청산금분_과세 = 과세양도차익 * 청산금분_양도차익 / 합계양도차익
    else:
        종전분_과세 = 청산금분_과세 = 0.0

    종전분_장특공제   = int(종전분_과세   * 기존공제율)
    청산금분_장특공제 = int(청산금분_과세 * 청산금공제율)
    총장특공제 = 종전분_장특공제 + 청산금분_장특공제

    # ⑦ 양도소득금액 → 기본공제 → 과세표준
    양도소득금액 = 과세양도차익 - 총장특공제
    기본공제     = max(0, min(int(양도소득금액), 2_500_000))
    과세표준     = max(0, int(양도소득금액) - 기본공제)

    # ⑧ 기본세율 적용
    산출세액, 적용세율, 누진공제 = apply_tax_table(과세표준, BASIC_TAX_TABLE)

    # ⑨ 지방소득세 (10%)
    지방소득세    = math.floor(산출세액 * 0.1)
    지방세포함세액 = 산출세액 + 지방소득세

    # ⑩ 공동명의 전체 세액
    최종세액 = 지방세포함세액 * 2 if 공동명의 else 지방세포함세액

    return {
        "기존보유기간":      기존보유기간,
        "청산금보유기간":    청산금보유기간,
        "기존공제율":        기존공제율,
        "청산금공제율":      청산금공제율,
        "전체양도차익":      int(전체양도차익),
        "관처일전_양도차익": int(관처일전_양도차익),
        "관처일후_양도차익": int(관처일후_양도차익),
        "종전분_양도차익":   int(종전분_양도차익),
        "청산금분_양도차익": int(청산금분_양도차익),
        "합계양도차익":      int(합계양도차익),
        "비과세양도차익":    int(비과세양도차익),
        "과세양도차익":      int(과세양도차익),
        "종전분_장특공제":   종전분_장특공제,
        "청산금분_장특공제": 청산금분_장특공제,
        "총장특공제":        총장특공제,
        "양도소득금액":      int(양도소득금액),
        "기본공제":          기본공제,
        "과세표준":          과세표준,
        "적용세율":          적용세율,
        "누진공제":          int(누진공제),
        "산출세액":          int(산출세액),
        "지방소득세":        int(지방소득세),
        "지방세포함세액":    int(지방세포함세액),
        "최종세액":          int(최종세액),
        "공동명의":          공동명의,
    }


# ============================================================
# Pydantic 요청 모델
# ============================================================

class CapitalGainsRequest(BaseModel):
    양도물건:   str  = "일반 주택 상가 토지"
    비과세여부: bool = False
    보유기간:   int  = 0
    거주기간:   int  = 0
    장특공제표: str  = "표1"
    공동명의:   bool = False
    중과세유형: str  = "없음"
    양도가액:   int  = 0
    매입가액:   int  = 0


class GiftTaxRequest(BaseModel):
    수증자_관계:     str = "직계비속 (성인)"
    증여재산가액:    int = 0
    재차증여재산:    int = 0
    비과세:          int = 0
    과세가액_불산입: int = 0
    채무:            int = 0
    납부세액공제:    int = 0


class AcquisitionTaxRequest(BaseModel):
    취득물건:         str  = "국민주택 (85㎡ 이하)"
    취득원인:         str  = "매매"
    주택수:           str  = "1주택"
    조정대상지역:     bool = True
    취득가액:         int  = 0
    기준시가_3억이상: bool = False
    가구1주택_상속:   bool = False


class ReconstructionRequest(BaseModel):
    신축양도가액:         int  = 0
    신축필요경비:         int  = 0
    권리가액:             int  = 0
    청산금납부액:         int  = 0
    종전취득가액:         int  = 0
    종전필요경비:         int  = 0
    신축양도일:           str  = "2025-01-01"
    관리처분계획인가일:   str  = "2020-01-01"
    종전취득일:           str  = "2015-01-01"
    비과세여부:           bool = True
    기존표구분:           str  = "표1"
    기존거주기간:         int  = 0
    청산금표구분:         str  = "표1"
    청산금거주기간:       int  = 0
    공동명의:             bool = False


# ============================================================
# API 엔드포인트
# ============================================================

@app.post("/api/capital-gains")
def api_capital_gains(req: CapitalGainsRequest):
    return calc_capital_gains_tax(
        req.양도물건, req.비과세여부, req.보유기간, req.거주기간,
        req.장특공제표, req.공동명의, req.중과세유형,
        req.양도가액, req.매입가액,
    )


@app.post("/api/gift-tax")
def api_gift_tax(req: GiftTaxRequest):
    return calc_gift_tax(
        req.수증자_관계, req.증여재산가액, req.재차증여재산,
        req.비과세, req.과세가액_불산입, req.채무, req.납부세액공제,
    )


@app.post("/api/acquisition-tax")
def api_acquisition_tax(req: AcquisitionTaxRequest):
    return calc_acquisition_tax(
        req.취득물건, req.취득원인, req.주택수, req.조정대상지역,
        req.취득가액, req.기준시가_3억이상, req.가구1주택_상속,
    )


@app.post("/api/reconstruction")
def api_reconstruction(req: ReconstructionRequest):
    return calc_reconstruction_capital_gains_tax(
        req.신축양도가액, req.신축필요경비, req.권리가액, req.청산금납부액,
        req.종전취득가액, req.종전필요경비,
        req.신축양도일, req.관리처분계획인가일, req.종전취득일,
        req.비과세여부, req.기존표구분, req.기존거주기간,
        req.청산금표구분, req.청산금거주기간, req.공동명의,
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# 정적 파일 서비스 (index.html, style.css, script.js)
_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=_DIR, html=True), name="static")
