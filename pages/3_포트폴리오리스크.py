import pandas as pd
import plotly.express as px
import streamlit as st

from services.claude_client import ClaudeClient
from services.tavily_client import TavilyClient

st.set_page_config(page_title="포트폴리오 리스크 대시보드", layout="wide")


def parse_portfolio(raw: str) -> list[dict]:
    rows = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        parts = line.split(",")
        name = parts[0].strip()
        try:
            weight = float(parts[1].strip())
        except ValueError:
            continue
        rows.append({"종목": name, "비중": weight})
    return rows


# ── 메인: 입력 폼 (중앙 배치) ────────────────────────────
st.title("⚠️ 포트폴리오 리스크 대시보드")
st.markdown("<br>", unsafe_allow_html=True)

_, center, _ = st.columns([1, 2, 1])
with center:
    st.markdown("##### 포트폴리오 입력 (종목명,비중% 형식으로 입력)")
    default_portfolio = "삼성전자,30\nSK하이닉스,20\n현대차,15\n카카오,10\n셀트리온,25"
    raw_input = st.text_area(
        "포트폴리오",
        value=default_portfolio,
        height=180,
        label_visibility="collapsed",
        placeholder="삼성전자,30\nSK하이닉스,20\n현대차,15",
    )
    st.markdown("<br>", unsafe_allow_html=True)
    analyze_btn = st.button(
        "🔍 리스크 분석 시작",
        type="primary",
        use_container_width=True,
    )

# ── 검색 전 초기 화면 ─────────────────────────────────────
if not analyze_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    _, preview_col, _ = st.columns([1, 2, 1])
    with preview_col:
        sample = pd.DataFrame([
            {"종목": "삼성전자", "비중": 30},
            {"종목": "SK하이닉스", "비중": 20},
            {"종목": "현대차", "비중": 15},
            {"종목": "카카오", "비중": 10},
            {"종목": "셀트리온", "비중": 25},
        ])
        fig = px.pie(sample, values="비중", names="종목", title="포트폴리오 구성 예시")
        st.plotly_chart(fig, use_container_width=True)
    st.stop()

# ── 분석 실행 ─────────────────────────────────────────────
portfolio = parse_portfolio(raw_input)

if not portfolio:
    st.error("올바른 형식으로 입력하세요. (예: 삼성전자,30)")
    st.stop()

total_weight = sum(r["비중"] for r in portfolio)
if abs(total_weight - 100) > 0.1:
    st.warning(f"비중 합계가 {total_weight:.1f}%입니다. 100%로 맞추는 것을 권장합니다.")

st.divider()
df = pd.DataFrame(portfolio)

# 섹션 1: 포트폴리오 구성 시각화
st.subheader("포트폴리오 구성")
col1, col2 = st.columns(2)
with col1:
    fig_pie = px.pie(df, values="비중", names="종목", title="종목별 비중")
    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    st.plotly_chart(fig_pie, use_container_width=True)
with col2:
    fig_bar = px.bar(
        df.sort_values("비중", ascending=True),
        x="비중", y="종목", orientation="h",
        title="종목별 비중 (%)", color="비중",
        color_continuous_scale="Blues",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# 섹션 2: 종목별 리스크 시그널
st.subheader("종목별 리스크 시그널")
tavily = TavilyClient()
claude = ClaudeClient()

risk_rows = []
news_context = []

progress = st.progress(0, text="뉴스 수집 중...")
for i, row in enumerate(portfolio):
    results = tavily.search(f"{row['종목']} 주가 리스크 악재 이슈", max_results=3)
    snippets = [r.get("title", "") for r in results]
    news_context.append(f"[{row['종목']}] " + " / ".join(snippets))
    risk_rows.append({"종목": row["종목"], "비중": row["비중"], "최근 이슈": " | ".join(snippets[:2])})
    progress.progress((i + 1) / len(portfolio), text=f"{row['종목']} 완료")

progress.empty()

risk_df = pd.DataFrame(risk_rows)
st.dataframe(risk_df, use_container_width=True, hide_index=True)

# 섹션 3: AI 종합 리스크 평가
st.subheader("AI 종합 리스크 평가")
with st.spinner("AI가 포트폴리오를 분석하는 중..."):
    portfolio_desc = "\n".join(f"- {r['종목']}: {r['비중']}%" for r in portfolio)
    news_desc = "\n".join(news_context)
    analysis = claude.analyze(
        system_prompt=(
            "당신은 자산관리 전문가입니다. "
            "포트폴리오 구성과 최근 뉴스를 바탕으로 "
            "① 집중 리스크 ② 섹터 편중 ③ 종목별 주요 리스크 ④ 리밸런싱 제안 "
            "을 구체적으로 분석하세요."
        ),
        user_message=(
            f"포트폴리오:\n{portfolio_desc}\n\n"
            f"최근 뉴스 이슈:\n{news_desc}"
        ),
    )
st.markdown(analysis)
