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

# ── 대시보드 메트릭 ──────────────────────────────────────
search_results = st.session_state.get("search_results")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("📅 오늘", date.today().strftime("%Y.%m.%d"))

if search_results is not None:
    company_results = search_results["company_results"]
    df_all = search_results["df_all"]
    found_cnt   = sum(1 for r in company_results if r["found"])
    disc_cnt    = sum(len(r.get("raw_rows", [])) for r in company_results if r["found"])
    alert_cnt   = st.session_state.get("last_alert_count", 0)

    with m2:
        st.metric("🏢 마지막 조회 기업", f"{found_cnt}개")
    with m3:
        alert_label = f"{alert_cnt}건" if alert_cnt else "없음"
        st.metric("🔔 키워드 알림", alert_label)
    with m4:
        st.metric("📋 수집된 공시", f"{disc_cnt}건")
else:
    with m2:
        st.metric("🏢 마지막 조회 기업", "—")
    with m3:
        st.metric("🔔 키워드 알림", "—")
    with m4:
        st.metric("📋 수집된 공시", "—")
    st.caption("아직 조회된 데이터 없음 — DART 공시 모니터링 페이지에서 검색하세요.")

st.divider()
