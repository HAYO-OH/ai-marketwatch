from datetime import date

import streamlit as st

from utils.nav import render_top_nav
from utils.watchlist import render_watchlist_sidebar

st.set_page_config(
    page_title="AI MarketWatch",
    page_icon="📈",
    layout="wide",
)

render_watchlist_sidebar()
render_top_nav("app.py")

st.title("📈 AI MarketWatch")
st.markdown("DART 공시 모니터링 · 실적 발표 요약 · 포트폴리오 리스크 분석")
st.divider()

# ── 데이터 ───────────────────────────────────────────────
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

# ── 메트릭 카드 ───────────────────────────────────────────
def _card(label: str, value: str, color: str = "#222222") -> str:
    return (
        "<div style='background:#f8f9fa;border:0.5px solid #e0e0e0;border-radius:8px;"
        "padding:16px 20px;'>"
        f"<div style='font-size:0.74rem;color:#888888;margin-bottom:6px;font-weight:500'>{label}</div>"
        f"<div style='font-size:1.55rem;font-weight:700;color:{color};line-height:1.2'>{value}</div>"
        "</div>"
    )

c1, c2, c3, c4 = st.columns(4)
c1.markdown(_card("📅 오늘", date.today().strftime("%Y.%m.%d")), unsafe_allow_html=True)
c2.markdown(_card("🏢 마지막 조회 기업", f"{found_cnt}개" if search_results else "—"), unsafe_allow_html=True)
c3.markdown(_card("🔔 키워드 알림",
    f"{alert_cnt}건" if alert_cnt else ("없음" if search_results else "—"),
    "#22a355" if alert_cnt > 0 else "#222222",
), unsafe_allow_html=True)
c4.markdown(_card("📋 수집된 공시",
    f"{disc_cnt}건" if search_results else "—",
    "#22a355" if disc_cnt > 0 else "#222222",
), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── 하단 2개 섹션 ─────────────────────────────────────────
col_l, col_r = st.columns(2)

# 왼쪽: 최근 공시 목록
with col_l:
    st.markdown("#### 📋 최근 공시 목록")
    if df_all is not None and not df_all.empty:
        def _score_badge(score: int) -> str:
            if score >= 9:
                bg = "#FF4B4B"
            elif score >= 7:
                bg = "#FF8C00"
            elif score >= 4:
                bg = "#FFB800"
            else:
                bg = "#22a355"
            return (
                f"<span style='background:{bg};color:white;border-radius:3px;"
                f"padding:1px 6px;font-size:0.71rem;font-weight:700'>{score}</span>"
            )
        for _, row in df_all.sort_values("중요도", ascending=False).head(5).iterrows():
            st.markdown(
                f"<div style='padding:7px 0;border-bottom:1px solid #f0f0f0'>"
                f"{_score_badge(row['중요도'])}&nbsp;"
                f"<span style='font-size:0.83rem;font-weight:600'>{row.get('기업명','')}</span>"
                f"&nbsp;<span style='font-size:0.77rem;color:#aaa'>{row.get('접수일','')}</span><br>"
                f"<span style='font-size:0.79rem;color:#555;margin-left:2px'>{row.get('보고서명','')}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("아직 조회된 데이터 없음")

# 오른쪽: 실적 서프라이즈 요약
with col_r:
    st.markdown("#### 📊 실적 서프라이즈 요약")
    if earnings_result is not None:
        analysis = earnings_result.get("analysis", {})
        surprise = analysis.get("earnings_surprise", "UNKNOWN")
        reason   = analysis.get("surprise_reason", "")
        corp_nm  = earnings_result.get("corp_name", "")
        quarter  = earnings_result.get("quarter", "")
        metrics  = analysis.get("key_metrics", [])

        _BADGE_STYLE = {
            "BEAT":    ("#22a355", "BEAT"),
            "MISS":    ("#FF4B4B", "MISS"),
            "IN_LINE": ("#888888", "IN-LINE"),
            "UNKNOWN": ("#bbbbbb", "UNKNOWN"),
        }
        bg, lbl = _BADGE_STYLE.get(surprise, ("#bbbbbb", surprise))
        st.markdown(
            f"<div style='margin-bottom:8px'>"
            f"<span style='font-weight:700;font-size:0.95rem'>{corp_nm}</span>"
            f"&nbsp;<span style='font-size:0.82rem;color:#888'>{quarter}</span>&nbsp;"
            f"<span style='background:{bg};color:white;border-radius:4px;"
            f"padding:2px 9px;font-size:0.82rem;font-weight:700'>{lbl}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if reason:
            st.caption(reason)
        for m in metrics[:4]:
            delta = m.get("전분기대비", "")
            if delta and delta not in ("해당없음", ""):
                dc = "#22a355" if "+" in delta else "#FF4B4B" if "-" in delta else "#888"
                delta_html = f"<span style='color:{dc};font-size:0.78rem'>&nbsp;{delta}</span>"
            else:
                delta_html = ""
            st.markdown(
                f"<div style='padding:5px 0;border-bottom:1px solid #f0f0f0;font-size:0.83rem'>"
                f"<span style='color:#888'>{m.get('항목','')}</span>&nbsp;"
                f"<span style='font-weight:600'>{m.get('값','')}</span>{delta_html}"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("아직 조회된 데이터 없음")
