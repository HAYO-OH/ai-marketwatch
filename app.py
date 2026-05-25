import streamlit as st

st.set_page_config(
    page_title="AI MarketWatch",
    page_icon="📈",
    layout="wide",
)

st.title("📈 AI MarketWatch")
st.markdown("DART 공시 모니터링 · 실적 발표 요약 · 포트폴리오 리스크 분석")

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    st.page_link("pages/1_DART공시모니터링.py", label="DART 공시 모니터링", icon="📋")
with col2:
    st.page_link("pages/2_실적발표요약.py", label="실적 발표 요약", icon="📊")
with col3:
    st.page_link("pages/3_포트폴리오리스크.py", label="포트폴리오 리스크", icon="⚠️")
