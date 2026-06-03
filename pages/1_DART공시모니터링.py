import json
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.claude_client import ClaudeClient
from services.dart_client import DartClient
from services.tavily_client import TavilyClient
from utils.logos import get_logo_html
from utils.nav import render_top_nav
from utils.watchlist import render_watchlist_sidebar

st.set_page_config(page_title="DART 공시 모니터링", layout="wide")

@st.cache_resource
def _get_clients():
    return DartClient(), ClaudeClient()

# ── 헬퍼 ─────────────────────────────────────────────────
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

def _display_summary(summary: dict):
    if "error" in summary:
        st.caption(f"⚠️ {summary['error']}")
    else:
        st.markdown(f"- **핵심 내용:** {summary.get('핵심내용', '')}")
        st.markdown(f"- **투자자 관점:** {summary.get('투자자관점', '')}")
        st.markdown(f"- **리스크/기회:** {summary.get('리스크기회', '')}")


def _render_disclosure_card(row, show_corp: bool = False, with_summary: bool = False, _tab_ctx: str = ""):
    badge = score_badge(row["중요도"])
    corp_prefix = f"[{row.get('기업명', '')}]  " if show_corp and row.get("기업명") else ""
    rcept_no = row.get("rcept_no", "")
    sum_key = f"summary_{rcept_no}" if rcept_no else None
    exp_key = f"exp_{rcept_no}" if rcept_no else None
    is_expanded = bool(st.session_state.get(exp_key)) if exp_key else False

    with st.expander(f"{badge}  {corp_prefix}[{row['접수일']}] {row['보고서명']}", expanded=is_expanded):
        meta = f"**카테고리:** {row['카테고리']}"
        if show_corp and row.get("기업명"):
            meta = f"**기업:** {row['기업명']}　|　" + meta
        st.markdown(meta)
        st.markdown(f"**점수 이유:** {row['분류사유']}")
        link_col, btn_col, chart_col = st.columns([2, 2, 2])
        with link_col:
            if rcept_no:
                dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                st.markdown(f"[DART 원문 보기 →]({dart_url})")
        with btn_col:
            if row["카테고리"] == "실적":
                st.page_link("pages/2_실적발표요약.py", label="📊 실적 상세 분석 보기")
        with chart_col:
            corp = row.get("기업명", "")
            if corp:
                _ckey = (
                    f"btn_chart_{_tab_ctx}_{rcept_no}"
                    if rcept_no
                    else f"btn_chart_{_tab_ctx}_{abs(hash(corp + str(row.get('접수일', ''))))}"
                )
                if st.button("📈 주가 반응 보기", key=_ckey):
                    st.session_state["selected_stock"] = corp
                    st.session_state["selected_date"] = row.get("접수일", "")
                    st.switch_page("pages/2_실적발표요약.py")

        if with_summary and rcept_no and sum_key:
            st.divider()
            st.markdown("**📝 공시 원문 요약**")
            if sum_key in st.session_state:
                _display_summary(st.session_state[sum_key])
            else:
                if st.button("원문 요약 불러오기", key=f"btn_sum_{rcept_no}", use_container_width=False):
                    if exp_key:
                        st.session_state[exp_key] = True
                    with st.spinner("DART 원문 분석 중..."):
                        dart_c, claude_c = _get_clients()
                        try:
                            text = dart_c.get_document_text(rcept_no)
                            if text:
                                summary = claude_c.summarize_disclosure(
                                    row.get("기업명", ""), row.get("보고서명", ""), text
                                )
                            else:
                                summary = {"error": "원문을 가져올 수 없습니다."}
                        except Exception as e:
                            summary = {"error": str(e)[:100]}
                    st.session_state[sum_key] = summary
                    _display_summary(summary)

def _detect_anomalies(rows: list[dict]) -> list[dict]:
    """공시 이상 패턴 감지. 반환: [{"type", "label", "detail"}, ...]"""
    from collections import defaultdict
    anomalies: list[dict] = []
    if not rows:
        return anomalies

    dated: list[tuple] = []
    for r in rows:
        s = r.get("접수일", "")
        try:
            d = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            dated.append((d, r))
        except (ValueError, TypeError, IndexError):
            pass
    if not dated:
        return anomalies
    dated.sort(key=lambda x: x[0])
    dates = [d for d, _ in dated]

    # 공시 급증: 3일 이내 3건 이상
    for i in range(len(dates)):
        window = [dates[j] for j in range(i, len(dates)) if (dates[j] - dates[i]).days <= 2]
        if len(window) >= 3:
            anomalies.append({
                "type": "급증",
                "label": "⚠️ 공시 급증",
                "detail": f"{dates[i].strftime('%m.%d')}~{max(window).strftime('%m.%d')} 3일 내 {len(window)}건",
            })
            break

    # 반복 정정: 정정공시 연속 2회 이상
    streak = max_streak = 0
    for _, r in dated:
        streak = streak + 1 if "정정" in r.get("보고서명", "") else 0
        max_streak = max(max_streak, streak)
    if max_streak >= 2:
        anomalies.append({
            "type": "정정",
            "label": "🔄 반복 정정",
            "detail": f"정정공시 {max_streak}회 연속 감지",
        })

    # 중요 공시: 주요사항보고서 + 동일일 다른 공시 동시
    date_groups: dict = defaultdict(list)
    for d, r in dated:
        date_groups[d].append(r)
    for d, group in date_groups.items():
        if any("주요사항보고서" in r.get("보고서명", "") for r in group) and len(group) >= 2:
            anomalies.append({
                "type": "중요",
                "label": "🚨 중요 공시",
                "detail": f"{d.strftime('%m.%d')} 주요사항보고서 포함 {len(group)}건 동시 공시",
            })
            break

    return anomalies


_CAT_BADGE: dict[str, str] = {
    "실적":    "background:#d4edda;color:#155724",
    "자사주":  "background:#cce5ff;color:#004085",
    "지배구조": "background:#fff3cd;color:#856404",
    "유상증자": "background:#f8d7da;color:#721c24",
    "배당":    "background:#d1ecf1;color:#0c5460",
    "소송":    "background:#f5c6cb;color:#721c24",
    "공시정정": "background:#e2e3e5;color:#383d41",
}


def _importance_bar_html(score: int) -> str:
    """1~10점 → 5단계 바 HTML. 5단계=빨강, 4단계=주황, 1~3단계=회색."""
    level = max(1, min(5, (score + 1) // 2))
    color = "#FF4B4B" if level == 5 else "#FF8C00" if level == 4 else "#bbbbbb"
    segs = []
    for i in range(1, 6):
        bg = color if i <= level else "#e9ecef"
        segs.append(
            f"<span style='display:inline-block;width:11px;height:13px;"
            f"background:{bg};border-radius:2px;margin-right:2px'></span>"
        )
    return (
        "<div style='display:inline-flex;align-items:center'>"
        + "".join(segs)
        + f"<span style='font-size:0.75rem;color:#888;margin-left:4px'>{score}/10</span>"
        + "</div>"
    )


def _list_card_html(row: dict) -> str:
    """공시 목록 탭 전용 카드 HTML (단일행 — 블록 배치용)."""
    cat      = row.get("카테고리", "기타")
    badge    = _CAT_BADGE.get(cat, "background:#e9ecef;color:#444")
    rcept_no = row.get("rcept_no", "")
    score    = row.get("중요도", 1)
    sc_color = "#FF4B4B" if score >= 9 else ("#FF8C00" if score >= 7 else "#bbb")
    dart_icon = ""
    if rcept_no:
        durl = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
        dart_icon = (
            f"<a href='{durl}' target='_blank' "
            f"style='font-size:0.72rem;color:#ccc;text-decoration:none;"
            f"flex-shrink:0;line-height:1'>↗</a>"
        )
    return (
        "<div style='display:flex;align-items:center;gap:6px;"
        "padding:5px 10px;border-bottom:1px solid #f0f2f5;"
        "background:white;line-height:1.3'>"
        f"<span style='font-size:0.67rem;color:#bbb;min-width:58px;flex-shrink:0;white-space:nowrap'>{row.get('접수일','')}</span>"
        f"<span style='font-size:0.66rem;padding:1px 5px;border-radius:4px;font-weight:600;flex-shrink:0;white-space:nowrap;{badge}'>{cat}</span>"
        f"<span style='font-size:0.7rem;color:{sc_color};font-weight:700;min-width:14px;text-align:right;flex-shrink:0'>{score}</span>"
        f"<span style='font-size:0.8rem;font-weight:600;color:#1a2744;flex:1;"
        f"overflow:hidden;white-space:nowrap;text-overflow:ellipsis'>{row.get('보고서명','')}</span>"
        f"<span style='font-size:0.72rem;color:#ccc;flex-shrink:0;line-height:1'>📈</span>"
        f"{dart_icon}"
        + "</div>"
    )


# ── 관심 종목 사이드바 ────────────────────────────────────
render_watchlist_sidebar()
render_top_nav("pages/1_DART공시모니터링.py")

# ── 사이드바 ──────────────────────────────────────────────
with st.sidebar:
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
    st.divider()
    st.subheader("🔔 키워드 알림 설정")
    st.caption("보고서명에 포함된 키워드를 감지해 페이지 상단에 알림 배너를 표시합니다.")
    keywords_raw = st.text_area(
        "키워드 (줄바꿈 또는 쉼표로 구분)",
        value="유상증자\n최대주주 변동\n횡령\n배임\n관리종목",
        height=130,
        label_visibility="collapsed",
    )

# 사이드바 밖에서 키워드 리스트 파싱 (항상 실행)
alert_keywords = [
    k.strip()
    for k in keywords_raw.replace(",", "\n").split("\n")
    if k.strip()
]

# ── session state 초기화 ─────────────────────────────────
if "corp_keys" not in st.session_state:
    st.session_state.corp_keys = [0]
    st.session_state.corp_counter = 1
if "search_results" not in st.session_state:
    st.session_state.search_results = None
if "selected_quarter" not in st.session_state:
    st.session_state.selected_quarter = "2026 1Q"

# ── 분기 정의 ─────────────────────────────────────────────
_QUARTERS = {
    "2026 1Q": (date(2026, 1, 1),  date(2026, 3, 31)),
    "2025 4Q": (date(2025, 10, 1), date(2025, 12, 31)),
    "2025 3Q": (date(2025, 7, 1),  date(2025, 9, 30)),
    "2025 2Q": (date(2025, 4, 1),  date(2025, 6, 30)),
    "2025 1Q": (date(2025, 1, 1),  date(2025, 3, 31)),
}

# ── 전역 스타일 ──────────────────────────────────────────
st.markdown(
    "<style>"
    "[data-testid='stAppViewContainer']{background:#f5f6fa}"
    "[data-testid='stHeader']{background:#f5f6fa}"
    "section[data-testid='stSidebar']{background:#fff}"
    "div[data-testid='stButton'] button[kind='primary']"
    "{background-color:#1a2744!important;border-color:#1a2744!important;color:#fff!important}"
    "div[data-testid='stButton'] button[kind='primary']:hover"
    "{background-color:#243560!important;border-color:#243560!important}"
    "</style>",
    unsafe_allow_html=True,
)

# ── 메인: 헤더 배너 ──────────────────────────────────────
st.markdown(
    f"<div style='background:#1a2744;padding:9px 18px;border-radius:6px;"
    f"margin-bottom:12px;display:flex;align-items:center;justify-content:space-between'>"
    f"<div><span style='color:#fff;font-size:1.15rem;font-weight:700;letter-spacing:-0.3px'>"
    f"DART 공시 모니터링</span>"
    f"<span style='color:#7a8fbb;font-size:0.78rem;margin-left:12px'>"
    f"AI 분류 · 중요도 점수화 · 감성 분석</span></div>"
    f"<span style='color:#7a8fbb;font-size:0.78rem'>{date.today().strftime('%Y.%m.%d')}</span>"
    f"</div>",
    unsafe_allow_html=True,
)

# ── 메인: 컴팩트 검색 바 (Bloomberg 스타일) ──────────────
_b1, _b2, _b3, _b4 = st.columns([5, 2, 2, 1])
with _b1:
    st.text_input(
        "종목",
        key="corp_input_single",
        placeholder="기업명 (쉼표 구분: 삼성전자, SK하이닉스)",
        label_visibility="collapsed",
    )
with _b2:
    _q_list = list(_QUARTERS.keys())
    _q_cur  = st.session_state.get("selected_quarter", _q_list[0])
    _q_idx  = _q_list.index(_q_cur) if _q_cur in _q_list else 0
    _sel_q  = st.selectbox(
        "분기",
        options=_q_list,
        index=_q_idx,
        label_visibility="collapsed",
        key="qselect",
    )
    st.session_state["selected_quarter"] = _sel_q
with _b3:
    min_score = st.slider(
        "최소 중요도",
        min_value=1, max_value=10, value=1,
        label_visibility="collapsed",
    )
with _b4:
    search_btn = st.button(
        "🔍 조회",
        type="primary",
        use_container_width=True,
    )

# 보조 행: 날짜 범위 + 관심종목 불러오기
sel_start, sel_end = _QUARTERS[_sel_q]
bgn_de, end_de = sel_start, sel_end
_wl = st.session_state.get("watchlist", [])
_wa, _wb = st.columns([7, 2])
with _wa:
    st.caption(
        f"📅 {bgn_de.strftime('%Y.%m.%d')} ~ {end_de.strftime('%Y.%m.%d')}"
        f"  ·  최소 중요도 {min_score}점 이상"
    )
with _wb:
    if _wl and st.button("⭐ 관심종목 불러오기", use_container_width=True, key="wl_load_corp"):
        st.session_state["corp_input_single"] = ", ".join(_wl)
        st.rerun()

# st.tabs 위치를 항상 고정하기 위해 with center: 블록 밖에 배치
progress_slot = st.empty()

if search_btn:
    _raw_input = st.session_state.get("corp_input_single", "")
    corp_names = [n.strip() for n in _raw_input.replace("，", ",").split(",") if n.strip()]
    if not corp_names:
        st.warning("기업명을 입력하세요.")
        st.stop()
    st.session_state["recent_corp_names"] = corp_names

    dart = DartClient()
    claude = ClaudeClient()

    bgn_str = bgn_de.strftime("%Y%m%d")
    end_str = end_de.strftime("%Y%m%d")

    # ── Phase 1: DART 공시 조회 + AI 분류 ────────────────
    company_results = []
    n = len(corp_names)
    progress_slot.progress(0, text="시작 중...")
    for i, name in enumerate(corp_names):
        # 1단계: 공시 수집
        progress_slot.progress(
            (2 * i) / (2 * n) * 0.5,
            text=f"[{i+1}/{n}] {name} — 1단계: 공시 수집 중...",
        )

        company = dart.search_company(name)
        if company is None:
            company_results.append({
                "corp_name": name, "found": False,
                "top_score": -1, "top3": [], "all_rows": [], "sentiment": [],
            })
            continue

        corp_code = company["corp_code"]
        corp_full_name = company["corp_name"]
        items = dart.get_disclosures(corp_code, bgn_str, end_str)

        if not items:
            company_results.append({
                "corp_name": corp_full_name, "found": True,
                "top_score": 0, "top3": [], "all_rows": [], "sentiment": [],
            })
            continue

        # 2단계: AI 분류
        progress_slot.progress(
            (2 * i + 1) / (2 * n) * 0.5,
            text=f"[{i+1}/{n}] {name} — 2단계: AI 분류 중... ({len(items)}건)",
        )
        try:
            classifications = claude.classify_disclosures(corp_full_name, items)
            classify_map = {c["index"]: c for c in classifications}
        except (json.JSONDecodeError, KeyError):
            classify_map = {}

        rows = []
        for j, it in enumerate(items):
            cl = classify_map.get(j, {})
            score = cl.get("score", 0)
            rows.append({
                "기업명": corp_full_name,
                "접수일": it.get("rcept_dt", ""),
                "보고서명": it.get("report_nm", ""),
                "카테고리": cl.get("category", "지배구조"),
                "중요도": score,
                "분류사유": cl.get("reason", ""),
                "rcept_no": it.get("rcept_no", ""),
            })

        rows.sort(key=lambda x: x["중요도"], reverse=True)
        filtered = [r for r in rows if r["중요도"] >= min_score]
        top_score = filtered[0]["중요도"] if filtered else 0

        company_results.append({
            "corp_name": corp_full_name,
            "found": True,
            "top_score": top_score,
            "top3": filtered[:3],
            "all_rows": filtered,
            "raw_rows": rows,   # min_score 필터 전 전체 공시 (키워드 알림용)
            "sentiment": [],
        })

    # ── Phase 2: 뉴스 수집 + 감성 분석 ──────────────────
    tavily = TavilyClient()
    found_results = [r for r in company_results if r["found"]]
    n_found = max(len(found_results), 1)
    for i, result in enumerate(found_results):
        corp = result["corp_name"]

        # 3단계: 뉴스 수집
        p_fetch = 0.5 + (2 * i) / (2 * n_found) * 0.5
        progress_slot.progress(
            p_fetch,
            text=f"[{i+1}/{n_found}] {corp} — 3단계: 뉴스 수집 중...",
        )
        try:
            news_articles = tavily.get_news(corp, days=30, max_results=10)
        except Exception:
            news_articles = []

        # 4단계: 감성 분석
        p_analyze = 0.5 + (2 * i + 1) / (2 * n_found) * 0.5
        if news_articles:
            progress_slot.progress(
                p_analyze,
                text=f"[{i+1}/{n_found}] {corp} — 4단계: 감성 분석 중... ({len(news_articles)}건)",
            )
            try:
                result["sentiment"] = claude.analyze_sentiment(corp, news_articles)
            except Exception:
                result["sentiment"] = []
        else:
            progress_slot.progress(p_analyze, text=f"[{i+1}/{n_found}] {corp} — 뉴스 없음")
            result["sentiment"] = []

    progress_slot.progress(1.0, text="✅ 완료!")
    progress_slot.empty()

    company_results.sort(key=lambda x: x["top_score"], reverse=True)

    all_disc_rows = []
    for r in company_results:
        if r["found"]:
            all_disc_rows.extend(r["all_rows"])

    _EMPTY_COLS = ["기업명", "접수일", "보고서명", "카테고리", "중요도", "분류사유", "rcept_no"]
    df_all = pd.DataFrame(all_disc_rows) if all_disc_rows else pd.DataFrame(columns=_EMPTY_COLS)

    st.session_state.search_results = {
        "company_results": company_results,
        "df_all": df_all,
        "min_score": min_score,
        "corp_names": corp_names,
    }

if st.session_state.search_results is None:
    _recent = st.session_state.get("recent_corp_names", [])
    if _recent:
        st.markdown(
            "<div style='padding:14px 4px;font-size:0.82rem;color:#888'>"
            "최근 조회:&nbsp;&nbsp;"
            + "&nbsp;&nbsp;·&nbsp;&nbsp;".join(
                f"<b style='color:#1a2744'>{c}</b>" for c in _recent
            )
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='text-align:center;padding:48px 20px;color:#ccc;font-size:0.88rem'>"
            "기업명을 입력하고 🔍 조회 버튼을 누르면 공시 목록이 여기에 표시됩니다.</div>",
            unsafe_allow_html=True,
        )
    st.stop()

_r = st.session_state.search_results
company_results = _r["company_results"]
df_all = _r["df_all"]
min_score = _r["min_score"]
corp_names = _r["corp_names"]

st.divider()

# 요약
found_cnt = sum(1 for r in company_results if r["found"])
st.caption(
    f"총 {len(corp_names)}개 종목 조회 | "
    f"공시 발견 {found_cnt}개 종목 | "
    f"중요도 {min_score}점 이상 전체 {len(df_all)}건"
)

# ── 키워드 알림 배너 ──────────────────────────────────────
def _kw_match(kw: str, report_nm: str) -> bool:
    """키워드를 단어로 분리해 각 단어가 보고서명에 모두 포함되면 True."""
    return all(w in report_nm for w in kw.split())

if alert_keywords and company_results:
    alerts = []
    for result in company_results:
        if not result["found"]:
            continue
        # raw_rows: min_score 필터 전 전체 공시 스캔
        scan_rows = result.get("raw_rows") or result.get("all_rows", [])
        for row in scan_rows:
            report_nm = row.get("보고서명", "")
            corp_nm = row.get("기업명", "")
            date = row.get("접수일", "")
            for kw in alert_keywords:
                if _kw_match(kw, report_nm):
                    alerts.append((corp_nm, date, report_nm, kw))
                    break  # 공시당 첫 번째 매칭 키워드만

    if alerts:
        # (기업, 키워드) 기준으로 그룹화
        groups: dict[tuple, list] = {}
        for corp, date, report_nm, kw in alerts:
            groups.setdefault((corp, kw), []).append((date, report_nm))

        st.session_state.last_alert_count = len(groups)

        bullets = []
        for (corp, kw), items in groups.items():
            first_date, first_report = items[0]
            extra = len(items) - 1
            suffix = f" 외 {extra}건" if extra > 0 else ""
            bullets.append(
                f"- **{corp}** — [{first_date}] {first_report}{suffix}에서 **'{kw}'** 감지"
            )
        st.error(f"⚠️ **키워드 알림**\n" + "\n".join(bullets))
    else:
        st.session_state.last_alert_count = 0

# ── 이상 탐지 (탭 공용) ──────────────────────────────────
_corp_anomalies: dict[str, list[dict]] = {}
for _res in company_results:
    if _res["found"]:
        _scan = _res.get("raw_rows") or _res.get("all_rows", [])
        _anom = _detect_anomalies(_scan)
        if _anom:
            _corp_anomalies[_res["corp_name"]] = _anom

# ── Bloomberg 요약 헤더 ───────────────────────────────────
if not df_all.empty:
    _hi   = int((df_all["중요도"] >= 7).sum())
    _corps = " · ".join(r["corp_name"] for r in company_results if r["found"])[:70]
    st.markdown(
        f"<div style='background:#1a2744;padding:7px 15px;border-radius:6px;"
        f"margin-bottom:8px;display:flex;align-items:center;justify-content:space-between'>"
        f"<span style='color:#fff;font-size:0.88rem;font-weight:600'>{_corps}</span>"
        f"<span style='color:#7a8fbb;font-size:0.77rem'>"
        f"공시 {len(df_all)}건 &nbsp;·&nbsp; 핵심 {_hi}건</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

# ── 탭 (3개) ─────────────────────────────────────────────
tab_list, tab_chart, tab_alert = st.tabs([
    "📋 공시목록", "📊 분석차트", "🔔 알림설정"
])

# ── Tab 1: 공시 목록 ──────────────────────────────────────
with tab_list:
    st.markdown(
        "<style>"
        "div[data-testid='stRadio']>div{gap:4px;flex-wrap:wrap}"
        "div[data-testid='stRadio'] label{border:1px solid #e0e0e0;border-radius:16px;"
        "padding:3px 13px;font-size:0.82rem;cursor:pointer}"
        "div[data-testid='stRadio'] label:has(input:checked){background:#FF4B4B;"
        "color:white;border-color:#FF4B4B}"
        "</style>",
        unsafe_allow_html=True,
    )

    # ── 이상 감지 배너
    if _corp_anomalies:
        _banner = (
            "<div style='background:#fff8e1;border:1px solid #ffc107;border-radius:8px;"
            "padding:12px 16px;margin-bottom:8px'>"
            "<div style='font-weight:700;font-size:0.88rem;margin-bottom:6px'>🔍 공시 이상 감지</div>"
        )
        for _corp, _anom_list in _corp_anomalies.items():
            _aid = f"anom_{_corp}"
            for _a in _anom_list:
                _banner += (
                    f"<div style='font-size:0.83rem;padding:2px 0'>"
                    f"<a href='#{_aid}' style='color:#856404;text-decoration:none'>{_a['label']}</a>"
                    f"&nbsp;<strong>{_corp}</strong>&nbsp;—&nbsp;{_a['detail']}</div>"
                )
        _banner += "</div>"
        st.markdown(_banner, unsafe_allow_html=True)

    # ── 필터 바 + 요약 (한 줄)
    _fb_l, _fb_r = st.columns([2, 5])
    with _fb_l:
        if not df_all.empty:
            _high_cnt = int((df_all["중요도"] >= 7).sum())
            st.markdown(
                f"<div style='padding:7px 0;font-size:0.78rem;color:#555'>"
                f"⚡ 핵심 <b style='color:#1a2744'>{_high_cnt}</b>건 표시 중"
                f"<span style='color:#aaa;font-size:0.73rem;margin-left:5px'>(전체 {len(df_all)}건)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    with _fb_r:
        _FILTER_CATS = ["전체", "실적", "자사주", "지배구조", "정정"]
        _cat_filter = st.radio(
            "카테고리 필터",
            options=_FILTER_CATS,
            horizontal=True,
            label_visibility="collapsed",
            key="list_cat_filter",
        )

    # ── 기업별 카드
    for result in company_results:
        corp_name = result["corp_name"]
        _anom     = _corp_anomalies.get(corp_name, [])
        st.markdown(f"<div id='anom_{corp_name}'></div>", unsafe_allow_html=True)
        if not result["found"]:
            st.warning(f"❓ **{corp_name}** — DART에서 찾을 수 없습니다.")
            continue
        if not result["all_rows"]:
            st.info(f"**{corp_name}** — 해당 기간 중요도 {min_score}점 이상 공시 없음")
            continue

        # 카테고리 필터 적용
        _rows = result["all_rows"]
        if _cat_filter != "전체":
            if _cat_filter == "정정":
                _rows = [r for r in _rows if r.get("카테고리") == "공시정정"
                         or "정정" in r.get("보고서명", "")]
            else:
                _rows = [r for r in _rows if r.get("카테고리") == _cat_filter]
        if not _rows:
            continue

        # 핵심/전체 분류
        _high_rows = [r for r in _rows if r.get("중요도", 0) >= 7]
        _low_rows  = [r for r in _rows if r.get("중요도", 0) < 7]
        _show_key  = f"list_show_all_{corp_name}"

        # 기업 헤더
        _hdr_l, _hdr_r = st.columns([3, 1])
        with _hdr_l:
            _badge_html = "".join(
                f"<span style='font-size:0.72rem;background:#fff3cd;color:#856404;"
                f"border-radius:3px;padding:2px 7px;font-weight:600;margin-left:6px'>"
                f"{a['label']}</span>"
                for a in _anom
            )
            st.markdown(
                f"<div style='display:flex;align-items:center;margin-bottom:2px;margin-top:6px'>"
                f"{get_logo_html(corp_name, 28)}"
                f"<span style='font-size:1.25rem;font-weight:700;color:#1a2744'>{corp_name}</span>"
                f"{_badge_html}</div>"
                f"<div style='font-size:0.81rem;color:#555;margin-bottom:4px'>"
                f"⚡ 핵심 공시 <strong>{len(_high_rows)}건</strong> / 전체 {len(_rows)}건</div>",
                unsafe_allow_html=True,
            )
        with _hdr_r:
            _show_all = st.toggle("전체 보기", key=_show_key)

        # 표시할 행 결정
        _display = _rows if _show_all else (_high_rows if _high_rows else _rows[:5])

        _cards_html = "".join(_list_card_html(row) for row in _display)
        st.markdown(
            f"<div style='border:1px solid #e2e5ea;border-left:3px solid #1a2744;"
            f"border-radius:4px;overflow:hidden;margin-bottom:8px'>"
            f"{_cards_html}</div>",
            unsafe_allow_html=True,
        )

# ── Tab 2: 분석차트 (차트 + 뉴스 감성 통합) ──────────────
_CAT_COLOR: dict[str, str] = {
    "실적":     "#22a355",
    "자사주":   "#2563eb",
    "유상증자": "#8b5cf6",
    "배당":     "#f59e0b",
    "지배구조": "#f0a500",
    "소송":     "#ef4444",
    "공시정정": "#dc2626",
    "인사":     "#6366f1",
    "투자":     "#0891b2",
    "기타":     "#6b7280",
}
_FONT = "Pretendard, -apple-system, BlinkMacSystemFont, sans-serif"

with tab_chart:
    # 중요도 기준표 (사이드바에서 이동)
    with st.expander("📌 중요도 기준표", expanded=False):
        st.markdown(
            "| 점수 | 등급 | 대표 공시 유형 |\n"
            "|:---:|:---:|---|\n"
            "| 🔴 **9~10** | 최고 | 최대주주 변동, 유상증자 30%↑, 횡령·배임, 상장폐지 사유, 워크아웃·법정관리 |\n"
            "| 🟠 **7~8** | 높음 | 대표이사 교체, 합병·분할·주식교환, 대규모 소송 패소, 어닝 서프라이즈 ±20%↑, 유상증자 10~30% |\n"
            "| 🟡 **5~6** | 보통 | 분기·반기·사업 실적 공시, 자사주 취득 1~5%, 특별배당, 신규 사업 진출, 대규모 계약 |\n"
            "| 🟢 **2~4** | 낮음 | 소액 배당, 임원 변경(대표 제외), 자기주식 소각, 감사보고서 제출 |\n"
            "| ⚪ **1** | 최저 | 단순 형식 정정, 기재사항 변경, 반복적 정기 공시 |"
        )

    if df_all.empty:
        st.info("차트를 표시할 공시 데이터가 없습니다.")
    else:
        available_corps = sorted(df_all["기업명"].unique().tolist())
        selected_corp = st.selectbox(
            "기업 선택",
            options=["전체"] + available_corps,
            key="chart_corp_select",
        )
        if selected_corp == "전체":
            df_chart = df_all
            label = "전체 기업"
        else:
            df_chart = df_all[df_all["기업명"] == selected_corp]
            label = selected_corp

        c1, c2 = st.columns(2)

        # ── 카테고리별 공시 건수 ─────────────────────────────
        with c1:
            cat_counts = df_chart["카테고리"].value_counts().reset_index()
            cat_counts.columns = ["카테고리", "건수"]
            bar_colors = [
                _CAT_COLOR.get(c, "#6b7280") for c in cat_counts["카테고리"]
            ]
            fig_cat = go.Figure(go.Bar(
                x=cat_counts["건수"],
                y=cat_counts["카테고리"],
                orientation="h",
                marker_color=bar_colors,
                text=cat_counts["건수"],
                textposition="outside",
                textfont=dict(size=12, family=_FONT),
            ))
            fig_cat.update_layout(
                title=dict(text=f"카테고리별 공시 건수 — {label}", font=dict(size=14, family=_FONT)),
                xaxis=dict(title="건수", tickfont=dict(family=_FONT)),
                yaxis=dict(title="", tickfont=dict(family=_FONT, size=12)),
                font=dict(family=_FONT),
                showlegend=False,
                margin=dict(l=10, r=50, t=45, b=10),
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            st.plotly_chart(fig_cat, use_container_width=True)

        # ── 중요도 분포 ──────────────────────────────────────
        with c2:
            x_vals = list(range(1, 11))
            score_cnt = df_chart["중요도"].value_counts()
            y_vals = [int(score_cnt.get(s, 0)) for s in x_vals]
            # 높은 점수일수록 진한 네이비
            dist_colors = [
                f"rgba(26,39,68,{0.12 + i * 0.088:.2f})" for i in range(10)
            ]
            fig_dist = go.Figure(go.Bar(
                x=x_vals,
                y=y_vals,
                text=y_vals,
                textposition="outside",
                textfont=dict(size=12, family=_FONT),
                marker_color=dist_colors,
                marker_line=dict(width=0),
            ))
            fig_dist.update_layout(
                title=dict(text=f"중요도 분포 — {label}", font=dict(size=14, family=_FONT)),
                xaxis=dict(
                    title="중요도 (1~10)",
                    tickmode="array",
                    tickvals=x_vals,
                    ticktext=[str(v) for v in x_vals],
                    tickfont=dict(family=_FONT),
                ),
                yaxis=dict(title="건수", tickfont=dict(family=_FONT), rangemode="tozero"),
                font=dict(family=_FONT),
                bargap=0.25,
                margin=dict(l=10, r=20, t=45, b=10),
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            st.plotly_chart(fig_dist, use_container_width=True)

        # ── 카테고리별 평균 중요도 ──────────────────────────
        cat_score = df_chart.groupby("카테고리")["중요도"].mean().reset_index()
        cat_score.columns = ["카테고리", "평균중요도"]
        cat_score = cat_score.sort_values("평균중요도", ascending=False)
        avg_colors = [_CAT_COLOR.get(c, "#6b7280") for c in cat_score["카테고리"]]
        fig_avg = go.Figure(go.Bar(
            x=cat_score["카테고리"],
            y=cat_score["평균중요도"],
            marker_color=avg_colors,
            text=[f"{v:.1f}" for v in cat_score["평균중요도"]],
            textposition="outside",
            textfont=dict(size=12, family=_FONT),
        ))
        fig_avg.update_layout(
            title=dict(text=f"카테고리별 평균 중요도 — {label}", font=dict(size=14, family=_FONT)),
            xaxis=dict(title="카테고리", tickfont=dict(family=_FONT, size=12)),
            yaxis=dict(title="평균 중요도", range=[0, 11], tickfont=dict(family=_FONT)),
            font=dict(family=_FONT),
            showlegend=False,
            margin=dict(l=10, r=20, t=45, b=10),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        st.plotly_chart(fig_avg, use_container_width=True)

    # ── 뉴스 감성 (분석차트 탭 하단 통합) ─────────────────
    st.divider()
    st.markdown("**📰 뉴스 감성 점수 트렌드**")
    with st.expander("❓ 감성 점수란?", expanded=False):
        st.markdown("AI가 뉴스 기사를 읽고 투자자 관점에서 긍정/부정 정도를 **-5~+5**로 수치화한 지표입니다. +5에 가까울수록 긍정적 뉴스, -5에 가까울수록 부정적 뉴스가 많다는 의미입니다.")
        st.markdown("""
| 점수 | 의미 |
|------|------|
| +4 ~ +5 | 🟢 매우 긍정 |
| +2 ~ +3 | 🔵 긍정 |
| 0 | ⚪ 중립 |
| -2 ~ -3 | 🟠 부정 |
| -4 ~ -5 | 🔴 매우 부정 |
""")
        st.markdown("**예시** +4 → 삼성전자 역대 최대 실적 달성 / -3 → 반도체 수요 둔화 우려 / 0 → 정기 주주총회 개최")

    st.markdown("#### 📰 뉴스 감성 점수 트렌드 (최근 1개월)")

    # 기업 선택 드롭다운
    sent_corps = [r["corp_name"] for r in company_results if r["found"] and r.get("sentiment")]
    if not sent_corps:
        st.info("감성 분석 데이터가 없습니다. 조회 버튼을 눌러 뉴스를 수집하세요.")
    else:
        sent_options = ["전체"] + sorted(set(sent_corps))
        selected_sent_corp = st.selectbox("기업 선택", options=sent_options, key="sent_corp_select")
        sent_label = "전체 기업" if selected_sent_corp == "전체" else selected_sent_corp

        sent_rows = []
        for r in company_results:
            corp = r["corp_name"]
            if selected_sent_corp != "전체" and corp != selected_sent_corp:
                continue
            for item in r.get("sentiment", []):
                d = item.get("date")
                if d and isinstance(d, str) and len(d) == 10:
                    try:
                        sent_rows.append({
                            "기업명": corp,
                            "날짜": d,
                            "감성점수": float(item.get("score", 0)),
                            "헤드라인": item.get("headline", ""),
                        })
                    except (TypeError, ValueError):
                        pass

        if not sent_rows:
            st.info("유효한 날짜 데이터가 없습니다.")
        else:
            df_sent = pd.DataFrame(sent_rows)
            df_sent_agg = (
                df_sent.groupby(["날짜", "기업명"])["감성점수"]
                .mean()
                .round(1)
                .reset_index()
                .sort_values("날짜")
            )
            fig_sent = px.line(
                df_sent_agg,
                x="날짜", y="감성점수", color="기업명",
                title=f"뉴스 감성 점수 트렌드 — {sent_label}",
                markers=True,
                range_y=[-5.5, 5.5],
            )
            fig_sent.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig_sent.update_layout(
                hovermode="x unified",
                yaxis_title="감성 점수",
                xaxis_title="날짜",
                yaxis=dict(tickvals=[-5, -3, -1, 0, 1, 3, 5]),
            )
            st.plotly_chart(fig_sent, use_container_width=True)
            st.markdown(
                "<p style='color:gray; font-size:0.78rem; margin-top:-8px'>"
                "※ AI 기반 감성 점수는 뉴스 트렌드 참고용이며, 투자 판단의 근거로 사용하지 마세요."
                "</p>",
                unsafe_allow_html=True,
            )

# ── Tab 3: 알림설정 (주요공시 + 원문 모니터링 통합) ──────
with tab_alert:
    if not company_results or all(not r["found"] for r in company_results):
        st.info("조회된 공시가 없습니다.")
    else:
        for result in company_results:
            if not result["found"]:
                continue
            with st.container(border=True):
                st.markdown(
                    f"<div style='display:flex;align-items:center;margin-bottom:4px'>"
                    f"{get_logo_html(result['corp_name'], 26)}"
                    f"<span style='font-size:1.15rem;font-weight:700;color:#1a2744'>"
                    f"{result['corp_name']}</span></div>",
                    unsafe_allow_html=True,
                )
                rows = result["all_rows"]
                if not rows:
                    st.info("해당 기간 조회된 공시가 없습니다.")
                    continue
                high_rows = [r for r in rows if r["중요도"] >= 7]
                if high_rows:
                    for row in high_rows:
                        _render_disclosure_card(row, _tab_ctx="alt_h")
                else:
                    st.success("이번 기간 고중요도 이벤트 없음 ✅")
                    top3 = rows[:3]
                    if top3:
                        st.markdown("**점수 상위 공시**")
                        for row in top3:
                            _render_disclosure_card(row, _tab_ctx="alt_t")

    # ── 원문 모니터링 (알림설정 탭 하단) ──────────────────
    st.divider()
    st.markdown("**📋 공시 원문 모니터링 (핵심 3건)**")
    for result in company_results:
        if not result["found"] or not result.get("top3"):
            continue
        with st.container(border=True):
            corp_name = result["corp_name"]
            _anom_mon = _corp_anomalies.get(corp_name, [])
            _hdr_txt = corp_name
            if _anom_mon:
                _hdr_txt += "  " + "  ".join(a["label"] for a in _anom_mon)
            _mh, _mb = st.columns([4, 1])
            with _mh:
                st.markdown(f"**{_hdr_txt}**")
            with _mb:
                ts = result["top_score"]
                if ts > 0:
                    st.markdown(f"최고점 {score_badge(ts)}", unsafe_allow_html=True)
            for disc in result["top3"]:
                _render_disclosure_card(disc, _tab_ctx="mon")
