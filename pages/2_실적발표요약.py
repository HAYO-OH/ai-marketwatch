import streamlit as st

from services.claude_client import ClaudeClient
from services.dart_client import DartClient
from services.tavily_client import TavilyClient

st.set_page_config(page_title="실적 발표 요약", layout="wide")

# ── 메인: 검색 폼 (중앙 배치) ────────────────────────────
st.title("📊 실적 발표 요약")
st.markdown("<br>", unsafe_allow_html=True)

_, center, _ = st.columns([1, 2, 1])
with center:
    corp_name = st.text_input(
        "기업명",
        placeholder="예: 현대차",
        label_visibility="collapsed",
    )
    quarter = st.selectbox(
        "분기",
        ["2025 1Q", "2025 2Q", "2025 3Q", "2024 4Q", "2024 3Q"],
    )
    include_news = st.checkbox("관련 뉴스 포함", value=True)
    st.markdown("<br>", unsafe_allow_html=True)
    analyze_btn = st.button(
        "🔍 실적 분석 시작",
        type="primary",
        use_container_width=True,
    )

# ── 검색 전 초기 화면 ─────────────────────────────────────
if not analyze_btn:
    st.stop()

if not corp_name:
    st.warning("기업명을 입력하세요.")
    st.stop()

st.divider()

dart = DartClient()
claude = ClaudeClient()
context_parts = []

# 1) DART 실적 공시 검색
with st.spinner("DART 실적 공시 검색 중..."):
    company = dart.search_company(corp_name)
    if company is not None:
        corp_code = company["corp_code"]
        corp_full_name = company.get("corp_name", corp_name)
        items = dart.get_disclosures(corp_code, "20240101", "20251231")
        earnings_items = [
            it for it in items
            if any(kw in it.get("report_nm", "") for kw in ["실적", "영업이익", "매출", "사업보고서", "분기보고서"])
        ]
        if earnings_items:
            titles = "\n".join(
                f"- {it['report_nm']} ({it['rcept_dt']})" for it in earnings_items[:10]
            )
            context_parts.append(f"[DART 실적 관련 공시]\n{titles}")
    else:
        corp_full_name = corp_name
        st.warning(f"DART에서 '{corp_name}'을 찾을 수 없어 뉴스 기반으로만 분석합니다.")

# 2) 뉴스 수집
if include_news:
    with st.spinner("실적 관련 뉴스 수집 중..."):
        tavily = TavilyClient()
        results = tavily.search(f"{corp_name} {quarter} 실적 발표 영업이익", max_results=5)
        if results:
            news_text = "\n".join(
                f"- {r['title']}: {r.get('content', '')[:200]}" for r in results
            )
            context_parts.append(f"[관련 뉴스]\n{news_text}")

if not context_parts:
    st.error("수집된 데이터가 없습니다. 기업명을 확인하세요.")
    st.stop()

# 3) AI 분석
with st.spinner("AI가 실적을 분석하는 중..."):
    context = "\n\n".join(context_parts)
    summary = claude.analyze(
        system_prompt=(
            "당신은 한국 주식시장 애널리스트입니다. "
            "제공된 실적 공시 및 뉴스를 바탕으로 "
            "① 핵심 실적 지표 요약 ② 전분기/전년 대비 변화 ③ 시장 반응 및 전망 "
            "순서로 투자자에게 유용한 분석 리포트를 작성하세요."
        ),
        user_message=f"{corp_full_name} {quarter} 실적 분석 요청:\n\n{context}",
    )

# 4) 결과 출력
st.subheader(f"{corp_full_name} {quarter} 실적 AI 분석")
st.markdown(summary)

with st.expander("수집된 원본 데이터 보기"):
    st.text(context)
