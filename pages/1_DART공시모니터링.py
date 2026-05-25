import json
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from services.claude_client import ClaudeClient
from services.dart_client import DartClient

st.set_page_config(page_title="DART 공시 모니터링", layout="wide")

# ── 중요도 표시 헬퍼 ──────────────────────────────────────
def score_badge(score: int) -> str:
    if score >= 9:
        return f"🔴 {score}"
    if score >= 7:
        return f"🟠 {score}"
    if score >= 4:
        return f"🟡 {score}"
    return f"🟢 {score}"

def score_label(score: int) -> str:
    if score >= 9:
        return "매우높음"
    if score >= 7:
        return "높음"
    if score >= 4:
        return "보통"
    return "낮음"

# ── 사이드바: 기준표만 ────────────────────────────────────
with st.sidebar:
    with st.expander("📌 중요도 기준표", expanded=False):
        st.markdown("🔴 **9~10점**: 최대주주 변동, 대규모 유상증자(30%↑), 횡령·배임, 상장폐지 사유, 워크아웃·법정관리, 적대적 M&A")
        st.markdown("🟠 **7~8점**: 대표이사 교체, 합병·분할·주식교환, 대규모 소송 패소, 어닝 서프라이즈(±20%↑), 자회사 대규모 매각·취득, 유상증자(10~30%), CB·BW 발행")
        st.markdown("🟡 **5~6점**: 분기·반기·사업 실적 공시, 자사주 취득(1~5%), 특별배당, 신규 사업 진출, 대규모 시설투자, 주요 계약 체결")
        st.markdown("🟢 **2~4점**: 소액 배당, 임원 변경(대표 제외), 자기주식 소각, 공시 정정(수치 오류), 감사보고서 제출")
        st.markdown("⚪ **1점**: 단순 형식 정정, 기재사항 변경, 반복적 정기 공시")
    st.divider()
    st.subheader("🗂️ 카테고리 설명")
    st.markdown("""
- **실적** — 사업·분기·반기보고서, 영업실적
- **유상증자** — 신주발행, CB·BW 발행
- **자사주** — 자기주식 취득·소각·처분
- **배당** — 현금·주식배당, 중간배당
- **지배구조** — 합병, 최대주주·임원 변경
- **소송** — 소송, 제재, 과징금
- **공시정정** — 기존 공시 내용 정정
""")

# ── 메인: 검색 폼 (중앙 배치) ────────────────────────────
st.title("📋 DART 공시 모니터링")
st.markdown("<br>", unsafe_allow_html=True)

_, center, _ = st.columns([1, 2, 1])
with center:
    corp_name = st.text_input(
        "기업명",
        placeholder="예: 삼성전자",
        label_visibility="collapsed",
    )
    st.markdown("##### 조회 기간")
    d1, d2 = st.columns(2)
    with d1:
        bgn_de = st.date_input("시작일", value=date.today() - timedelta(days=90))
    with d2:
        end_de = st.date_input("종료일", value=date.today())

    st.markdown("##### 최소 중요도")
    min_score = st.slider(
        "최소 중요도",
        min_value=1, max_value=10, value=1,
        label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)
    search_btn = st.button(
        "🔍 조회 + AI 분류",
        type="primary",
        use_container_width=True,
    )

# ── 검색 전 초기 화면 ─────────────────────────────────────
if not search_btn:
    st.stop()

if not corp_name:
    st.warning("기업명을 입력하세요.")
    st.stop()

st.divider()

dart = DartClient()
claude = ClaudeClient()

# 1) 기업 코드 조회
with st.spinner("기업 정보 조회 중..."):
    company = dart.search_company(corp_name)

if company is None:
    st.error(f"'{corp_name}'에 해당하는 기업을 찾을 수 없습니다.")
    st.stop()

corp_code = company["corp_code"]
corp_full_name = company.get("corp_name", corp_name)

# 2) 공시 목록 조회
with st.spinner("공시 목록 불러오는 중..."):
    items = dart.get_disclosures(
        corp_code,
        bgn_de.strftime("%Y%m%d"),
        end_de.strftime("%Y%m%d"),
    )

if not items:
    st.info(f"**{corp_full_name}** — 해당 기간에 공시가 없습니다.")
    st.stop()

# 3) AI 분류 + 중요도 점수화
with st.spinner(f"AI가 공시 {len(items)}건을 분류하는 중..."):
    try:
        classifications = claude.classify_disclosures(corp_full_name, items)
        classify_map = {c["index"]: c for c in classifications}
    except (json.JSONDecodeError, KeyError):
        st.warning("AI 분류 중 오류가 발생했습니다. 공시 목록만 표시합니다.")
        classify_map = {}

# 4) 데이터프레임 조합
rows = []
for i, it in enumerate(items):
    cl = classify_map.get(i, {})
    rows.append(
        {
            "접수일": it.get("rcept_dt", ""),
            "보고서명": it.get("report_nm", ""),
            "제출인": it.get("flr_nm", ""),
            "카테고리": cl.get("category", "지배구조"),
            "중요도": cl.get("score", 0),
            "중요도표시": score_badge(cl.get("score", 0)) if cl else "-",
            "중요도등급": score_label(cl.get("score", 0)) if cl else "-",
            "분류사유": cl.get("reason", ""),
            "rcept_no": it.get("rcept_no", ""),
        }
    )

df = pd.DataFrame(rows)
df_filtered = df[df["중요도"] >= min_score] if classify_map else df

# ── 요약 메트릭 ───────────────────────────────────────────
st.subheader(f"{corp_full_name} 공시 분석 결과")

m1, m2, m3, m4 = st.columns(4)
m1.metric("전체 공시", f"{len(df)}건")
if classify_map:
    avg_score = df["중요도"].mean()
    high_cnt = len(df[df["중요도"] >= 7])
    top_cat = df["카테고리"].value_counts().idxmax()
    m2.metric("평균 중요도", f"{avg_score:.1f} / 10")
    m3.metric("고중요도 (7점↑)", f"{high_cnt}건")
    m4.metric("최다 카테고리", top_cat)
else:
    m2.metric("평균 중요도", "-")
    m3.metric("고중요도 (7점↑)", "-")
    m4.metric("최다 카테고리", "-")

st.caption(f"필터 적용: 중요도 {min_score}점 이상 → {len(df_filtered)}건 표시")
st.divider()

# ── 탭 ───────────────────────────────────────────────────
tab_list, tab_chart, tab_alert = st.tabs(["📄 공시 목록", "📊 분석 차트", "🚨 주요 공시"])

with tab_list:
    if df_filtered.empty:
        st.info("해당 중요도 이상의 공시가 없습니다.")
    else:
        display_cols = ["접수일", "보고서명", "제출인", "카테고리", "중요도표시", "분류사유"]
        st.dataframe(
            df_filtered[display_cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            column_config={
                "중요도표시": st.column_config.TextColumn("중요도", width="small"),
                "분류사유": st.column_config.TextColumn("AI 분류 사유", width="large"),
            },
        )

with tab_chart:
    if not classify_map:
        st.info("AI 분류 결과가 없어 차트를 표시할 수 없습니다.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            cat_counts = df["카테고리"].value_counts().reset_index()
            cat_counts.columns = ["카테고리", "건수"]
            fig_cat = px.bar(
                cat_counts,
                x="건수", y="카테고리", orientation="h",
                title="카테고리별 공시 건수",
                color="건수", color_continuous_scale="Blues",
            )
            fig_cat.update_layout(showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_cat, use_container_width=True)

        with c2:
            fig_hist = px.histogram(
                df, x="중요도", nbins=10,
                title="중요도 분포",
                range_x=[0.5, 10.5],
                color_discrete_sequence=["#4A90D9"],
            )
            fig_hist.update_layout(bargap=0.1)
            st.plotly_chart(fig_hist, use_container_width=True)

        cat_score = df.groupby("카테고리")["중요도"].mean().reset_index()
        cat_score.columns = ["카테고리", "평균중요도"]
        cat_score = cat_score.sort_values("평균중요도", ascending=False)
        fig_avg = px.bar(
            cat_score, x="카테고리", y="평균중요도",
            title="카테고리별 평균 중요도",
            color="평균중요도", color_continuous_scale="Reds",
            range_y=[0, 10],
        )
        fig_avg.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig_avg, use_container_width=True)

def _render_disclosure_card(row):
    badge = score_badge(row["중요도"])
    with st.expander(f"{badge} [{row['접수일']}] {row['보고서명']}"):
        st.markdown(f"**카테고리:** {row['카테고리']}　|　**제출인:** {row['제출인']}")
        st.markdown(f"**점수 이유:** {row['분류사유']}")
        link_col, btn_col = st.columns([1, 1])
        with link_col:
            if row["rcept_no"]:
                dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"
                st.markdown(f"[DART 원문 보기 →]({dart_url})")
        with btn_col:
            if row["카테고리"] == "실적":
                st.page_link(
                    "pages/2_실적발표요약.py",
                    label="📊 Tab 2에서 실적 상세 분석 보기",
                )

with tab_alert:
    high_df = df[df["중요도"] >= 7].sort_values("중요도", ascending=False)
    if high_df.empty:
        st.info("이번 기간 고중요도 이벤트 없음 (7점↑ 공시 없음)")
        st.markdown("##### 점수 상위 공시 TOP 5")
        top5 = df.sort_values("중요도", ascending=False).head(5)
        for _, row in top5.iterrows():
            _render_disclosure_card(row)
    else:
        for _, row in high_df.iterrows():
            _render_disclosure_card(row)
