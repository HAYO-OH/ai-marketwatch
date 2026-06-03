from datetime import date

import streamlit as st

st.set_page_config(
    page_title="AI MarketWatch",
    page_icon="📈",
    layout="wide",
)

# ── 전역 CSS ─────────────────────────────────────────────
st.markdown(
    "<style>"
    "@import url('https://cdn.jsdelivr.net/npm/pretendard@latest/dist/web/static/pretendard.css');"
    "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');"
    "html,body,*{font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif!important}"
    "[data-testid='stMetricValue'],[data-testid='stMetricDelta'],code,pre,table td,table th{"
    "font-family:'Inter','Pretendard',sans-serif!important}"
    "[data-testid='stAppViewContainer']{background:#f5f6fa}"
    "[data-testid='stHeader']{background:#f5f6fa}"
    "section[data-testid='stSidebar']{display:none!important}"
    "[data-testid='stSidebarCollapsedControl']{display:none!important}"
    "[data-testid='stSidebarNav']{display:none!important}"
    "[data-testid='block-container']{padding-top:0.6rem!important;padding-bottom:0.5rem!important}"
    "[data-testid='stVerticalBlock']{gap:0.3rem!important}"
    ".element-container{margin-bottom:0!important}"
    "[data-testid='stHorizontalBlock']{gap:0.6rem!important}"
    ".feat-card{"
    "transition:transform 0.18s,box-shadow 0.18s;cursor:default}"
    ".feat-card:hover{"
    "transform:translateY(-5px)!important;"
    "box-shadow:0 10px 28px rgba(26,39,68,0.13)!important}"
    ".stButton>button{"
    "background:#e63946!important;color:white!important;"
    "border:none!important;border-radius:6px!important;"
    "font-weight:700!important;font-size:0.85rem!important;"
    "padding:10px 16px!important;margin-top:8px!important;"
    "transition:background 0.15s,transform 0.12s!important}"
    ".stButton>button:hover{"
    "background:#c1121f!important;transform:translateY(-2px)!important;"
    "box-shadow:0 4px 12px rgba(230,57,70,0.3)!important}"
    ".stButton>button:active{transform:translateY(0)!important}"
    "</style>",
    unsafe_allow_html=True,
)

# ── 데이터 로딩 ───────────────────────────────────────────
search_results  = st.session_state.get("search_results")
earnings_result = st.session_state.get("earnings_result")

if search_results is not None:
    company_results = search_results["company_results"]
    df_all    = search_results["df_all"]
    found_cnt = sum(1 for r in company_results if r["found"])
    disc_cnt  = sum(len(r.get("raw_rows", [])) for r in company_results if r["found"])
    alert_cnt = st.session_state.get("last_alert_count", 0)
else:
    company_results = []
    df_all    = None
    found_cnt = disc_cnt = alert_cnt = 0

# 실적 요약 데이터
_beat_corp = ""
_beat_surprise = "UNKNOWN"
if earnings_result:
    _ea = earnings_result.get("analysis", {})
    _beat_corp     = earnings_result.get("corp_name", "")
    _beat_surprise = _ea.get("earnings_surprise", "UNKNOWN")

# ── 히어로 섹션 ───────────────────────────────────────────
_disc_disp  = f"{disc_cnt}건"  if search_results else "—"
_beat_disp  = _beat_corp       if _beat_corp      else "—"
_alert_disp = f"{alert_cnt}건" if search_results  else "—"

_beat_c  = "#00d084" if _beat_surprise == "BEAT" else (
           "#ff4b4b" if _beat_surprise == "MISS" else "white")
_alert_c = "#ff4b4b" if alert_cnt > 0 else "white"
_disc_c  = "#00d084" if disc_cnt > 0  else "white"

_mini_cards = (
    "<div style='display:flex;flex-direction:column;gap:10px;min-width:210px'>"

    f"<div style='background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);"
    f"border-radius:8px;padding:14px 18px'>"
    f"<div style='color:#8899bb;font-size:0.7rem;font-weight:600;letter-spacing:1px;"
    f"margin-bottom:6px'>수집된 공시</div>"
    f"<div style='color:{_disc_c};font-size:1.55rem;font-weight:700;line-height:1'>"
    f"{_disc_disp}</div></div>"

    f"<div style='background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);"
    f"border-radius:8px;padding:14px 18px'>"
    f"<div style='color:#8899bb;font-size:0.7rem;font-weight:600;letter-spacing:1px;"
    f"margin-bottom:6px'>최근 분석 기업</div>"
    f"<div style='color:{_beat_c};font-size:1.1rem;font-weight:700;line-height:1.2'>"
    f"{_beat_disp}"
    + (f"<span style='font-size:0.72rem;background:rgba(0,208,132,0.25);"
       f"color:#00d084;border-radius:3px;padding:1px 6px;margin-left:6px'>"
       f"{_beat_surprise}</span>" if _beat_corp else "")
    + "</div></div>"

    f"<div style='background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);"
    f"border-radius:8px;padding:14px 18px'>"
    f"<div style='color:#8899bb;font-size:0.7rem;font-weight:600;letter-spacing:1px;"
    f"margin-bottom:6px'>키워드 알림</div>"
    f"<div style='color:{_alert_c};font-size:1.55rem;font-weight:700;line-height:1'>"
    f"{_alert_disp}</div></div>"

    "</div>"
)

st.markdown(
    f"<div style='background:linear-gradient(135deg,#1a2744 0%,#253a6e 100%);"
    f"padding:44px 48px;border-radius:12px;margin-bottom:20px;"
    f"display:flex;align-items:center;justify-content:space-between;gap:32px'>"
    f"<div style='flex:1;min-width:0'>"
    f"<div style='color:#ff4b4b;font-size:0.73rem;font-weight:700;"
    f"letter-spacing:2.5px;text-transform:uppercase;margin-bottom:16px'>"
    f"AI-Powered Financial Platform</div>"
    f"<div style='color:white;font-size:2.1rem;font-weight:800;line-height:1.25;"
    f"margin-bottom:14px'>AI가 분석하는<br>금융 모니터링 플랫폼</div>"
    f"<div style='color:#8899bb;font-size:0.96rem;line-height:1.75'>"
    f"DART 공시 · 실적 분석 · 포트폴리오 리스크를<br>한 곳에서 모니터링하세요</div>"
    f"<div style='color:#4a5e7a;font-size:0.78rem;margin-top:18px'>"
    f"⏱ {date.today().strftime('%Y년 %m월 %d일')} 기준</div>"
    f"</div>"
    f"{_mini_cards}"
    f"</div>",
    unsafe_allow_html=True,
)

# ── 기능 소개 카드 3개 ────────────────────────────────────
def _feat_card(icon: str, title: str, f1: str, f2: str) -> str:
    return (
        f"<div class='feat-card' style='background:white;border:1px solid #e2e5ea;"
        f"border-radius:8px;padding:24px 20px;border-top:3px solid #1a2744'>"
        f"<div style='font-size:2rem;margin-bottom:12px'>{icon}</div>"
        f"<div style='font-size:0.97rem;font-weight:700;color:#1a2744;margin-bottom:10px'>"
        f"{title}</div>"
        f"<div style='font-size:0.82rem;color:#666;line-height:1.75'>"
        f"· {f1}<br>· {f2}</div>"
        f"</div>"
    )

fc1, fc2, fc3 = st.columns(3)

with fc1:
    st.markdown(
        _feat_card("📋", "DART 공시 모니터링",
                   "AI 자동 분류 · 중요도 1~10점 스코어링",
                   "키워드 알림 · 이상 공시 자동 탐지"),
        unsafe_allow_html=True,
    )
    if st.button("시작하기 →", key="go_dart", use_container_width=True):
        st.switch_page("pages/1_DART공시모니터링.py")

with fc2:
    st.markdown(
        _feat_card("📊", "실적 발표 요약",
                   "AI 실적 분석 · BEAT / MISS 판정",
                   "동종업계 비교 · 8분기 히스토리 차트"),
        unsafe_allow_html=True,
    )
    if st.button("시작하기 →", key="go_earn", use_container_width=True):
        st.switch_page("pages/2_실적발표요약.py")

with fc3:
    st.markdown(
        _feat_card("💼", "포트폴리오 리스크",
                   "AI 리스크 평가 · 변동성 분석",
                   "섹터 집중도 · 베타 계수 산출"),
        unsafe_allow_html=True,
    )
    if st.button("시작하기 →", key="go_port", use_container_width=True):
        st.switch_page("pages/3_포트폴리오리스크.py")

# ── 메트릭 바 ─────────────────────────────────────────────
_mbar_ac = "#ff4b4b" if alert_cnt > 0 else "#1a2744"
_mbar_dc = "#00d084" if disc_cnt  > 0 else "#1a2744"

def _mbar_cell(label: str, value: str, color: str = "#1a2744") -> str:
    return (
        f"<div style='text-align:center;padding:0 8px'>"
        f"<div style='color:#aaa;font-size:0.65rem;text-transform:uppercase;"
        f"letter-spacing:0.8px;margin-bottom:4px'>{label}</div>"
        f"<div style='color:{color};font-size:0.92rem;font-weight:700'>{value}</div>"
        f"</div>"
    )

_sep = "<div style='width:1px;height:30px;background:#e2e5ea'></div>"

st.markdown(
    f"<div style='background:white;border:1px solid #e2e5ea;border-radius:8px;"
    f"padding:14px 32px;display:flex;justify-content:space-around;"
    f"align-items:center;margin-top:16px;margin-bottom:20px'>"
    + _mbar_cell("오늘", date.today().strftime("%Y.%m.%d"))
    + _sep
    + _mbar_cell("마지막 조회", f"{found_cnt}개 기업" if search_results else "—")
    + _sep
    + _mbar_cell("키워드 알림", f"{alert_cnt}건" if search_results else "—", _mbar_ac)
    + _sep
    + _mbar_cell("수집된 공시", f"{disc_cnt}건"  if search_results else "—", _mbar_dc)
    + "</div>",
    unsafe_allow_html=True,
)

# ── 하단 데이터 섹션: 최근 공시 + 실적 서프라이즈 ───────────
col_l, col_r = st.columns([3, 2])
_CARD_MIN_H = "224px"

_HDR_L = (
    "<div style='background:#1a2744;color:white;padding:10px 14px;"
    "border-radius:4px 4px 0 0;font-size:0.8rem;font-weight:600;"
    "overflow:visible;white-space:nowrap'>📋 최근 공시</div>"
)
_HDR_R = (
    "<div style='background:#1a2744;color:white;padding:10px 14px;"
    "border-radius:4px 4px 0 0;font-size:0.8rem;font-weight:600;"
    "overflow:visible;white-space:nowrap'>📊 실적 서프라이즈</div>"
)
_BODY_WRAP = (
    f"<div style='border:1px solid #e2e5ea;border-top:none;"
    f"border-radius:0 0 4px 4px;background:white;min-height:{_CARD_MIN_H}'>"
)
_EMPTY_BODY = (
    f"<div style='border:1px solid #e2e5ea;border-top:none;"
    f"border-radius:0 0 4px 4px;background:white;min-height:{_CARD_MIN_H};"
    f"display:flex;align-items:center;justify-content:center;"
    f"color:#bbb;font-size:0.85rem'>아직 조회된 데이터 없음</div>"
)

with col_l:
    if df_all is not None and not df_all.empty:
        _rows_html = ""
        for _, row in df_all.sort_values("중요도", ascending=False).head(6).iterrows():
            score = int(row.get("중요도", 1))
            bg = "#ff4b4b" if score >= 9 else ("#f0a500" if score >= 7 else "#8899bb")
            cat = row.get("카테고리", "")
            cat_html = (
                f"<span style='font-size:0.64rem;background:#eef3fb;color:#2563eb;"
                f"border-radius:3px;padding:1px 5px;flex-shrink:0;white-space:nowrap'>"
                f"{cat}</span>"
            ) if cat else ""
            _rows_html += (
                f"<div style='display:flex;align-items:center;padding:8px 12px;"
                f"border-bottom:1px solid #f3f4f8;gap:6px'>"
                f"<span style='background:{bg};color:white;border-radius:3px;"
                f"padding:1px 5px;font-size:0.68rem;font-weight:700;flex-shrink:0'>{score}</span>"
                f"<span style='font-size:0.78rem;font-weight:600;color:#1a2744;flex-shrink:0;"
                f"max-width:66px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis'>"
                f"{row.get('기업명','')}</span>"
                f"<span style='font-size:0.7rem;color:#bbb;flex-shrink:0;white-space:nowrap'>"
                f"{row.get('접수일','')}</span>"
                f"{cat_html}"
                f"<span style='font-size:0.77rem;color:#444;flex:1;min-width:0;"
                f"overflow:hidden;white-space:nowrap;text-overflow:ellipsis'>"
                f"{row.get('보고서명','')}</span>"
                f"</div>"
            )
        st.markdown(_HDR_L + _BODY_WRAP + _rows_html + "</div>", unsafe_allow_html=True)
    else:
        st.markdown(_HDR_L + _EMPTY_BODY, unsafe_allow_html=True)

with col_r:
    if earnings_result is not None:
        analysis = earnings_result.get("analysis", {})
        surprise = analysis.get("earnings_surprise", "UNKNOWN")
        reason   = analysis.get("surprise_reason", "")
        corp_nm  = earnings_result.get("corp_name", "")
        quarter  = earnings_result.get("quarter", "")
        metrics  = analysis.get("key_metrics", [])
        _BADGE = {
            "BEAT":    ("#00d084", "BEAT"),
            "MISS":    ("#ff4b4b", "MISS"),
            "IN_LINE": ("#8899bb", "IN-LINE"),
            "UNKNOWN": ("#aaa",    "?"),
        }
        bg, lbl = _BADGE.get(surprise, ("#aaa", "?"))

        _earn_html = (
            f"<div style='padding:9px 12px;border-bottom:1px solid #f3f4f8;"
            f"display:flex;align-items:center;gap:7px;flex-wrap:wrap'>"
            f"<span style='font-weight:700;font-size:0.91rem;color:#1a2744'>{corp_nm}</span>"
            f"<span style='font-size:0.77rem;color:#bbb'>{quarter}</span>"
            f"<span style='background:{bg};color:white;border-radius:3px;"
            f"padding:2px 8px;font-size:0.77rem;font-weight:700'>{lbl}</span>"
            f"</div>"
        )
        if reason:
            _earn_html += (
                f"<div style='font-size:0.77rem;color:#667;padding:7px 12px;"
                f"border-bottom:1px solid #f3f4f8;line-height:1.4'>{reason}</div>"
            )
        for m in metrics[:4]:
            delta = m.get("전분기대비", "")
            if delta and delta not in ("해당없음", ""):
                dc = "#00d084" if "+" in delta else "#ff4b4b"
                dh = f"<span style='color:{dc};font-size:0.74rem;margin-left:5px'>{delta}</span>"
            else:
                dh = ""
            _earn_html += (
                f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"padding:7px 12px;border-bottom:1px solid #f3f4f8'>"
                f"<span style='font-size:0.8rem;color:#999;flex-shrink:0'>{m.get('항목','')}</span>"
                f"<span style='font-size:0.8rem;font-weight:600;color:#1a2744;"
                f"white-space:nowrap'>{m.get('값','')}{dh}</span>"
                f"</div>"
            )
        st.markdown(_HDR_R + _BODY_WRAP + _earn_html + "</div>", unsafe_allow_html=True)
    else:
        st.markdown(_HDR_R + _EMPTY_BODY, unsafe_allow_html=True)
