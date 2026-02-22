/* ============================================================
   세금 계산기 프론트엔드 스크립트
   ============================================================ */

const API = "http://localhost:8000";

// ──────────────────────────────────────────────
// 탭 전환
// ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((s) => s.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

// ──────────────────────────────────────────────
// 숫자 포맷 유틸
// ──────────────────────────────────────────────
function fmt(n) {
  if (n === null || n === undefined) return "-";
  return Math.round(n).toLocaleString("ko-KR") + "원";
}

function fmtPct(v) {
  return (v * 100).toFixed(2).replace(/\.?0+$/, "") + "%";
}

/** 만/억 단위 한글 표시 */
function fmtKr(n) {
  if (!n || n === 0) return "";
  const eok = Math.floor(Math.abs(n) / 1_0000_0000);
  const man = Math.floor((Math.abs(n) % 1_0000_0000) / 10000);
  let s = n < 0 ? "약 -" : "약 ";
  if (eok > 0) s += eok + "억 ";
  if (man > 0) s += man + "만 ";
  return s + "원";
}

// ──────────────────────────────────────────────
// 금액 입력칸 — 쉼표 자동 포맷팅
// ──────────────────────────────────────────────

/** 입력칸에서 쉼표를 제거하고 정수로 파싱 */
function parseAmount(id) {
  const val = document.getElementById(id)?.value ?? "0";
  return parseInt(val.replace(/,/g, ""), 10) || 0;
}

/** 입력 이벤트: 숫자만 남기고 쉼표를 다시 찍음 */
function formatMoneyInput(input) {
  const raw = input.value.replace(/[^0-9]/g, "");
  const num = parseInt(raw, 10);
  if (!raw || isNaN(num)) {
    input.value = "";
    return 0;
  }
  input.value = num.toLocaleString("ko-KR");
  return num;
}

/** 금액 입력칸 초기화: 쉼표 포맷 + (옵션) 한글 단위 helper 표시 */
function attachMoneyInput(inputId, displayId) {
  const input = document.getElementById(inputId);
  if (!input) return;

  // 초기값도 포맷
  formatMoneyInput(input);

  // 입력할 때마다 포맷
  input.addEventListener("input", () => {
    const num = formatMoneyInput(input);
    if (displayId) {
      const disp = document.getElementById(displayId);
      if (disp) disp.textContent = fmtKr(num);
    }
  });

  // 초기 helper 표시
  if (displayId) {
    const disp = document.getElementById(displayId);
    if (disp) disp.textContent = fmtKr(parseAmount(inputId));
  }
}

// 모든 금액 입력칸에 포맷팅 적용
attachMoneyInput("cg-sale-price",     "cg-sale-price-display");
attachMoneyInput("cg-purchase-price", "cg-purchase-price-display");
attachMoneyInput("gt-amount",         "gt-amount-display");
attachMoneyInput("gt-prior");
attachMoneyInput("gt-nontax");
attachMoneyInput("gt-exclusion");
attachMoneyInput("gt-debt");
attachMoneyInput("gt-paid-credit");
attachMoneyInput("at-price",          "at-price-display");
attachMoneyInput("rc-sale-price",     "rc-sale-price-display");
attachMoneyInput("rc-expense");
attachMoneyInput("rc-rights");
attachMoneyInput("rc-settlement");
attachMoneyInput("rc-acq-price");
attachMoneyInput("rc-acq-expense");

// ──────────────────────────────────────────────
// 취득세: 입력 폼 동적 변경
// ──────────────────────────────────────────────
function updateAcquisitionForm() {
  const assetType = document.getElementById("at-asset-type").value;
  const reason    = document.getElementById("at-reason").value;

  const isHousing = assetType.startsWith("국민주택");

  const houseOpts   = document.getElementById("at-house-options");
  const giftOpts    = document.getElementById("at-gift-options");
  const inheritOpts = document.getElementById("at-inherit-options");

  houseOpts.style.display   = (isHousing && reason === "매매") ? "" : "none";
  giftOpts.style.display    = (isHousing && reason === "증여") ? "" : "none";
  inheritOpts.style.display = (isHousing && reason === "상속") ? "" : "none";
}

updateAcquisitionForm();

// ──────────────────────────────────────────────
// API 공통 호출 함수
// ──────────────────────────────────────────────
async function callAPI(endpoint, payload) {
  const res = await fetch(`${API}/api/${endpoint}`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `서버 오류 (${res.status})`);
  }
  return res.json();
}

// ──────────────────────────────────────────────
// 양도소득세 계산
// ──────────────────────────────────────────────
async function calcCapitalGains() {
  const payload = {
    양도물건:   document.getElementById("cg-asset-type").value,
    비과세여부: document.querySelector('[name="cg-exempt"]:checked').value === "true",
    보유기간:   parseInt(document.getElementById("cg-holding").value) || 0,
    거주기간:   parseInt(document.getElementById("cg-residence").value) || 0,
    장특공제표: document.getElementById("cg-deduction-table").value,
    공동명의:   document.querySelector('[name="cg-joint"]:checked').value === "true",
    중과세유형: document.getElementById("cg-surcharge").value,
    양도가액:   parseAmount("cg-sale-price"),
    매입가액:   parseAmount("cg-purchase-price"),
  };

  const resultEl = document.getElementById("cg-result");
  resultEl.style.display = "none";

  try {
    const d = await callAPI("capital-gains", payload);
    renderCapitalGains(d, payload.공동명의);
    resultEl.style.display = "block";
  } catch (e) {
    showError("cg-result", e.message);
  }
}

function renderCapitalGains(d, isJoint) {
  const final = document.getElementById("cg-final");
  final.innerHTML = `
    <div class="label">${isJoint ? "공동명의 전체 세금 (지방소득세 포함)" : "최종 납부세액 (지방소득세 포함)"}</div>
    <div class="amount">${fmt(d.최종세액)}</div>
    ${isJoint ? `<div class="sub">1인당 ${fmt(d.지방세포함_세액)}</div>` : ""}
  `;

  const rows = [
    ["전체 양도차익",       fmt(d.전체_양도차익)],
    ["비과세 양도차익",     fmt(d.비과세_양도차익)],
    ["과세 양도차익",       fmt(d.과세_양도차익)],
    ["장기보유특별공제",    `${fmt(d.장특공제)} <span class="rate">(${fmtPct(d.장특공제_공제율)})</span>`],
    ["양도소득금액",        fmt(d.양도소득금액)],
    ["기본공제",            fmt(d.기본공제)],
    ["과세표준",            fmt(d.과세표준)],
    ["적용세율",            `${fmtPct(d.적용세율)} (${d.세율라벨})`],
    ["누진공제",            fmt(d.누진공제)],
    ["산출세액 (기본)",     fmt(d.기본세액)],
    ...(d.산출세액 !== d.기본세액
      ? [["산출세액 (중과 후)", fmt(d.산출세액)]]
      : []),
    ["지방소득세 (10%)",    fmt(d.지방소득세)],
    ["지방세 포함 세액",    fmt(d.지방세포함_세액)],
    ...(isJoint ? [["공동명의 전체 세금", fmt(d.최종세액)]] : []),
  ];

  document.getElementById("cg-table").innerHTML = rows
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("");

  document.getElementById("cg-note").textContent =
    "※ 지방소득세 = 산출세액의 10%. 1세대1주택 비과세 한도 12억원 적용. 실제 세금은 필요경비·감면 등에 따라 달라질 수 있습니다.";
}

// ──────────────────────────────────────────────
// 증여세 계산
// ──────────────────────────────────────────────
async function calcGiftTax() {
  const payload = {
    수증자_관계:     document.getElementById("gt-relation").value,
    증여재산가액:    parseAmount("gt-amount"),
    재차증여재산:    parseAmount("gt-prior"),
    비과세:          parseAmount("gt-nontax"),
    과세가액_불산입: parseAmount("gt-exclusion"),
    채무:            parseAmount("gt-debt"),
    납부세액공제:    parseAmount("gt-paid-credit"),
  };

  const resultEl = document.getElementById("gt-result");
  resultEl.style.display = "none";

  try {
    const d = await callAPI("gift-tax", payload);
    renderGiftTax(d);
    resultEl.style.display = "block";
  } catch (e) {
    showError("gt-result", e.message);
  }
}

function renderGiftTax(d) {
  document.getElementById("gt-final").innerHTML = `
    <div class="label">최종 납부세액</div>
    <div class="amount">${fmt(d.납부세액)}</div>
    <div class="sub">산출세액 ${fmt(d.산출세액)} − 신고세액공제 ${fmt(d.신고세액공제)}</div>
  `;

  const rows = [
    ["증여세 과세가액",   fmt(d.증여세_과세가액)],
    ["증여재산공제",       fmt(d.증여재산공제)],
    ["과세표준",           fmt(d.과세표준)],
    ["적용세율",           fmtPct(d.적용세율)],
    ["누진공제",           fmt(d.누진공제)],
    ["산출세액",           fmt(d.산출세액)],
    ["납부세액공제",       fmt(d.납부세액공제)],
    ["신고세액공제 (3%)",  fmt(d.신고세액공제)],
    ["납부세액",           fmt(d.납부세액)],
  ];

  document.getElementById("gt-table").innerHTML = rows
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("");
}

// ──────────────────────────────────────────────
// 취득세 계산
// ──────────────────────────────────────────────
async function calcAcquisitionTax() {
  const assetType = document.getElementById("at-asset-type").value;
  const reason    = document.getElementById("at-reason").value;

  const isHousing = assetType.startsWith("국민주택");

  const zoneEl     = document.querySelector('[name="at-zone"]:checked');
  const giftZoneEl = document.querySelector('[name="at-gift-zone"]:checked');

  let 조정 = false;
  if (isHousing && reason === "매매" && zoneEl)     조정 = zoneEl.value === "true";
  if (isHousing && reason === "증여" && giftZoneEl) 조정 = giftZoneEl.value === "true";

  const payload = {
    취득물건:         assetType,
    취득원인:         reason,
    주택수:           document.getElementById("at-house-count").value,
    조정대상지역:     조정,
    취득가액:         parseAmount("at-price"),
    기준시가_3억이상: document.querySelector('[name="at-gift-value"]:checked')?.value === "true",
    가구1주택_상속:   document.querySelector('[name="at-inherit-1h"]:checked')?.value === "true",
  };

  const resultEl = document.getElementById("at-result");
  resultEl.style.display = "none";

  try {
    const d = await callAPI("acquisition-tax", payload);
    renderAcquisitionTax(d);
    resultEl.style.display = "block";
  } catch (e) {
    showError("at-result", e.message);
  }
}

function renderAcquisitionTax(d) {
  document.getElementById("at-final").innerHTML = `
    <div class="label">취득세 등 납부 합계</div>
    <div class="amount">${fmt(d.합계)}</div>
    <div class="sub">합계세율 ${fmtPct(d.합계세율)}</div>
  `;

  const rows = [
    ["취득세",       `${fmt(d.취득세)} <span class="rate">(${fmtPct(d.취득세율)})</span>`],
    ["농어촌특별세", `${fmt(d.농특세)} <span class="rate">(${fmtPct(d.농특세율)})</span>`],
    ["지방교육세",   `${fmt(d.지방교육세)} <span class="rate">(${fmtPct(d.지방교육세율)})</span>`],
    ["합계",         fmt(d.합계)],
  ];

  document.getElementById("at-table").innerHTML = rows
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("");
}

// ──────────────────────────────────────────────
// 재건축 양도소득세 계산
// ──────────────────────────────────────────────
async function calcReconstructionTax() {
  const payload = {
    신축양도가액:         parseAmount("rc-sale-price"),
    신축필요경비:         parseAmount("rc-expense"),
    권리가액:             parseAmount("rc-rights"),
    청산금납부액:         parseAmount("rc-settlement"),
    종전취득가액:         parseAmount("rc-acq-price"),
    종전필요경비:         parseAmount("rc-acq-expense"),
    신축양도일:           document.getElementById("rc-sale-date").value,
    관리처분계획인가일:   document.getElementById("rc-mgmt-date").value,
    종전취득일:           document.getElementById("rc-acq-date").value,
    비과세여부:           document.querySelector('[name="rc-exempt"]:checked').value === "true",
    기존표구분:           document.getElementById("rc-old-table").value,
    기존거주기간:         parseInt(document.getElementById("rc-old-residence").value) || 0,
    청산금표구분:         document.getElementById("rc-settle-table").value,
    청산금거주기간:       parseInt(document.getElementById("rc-settle-residence").value) || 0,
    공동명의:             document.querySelector('[name="rc-joint"]:checked').value === "true",
  };

  const resultEl = document.getElementById("rc-result");
  resultEl.style.display = "none";

  try {
    const d = await callAPI("reconstruction", payload);
    renderReconstructionTax(d, payload.공동명의);
    resultEl.style.display = "block";
  } catch (e) {
    showError("rc-result", e.message);
  }
}

function renderReconstructionTax(d, isJoint) {
  document.getElementById("rc-final").innerHTML = `
    <div class="label">${isJoint ? "공동명의 전체 세금 (지방소득세 포함)" : "최종 납부세액 (지방소득세 포함)"}</div>
    <div class="amount">${fmt(d.최종세액)}</div>
    ${isJoint ? `<div class="sub">1인당 ${fmt(d.지방세포함세액)}</div>` : ""}
  `;

  const rows = [
    ["▸ 양도차익 구분", ""],
    ["전체 양도차익",          fmt(d.전체양도차익)],
    ["관리처분인가일 전 양도차익", fmt(d.관처일전_양도차익)],
    ["관리처분인가일 후 양도차익", fmt(d.관처일후_양도차익)],
    ["종전 부동산 양도차익",   fmt(d.종전분_양도차익)],
    ["청산금 납부분 양도차익", fmt(d.청산금분_양도차익)],
    ["▸ 세금 계산", ""],
    ["합계 양도차익",          fmt(d.합계양도차익)],
    ["비과세 양도차익",        fmt(d.비과세양도차익)],
    ["과세 양도차익",          fmt(d.과세양도차익)],
    ["장특공제 (종전분)",      `${fmt(d.종전분_장특공제)} <span class="rate">(${fmtPct(d.기존공제율)}, ${d.기존보유기간}년 보유)</span>`],
    ["장특공제 (청산금분)",    `${fmt(d.청산금분_장특공제)} <span class="rate">(${fmtPct(d.청산금공제율)}, ${d.청산금보유기간}년 보유)</span>`],
    ["양도소득금액",           fmt(d.양도소득금액)],
    ["기본공제",               fmt(d.기본공제)],
    ["과세표준",               fmt(d.과세표준)],
    ["적용세율",               fmtPct(d.적용세율)],
    ["누진공제",               fmt(d.누진공제)],
    ["산출세액",               fmt(d.산출세액)],
    ["지방소득세 (10%)",       fmt(d.지방소득세)],
    ["지방세 포함 세액",       fmt(d.지방세포함세액)],
    ...(isJoint ? [["공동명의 전체 세금", fmt(d.최종세액)]] : []),
  ];

  document.getElementById("rc-table").innerHTML = rows
    .map(([k, v]) => {
      if (v === "") return `<tr><td colspan="2" class="rc-section-header">${k}</td></tr>`;
      return `<tr><td>${k}</td><td>${v}</td></tr>`;
    })
    .join("");

  document.getElementById("rc-note").textContent =
    `※ 기존 보유기간 ${d.기존보유기간}년 (공제율 ${(d.기존공제율 * 100).toFixed(0)}%), 청산금 납부분 보유기간 ${d.청산금보유기간}년 (공제율 ${(d.청산금공제율 * 100).toFixed(0)}%). 1세대1주택 비과세 한도 12억원 적용. 실제 세금은 세무사 상담을 통해 확인하시기 바랍니다.`;
}

// ──────────────────────────────────────────────
// 에러 표시
// ──────────────────────────────────────────────
function showError(panelId, msg) {
  const panel = document.getElementById(panelId);
  panel.style.display = "block";
  panel.innerHTML = `<div class="error-msg">⚠️ 오류: ${msg}<br><small>서버가 실행 중인지 확인하세요 (uvicorn logic:app --port 8000)</small></div>`;
}
