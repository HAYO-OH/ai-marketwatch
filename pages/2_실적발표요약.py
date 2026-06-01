import re
import requests
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import settings
from services.claude_client import ClaudeClient
from services.dart_client import DartClient
from utils.watchlist import render_watchlist_sidebar

st.set_page_config(page_title="실적 발표 요약", layout="wide")

@st.cache_resource
def _get_clients():
    return DartClient(), ClaudeClient()

# ── Tab 1 → Tab 2 선택 종목 자동 분석 ───────────────────
if st.session_state.get("selected_stock"):
    _incoming = st.session_state.pop("selected_stock")
    st.session_state["earn_corp_input"] = _incoming
    st.session_state["_auto_analyze"] = True

# ── 분기 정의 (2024 1Q ~ 2026 1Q) ─────────────────────────
_QUARTERS: dict[str, tuple[date, date]] = {
    "2026 1Q": (date(2026, 1, 1),  date(2026, 3, 31)),
    "2025 4Q": (date(2025, 10, 1), date(2025, 12, 31)),
    "2025 3Q": (date(2025, 7, 1),  date(2025, 9, 30)),
    "2025 2Q": (date(2025, 4, 1),  date(2025, 6, 30)),
    "2025 1Q": (date(2025, 1, 1),  date(2025, 3, 31)),
    "2024 4Q": (date(2024, 10, 1), date(2024, 12, 31)),
    "2024 3Q": (date(2024, 7, 1),  date(2024, 9, 30)),
    "2024 2Q": (date(2024, 4, 1),  date(2024, 6, 30)),
    "2024 1Q": (date(2024, 1, 1),  date(2024, 3, 31)),
}

_EARNINGS_KW = ["잠정실적", "영업이익", "잠정", "분기보고서", "반기보고서", "사업보고서", "실적"]

# ── 동종업계 피어 그룹 ─────────────────────────────────────
_PEER_GROUPS: dict[str, list[str]] = {
    "삼성전자":         ["SK하이닉스", "LG전자", "삼성SDI", "LG에너지솔루션"],
    "SK하이닉스":       ["삼성전자", "LG전자", "삼성SDI"],
    "현대자동차":       ["기아", "현대모비스", "현대글로비스", "현대제철"],
    "기아":             ["현대자동차", "현대모비스", "현대제철"],
    "NAVER":            ["카카오", "카카오페이", "카카오뱅크", "크래프톤"],
    "카카오":           ["NAVER", "카카오페이", "카카오뱅크"],
    "LG전자":           ["삼성전자", "LG디스플레이", "삼성SDI"],
    "LG에너지솔루션":   ["삼성SDI", "SK이노베이션", "POSCO홀딩스"],
    "삼성SDI":          ["LG에너지솔루션", "SK이노베이션", "삼성전자"],
    "KB금융":           ["신한지주", "하나금융지주", "우리금융지주"],
    "신한지주":         ["KB금융", "하나금융지주", "우리금융지주"],
    "하나금융지주":     ["KB금융", "신한지주", "우리금융지주"],
    "우리금융지주":     ["KB금융", "신한지주", "하나금융지주"],
    "셀트리온":         ["삼성바이오로직스", "한미약품"],
    "삼성바이오로직스": ["셀트리온", "한미약품"],
    "POSCO홀딩스":      ["현대제철", "고려아연"],
    "크래프톤":         ["NAVER", "카카오", "넷마블", "엔씨소프트"],
    "엔씨소프트":       ["크래프톤", "넷마블", "NAVER"],
    "LG화학":           ["롯데케미칼", "SK이노베이션", "한화솔루션"],
    "아모레퍼시픽":     ["LG생활건강"],
    "LG생활건강":       ["아모레퍼시픽"],
    "현대건설":         ["GS건설", "삼성물산", "대우건설"],
    "삼성물산":         ["현대건설", "GS건설", "현대글로비스"],
    "HD현대":           ["한화에어로스페이스", "현대중공업"],
    "한화에어로스페이스": ["HD현대", "LIG넥스원"],
}


def _best_earnings_item(items: list[dict]) -> dict | None:
    for kw in _EARNINGS_KW:
        for it in items:
            if kw in it.get("report_nm", ""):
                return it
    return None


# ── 캐시 함수들 ───────────────────────────────────────────

@st.cache_data(ttl=3600)
def _fetch_price(ticker: str, event_date: str, window: int = 5) -> pd.DataFrame:
    """실적 발표일 기준 전후 window 거래일 종가."""
    try:
        from pykrx import stock as krx  # noqa: PLC0415
        center = date(int(event_date[:4]), int(event_date[4:6]), int(event_date[6:]))
        buf = window * 3
        start = (center - timedelta(days=buf)).strftime("%Y%m%d")
        end = min(center + timedelta(days=buf), date.today()).strftime("%Y%m%d")
        df = krx.get_market_ohlcv_by_date(start, end, ticker)
        if df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index)
        idx = min(df.index.searchsorted(pd.Timestamp(center)), len(df) - 1)
        result = df.iloc[max(0, idx - window): idx + window + 1].copy()
        result["is_event"] = result.index == df.index[idx]
        return result
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def _fetch_peer_performance(ticker_items: tuple, today_str: str) -> pd.DataFrame:
    """(종목명, ticker, is_current) 튜플 기반 현재가·1M·3M 수익률 조회.
    get_market_ohlcv_by_date 만 사용 — KRX 인증 불필요."""
    try:
        from pykrx import stock as krx
        today = date(int(today_str[:4]), int(today_str[4:6]), int(today_str[6:]))
        start = (today - timedelta(days=110)).strftime("%Y%m%d")  # 3개월+여유
        rows = []
        for name, ticker, is_current in ticker_items:
            try:
                df = krx.get_market_ohlcv_by_date(start, today_str, ticker)
                if df.empty:
                    cur = ret_1m = ret_3m = None
                else:
                    cur = int(df["종가"].iloc[-1])
                    ret_1m = round((cur / df["종가"].iloc[-22] - 1) * 100, 1) if len(df) >= 22 else None
                    ret_3m = round((cur / df["종가"].iloc[-64] - 1) * 100, 1) if len(df) >= 64 else None
            except Exception:
                cur = ret_1m = ret_3m = None
            rows.append({"종목명": name, "ticker": ticker,
                         "현재가": cur, "1M수익률": ret_1m, "3M수익률": ret_3m, "is_current": is_current})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800)
def _fetch_earnings_calendar(bgn_de: str, end_de: str, dart_api_key: str) -> pd.DataFrame:
    """DART 정기공시 기준 실적 공시 캘린더 (전체 기업)."""
    _EKW = ["분기보고서", "반기보고서", "사업보고서", "잠정실적", "영업이익"]
    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": dart_api_key,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": "A",
                "page_count": 100,
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("list", [])
    except Exception:
        return pd.DataFrame()
    filtered = [it for it in items if any(kw in it.get("report_nm", "") for kw in _EKW)]
    if not filtered:
        return pd.DataFrame()
    df = pd.DataFrame(filtered)
    df["rcept_dt"] = pd.to_datetime(df["rcept_dt"], format="%Y%m%d")
    return df[["rcept_dt", "corp_name", "report_nm", "rcept_no"]].sort_values("rcept_dt")


@st.cache_data(ttl=3600)
def _fetch_kind_ir_calendar(bgn_de: str, end_de: str) -> pd.DataFrame:
    """KIND IR 발표 예정 일정 수집 → DataFrame[date: date, corp: str]
    KIND 세션 쿠키 방식 AJAX POST 파싱."""
    bgn = datetime.strptime(bgn_de, "%Y%m%d").date()
    end = datetime.strptime(end_de, "%Y%m%d").date()
    # 필요한 (year, month) 집합
    months: set = set()
    cur = bgn.replace(day=1)
    while cur <= end:
        months.add((cur.year, cur.month))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://kind.krx.co.kr/corpgeneral/irschedule.do?method=searchIRScheduleMain&gubun=iRScheduleCalendar",
        })
        base = "https://kind.krx.co.kr/corpgeneral/irschedule.do"
        sess.get(base, params={"method": "searchIRScheduleMain", "gubun": "iRScheduleCalendar"}, timeout=15)
        rows = []
        seen: set = set()
        for year, month in sorted(months):
            resp = sess.post(base, data={
                "method": "searchIRScheduleCalendar",
                "selYear": str(year), "selMonth": f"{month:02d}",
                "currentPageSize": "100", "pageIndex": "1",
            }, timeout=15)
            td_blocks = re.findall(r"<td[^>]*>(.*?)</td>", resp.text, re.DOTALL)
            for block in td_blocks:
                clean = re.sub(r"<[^>]+>", " ", block)
                day_m = re.search(r"^\s*(\d{1,2})\b", clean.strip())
                if not day_m:
                    continue
                day = int(day_m.group(1))
                if not 1 <= day <= 31:
                    continue
                titles = re.findall(r'title="([^"]{2,30})"', block)
                corps = [t for t in titles if re.search("[가-힣]", t) and "더보기" not in t]
                try:
                    evt_date = date(year, month, day)
                except ValueError:
                    continue
                if evt_date < bgn or evt_date > end:
                    continue
                for corp in corps:
                    key = (evt_date, corp)
                    if key not in seen:
                        seen.add(key)
                        rows.append({"date": evt_date, "corp": corp})
        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True) if rows else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ── 렌더링 헬퍼 ───────────────────────────────────────────

def _surprise_ui(surprise: str) -> tuple[str, str]:
    labels = {
        "BEAT":    ("🟢 BEAT",    "어닝 서프라이즈 — 예상 상회"),
        "MISS":    ("🔴 MISS",    "어닝 쇼크 — 예상 하회"),
        "IN_LINE": ("⚪ IN-LINE", "예상치 부합"),
        "UNKNOWN": ("❓ UNKNOWN", "판단 불가 (정보 부족)"),
    }
    return labels.get(surprise, ("❓", surprise))


def _render_peer_comparison(peer_df: pd.DataFrame, current_corp: str):
    st.markdown("#### 🏢 동종업계 비교")
    if peer_df.empty:
        st.info("동종업계 비교 데이터를 가져올 수 없습니다.")
        return
    df = peer_df.copy()
    df[""] = df["is_current"].apply(lambda x: "◀ 현재" if x else "") if "is_current" in df.columns \
        else df["종목명"].apply(lambda x: "◀ 현재" if x == current_corp else "")

    def _fmt_ret(v):
        if v is None:
            return "N/A"
        return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

    df["현재가"] = df["현재가"].apply(lambda v: f"{v:,}원" if v else "N/A")
    df["1M수익률"] = df["1M수익률"].apply(_fmt_ret)
    df["3M수익률"] = df["3M수익률"].apply(_fmt_ret)
    st.dataframe(
        df[["", "종목명", "현재가", "1M수익률", "3M수익률"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "":         st.column_config.TextColumn("", width=75),
            "종목명":   st.column_config.TextColumn("종목명", width=140),
            "현재가":   st.column_config.TextColumn("현재가", width=100),
            "1M수익률": st.column_config.TextColumn("1M 수익률", width=90),
            "3M수익률": st.column_config.TextColumn("3M 수익률", width=90),
        },
    )
    st.caption("데이터 기준: KRX 종가 · 1M=21거래일, 3M=63거래일 수익률")


def _render_earnings_calendar(cal_df: pd.DataFrame, kind_df: pd.DataFrame, analyzed_corp: str):
    st.markdown("#### 📅 실적 공시 캘린더")
    # 범례
    st.markdown(
        "<div style='font-size:0.79rem;color:#555;margin-bottom:4px'>"
        "<span style='color:#333;font-weight:bold'>●</span> 공시 완료 (DART)&nbsp;&nbsp;"
        "<span style='color:#1E88E5;font-weight:bold'>◆</span> IR 발표 예정 (KIND)</div>",
        unsafe_allow_html=True,
    )

    today = date.today()
    start_mon = today - timedelta(days=today.weekday() + 7)
    all_days = [start_mon + timedelta(days=i) for i in range(21)]
    visible = set(all_days)

    # DART 공시 맵
    cal_map: dict[date, list[dict]] = {}
    if not cal_df.empty:
        for _, row in cal_df.iterrows():
            d: date = row["rcept_dt"].date()
            if d in visible:
                cal_map.setdefault(d, []).append({
                    "corp": row["corp_name"],
                    "report": row["report_nm"],
                    "rcept_no": row["rcept_no"],
                })

    # KIND IR 예정일 맵
    kind_map: dict[date, list[str]] = {}
    if not kind_df.empty:
        for _, row in kind_df.iterrows():
            d: date = row["date"]
            if d in visible:
                kind_map.setdefault(d, []).append(row["corp"])

    # 요일 헤더
    hdr = st.columns(7)
    for col, label in zip(hdr, ["월", "화", "수", "목", "금", "토", "일"]):
        with col:
            st.markdown(
                f"<div style='text-align:center;font-weight:bold;font-size:0.85rem;"
                f"padding:5px 2px;background:#f0f2f6;border-radius:4px'>{label}</div>",
                unsafe_allow_html=True,
            )

    # 주별 렌더링
    for week in [all_days[i:i+7] for i in range(0, 21, 7)]:
        cols = st.columns(7)
        for col, day in zip(cols, week):
            with col:
                is_today = day == today
                is_past = day < today
                items = cal_map.get(day, [])
                kind_items = kind_map.get(day, [])
                bg = "#FF4B4B" if is_today else ("#f8f9fa" if is_past else "#ffffff")
                fg = "white" if is_today else ("#aaa" if is_past else "#222")
                border = "2px solid #FF4B4B" if is_today else "1px solid #e0e0e0"
                fw = "bold" if is_today else "normal"
                st.markdown(
                    f"<div style='text-align:center;padding:4px 2px;margin-top:4px;"
                    f"border:{border};border-radius:5px;background:{bg};color:{fg};'>"
                    f"<span style='font-size:0.82rem;font-weight:{fw}'>"
                    f"{day.strftime('%m/%d')}</span></div>",
                    unsafe_allow_html=True,
                )
                # ● DART 공시 완료
                for item in items[:3]:
                    corp = item["corp"]
                    report_title = item["report"]
                    is_current = corp == analyzed_corp
                    color = "#FF4B4B" if is_current else ("#999" if is_past else "#333")
                    weight = "bold" if is_current else "normal"
                    st.markdown(
                        f"<div style='font-size:0.71rem;color:{color};font-weight:{weight};"
                        f"padding:1px 2px;overflow:hidden;white-space:nowrap;"
                        f"text-overflow:ellipsis;' title='{report_title}'>● {corp}</div>",
                        unsafe_allow_html=True,
                    )
                if len(items) > 3:
                    st.markdown(
                        f"<div style='font-size:0.69rem;color:#aaa;padding:1px 2px'>"
                        f"●+{len(items)-3}건</div>",
                        unsafe_allow_html=True,
                    )
                # ◆ KIND IR 발표 예정
                for corp in kind_items[:2]:
                    is_current = corp == analyzed_corp
                    color = "#FF4B4B" if is_current else "#1E88E5"
                    weight = "bold" if is_current else "normal"
                    st.markdown(
                        f"<div style='font-size:0.71rem;color:{color};font-weight:{weight};"
                        f"padding:1px 2px;overflow:hidden;white-space:nowrap;"
                        f"text-overflow:ellipsis;'>◆ {corp}</div>",
                        unsafe_allow_html=True,
                    )
                if len(kind_items) > 2:
                    st.markdown(
                        f"<div style='font-size:0.69rem;color:#1E88E5;padding:1px 2px'>"
                        f"◆+{len(kind_items)-2}건</div>",
                        unsafe_allow_html=True,
                    )
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    notes = []
    if not cal_df.empty:
        notes.append("DART 정기공시")
    if not kind_df.empty:
        notes.append("KIND IR 발표 예정")
    if not notes:
        st.info("해당 기간 수집된 실적 공시가 없습니다.")
    else:
        note = f"※ {' · '.join(notes)} · 오늘({today.strftime('%Y.%m.%d')}) 기준 ±3주"
        if analyzed_corp:
            note += f" · 빨간 글씨: {analyzed_corp}"
        st.caption(note)


# ── 사이드바: 관심 종목 ───────────────────────────────────
render_watchlist_sidebar()

with st.sidebar:
    _wl = st.session_state.get("watchlist", [])
    if _wl:
        st.subheader("빠른 분석")
        _wl_sel = st.selectbox(
            "관심 종목 선택",
            options=["선택..."] + _wl,
            key="wl_sel_tab2",
            label_visibility="collapsed",
        )
        if _wl_sel != "선택..." and st.button("📊 이 종목 분석", key="wl_analyze_btn", use_container_width=True):
            st.session_state["earn_corp_input"] = _wl_sel
            st.session_state["_auto_analyze"] = True
            st.rerun()
        st.divider()

# ── 메인: 입력 폼 (중앙 배치) ─────────────────────────────
st.title("📊 실적 발표 요약")
st.markdown("<br>", unsafe_allow_html=True)

_, center, _ = st.columns([1, 2, 1])
with center:
    corp_input = st.text_input(
        "기업명",
        placeholder="예: 삼성전자",
        label_visibility="collapsed",
        key="earn_corp_input",
    )
    quarter_sel = st.selectbox(
        "분기",
        options=list(_QUARTERS.keys()),
        index=1,
        label_visibility="collapsed",
        key="earn_quarter_sel",
    )
    st.markdown("<br>", unsafe_allow_html=True)
    analyze_btn = st.button(
        "📊 실적 분석 시작",
        type="primary",
        use_container_width=True,
    )

# ── 분석 실행 ─────────────────────────────────────────────
progress_slot = st.empty()

_auto_analyze = st.session_state.pop("_auto_analyze", False)
if analyze_btn or _auto_analyze:
    corp_name = corp_input.strip()
    if not corp_name:
        st.warning("기업명을 입력하세요.")
    else:
        dart, claude = _get_clients()
        quarter = quarter_sel
        q_start, q_end = _QUARTERS[quarter]
        search_start = q_start.strftime("%Y%m%d")
        search_end = (q_end + timedelta(days=120)).strftime("%Y%m%d")

        progress_slot.progress(0.10, text=f"[1/5] {corp_name} — DART 기업 조회 중...")
        company = dart.search_company(corp_name)
        if company is None:
            progress_slot.empty()
            st.error(f"DART에서 '{corp_name}'을(를) 찾을 수 없습니다. 기업명을 확인하세요.")
        else:
            corp_code = company["corp_code"]
            corp_full_name = company["corp_name"]

            progress_slot.progress(0.28, text=f"[2/5] {corp_full_name} — {quarter} 실적 공시 조회 중...")
            all_items = dart.get_disclosures(corp_code, search_start, search_end)
            earnings_items = [
                it for it in all_items
                if any(kw in it.get("report_nm", "") for kw in _EARNINGS_KW)
            ]
            best = _best_earnings_item(earnings_items)

            if best is None:
                progress_slot.empty()
                st.warning(f"{corp_full_name} {quarter} 기간에 실적 공시를 찾을 수 없습니다.")
                if all_items:
                    with st.expander("수집된 전체 공시 목록"):
                        for it in all_items[:20]:
                            st.caption(f"- [{it['rcept_dt']}] {it['report_nm']}")
            else:
                rcept_no = best.get("rcept_no", "")
                rcept_dt = best.get("rcept_dt", "")
                report_nm = best.get("report_nm", "")

                progress_slot.progress(0.46, text=f"[3/5] {corp_full_name} — 공시 원문 가져오는 중... ({report_nm})")
                doc_text = dart.get_document_text(rcept_no) if rcept_no else ""

                progress_slot.progress(0.65, text=f"[4/5] {corp_full_name} — AI 실적 분석 중...")
                analysis = claude.analyze_earnings(corp_full_name, quarter, report_nm, doc_text)

                progress_slot.progress(0.85, text=f"[5/5] {corp_full_name} — 주가 데이터 수집 중...")
                stock_code = dart.get_stock_code(corp_full_name)
                price_df = _fetch_price(stock_code, rcept_dt) if (stock_code and rcept_dt) else pd.DataFrame()

                progress_slot.progress(1.0, text="✅ 완료!")
                progress_slot.empty()

                st.session_state.earnings_result = {
                    "corp_name": corp_full_name,
                    "quarter": quarter,
                    "rcept_dt": rcept_dt,
                    "report_nm": report_nm,
                    "rcept_no": rcept_no,
                    "analysis": analysis,
                    "price_df": price_df,
                    "stock_code": stock_code or "",
                    "earnings_items": earnings_items,
                }

# ── 분석 결과 렌더링 ───────────────────────────────────────
if st.session_state.get("earnings_result"):
    r = st.session_state.earnings_result
    analysis = r["analysis"]
    corp_full_name = r["corp_name"]
    quarter = r["quarter"]
    price_df = r["price_df"]

    st.divider()

    # 헤더
    hdr_l, hdr_r = st.columns([3, 1])
    with hdr_l:
        st.subheader(f"{corp_full_name} {quarter} 실적 분석")
        disc_info = f"📋 [{r['rcept_dt']}] {r['report_nm']}"
        if r["rcept_no"]:
            dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"
            st.markdown(f"[{disc_info}]({dart_url})")
        else:
            st.caption(disc_info)
    with hdr_r:
        if r["stock_code"]:
            st.caption(f"종목코드: {r['stock_code']}")

    # 요약 카드
    with st.container(border=True):
        surprise = analysis.get("earnings_surprise", "UNKNOWN")
        surprise_reason = analysis.get("surprise_reason", "")
        key_metrics = analysis.get("key_metrics", [])
        icon, desc = _surprise_ui(surprise)

        badge_col, metrics_col = st.columns([1, 2])
        with badge_col:
            if surprise == "BEAT":
                st.success(f"## {icon}")
            elif surprise == "MISS":
                st.error(f"## {icon}")
            else:
                st.info(f"## {icon}")
            st.markdown(f"**{desc}**")
            if surprise_reason:
                st.caption(surprise_reason)
        with metrics_col:
            if key_metrics:
                metric_cols = st.columns(min(len(key_metrics), 4))
                for i, m in enumerate(key_metrics[:4]):
                    with metric_cols[i]:
                        delta = m.get("전분기대비", "")
                        st.metric(
                            label=m.get("항목", ""),
                            value=m.get("값", "—"),
                            delta=delta if (delta and delta != "해당없음") else None,
                        )
            else:
                st.caption("수치 데이터 추출 불가")

    # AI 분석 섹션
    col_l, col_r = st.columns(2)
    with col_l:
        with st.container(border=True):
            st.markdown("#### 📈 전분기 대비 핵심 변화")
            for c in analysis.get("key_changes", []) or ["정보 없음"]:
                st.markdown(f"• {c}")
        with st.container(border=True):
            st.markdown("#### 📋 가이던스")
            st.markdown(analysis.get("guidance", "정보 없음"))
    with col_r:
        with st.container(border=True):
            st.markdown("#### ⚠️ 리스크 포인트")
            for risk in analysis.get("risks", []) or ["정보 없음"]:
                st.markdown(f"• {risk}")

    # 주가 반응 차트
    st.markdown("#### 📉 실적 발표 전후 주가 반응")
    if price_df.empty:
        if r["stock_code"]:
            st.info("주가 데이터를 가져올 수 없습니다.")
        else:
            st.info("상장 종목이 아니거나 종목코드를 찾을 수 없습니다.")
    else:
        if "is_event" in price_df.columns:
            ev_rows = price_df[price_df["is_event"]]
            event_ts = ev_rows.index[0] if not ev_rows.empty else None
        else:
            event_ts = None
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=price_df.index, y=price_df["종가"],
            mode="lines+markers", name="종가",
            line=dict(color="#4A90D9", width=2), marker=dict(size=7),
            hovertemplate="%{x|%Y.%m.%d}<br>종가: %{y:,}원<extra></extra>",
        ))
        if event_ts is not None:
            x_date = str(event_ts)[:10]
            fig.add_shape(
                type="line",
                x0=x_date, x1=x_date,
                y0=0, y1=1,
                xref="x", yref="paper",
                line=dict(color="crimson", width=2, dash="dash"),
            )
            fig.add_annotation(
                x=x_date, y=1, xref="x", yref="paper",
                text="📋 실적 발표", showarrow=False,
                xanchor="left", yanchor="top",
                font=dict(color="crimson"),
            )
        fig.update_layout(
            title=f"{corp_full_name} {quarter} 실적 발표 전후 ±5 거래일",
            xaxis_title="날짜", yaxis_title="종가 (원)",
            hovermode="x unified", height=360,
            margin=dict(t=50, b=40), yaxis=dict(tickformat=","),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(
            "<p style='color:gray;font-size:0.78rem;margin-top:-8px'>"
            "※ 주가 데이터는 pykrx(KRX)에서 수집됩니다. 투자 판단의 근거로 사용하지 마세요."
            "</p>", unsafe_allow_html=True,
        )

    # ── 동종업계 비교 ────────────────────────────────────────────────────────────────────
    st.divider()
    peers = _PEER_GROUPS.get(corp_full_name, [])
    if r["stock_code"] and peers:
        dart_c, _ = _get_clients()
        ticker_items_list = [(corp_full_name, r["stock_code"], True)]
        for p in peers[:4]:
            tc = dart_c.get_stock_code(p)
            if tc:
                ticker_items_list.append((p, tc, False))
        if len(ticker_items_list) > 1:
            with st.spinner("동종업계 주가 데이터 조회 중..."):
                peer_df = _fetch_peer_performance(tuple(ticker_items_list), date.today().strftime("%Y%m%d"))
            _render_peer_comparison(peer_df, corp_full_name)
        else:
            st.info("동종업계 종목코드를 찾을 수 없습니다.")
    elif not r["stock_code"]:
        st.info("상장 종목이 아니거나 종목코드를 찾을 수 없습니다.")

    # 수집된 공시 목록
    if r["earnings_items"]:
        with st.expander(f"📄 수집된 실적 공시 목록 ({len(r['earnings_items'])}건)", expanded=False):
            for it in r["earnings_items"]:
                url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it.get('rcept_no', '')}"
                mark = "**▶**" if it.get("rcept_no") == r["rcept_no"] else "   "
                st.markdown(f"{mark} [{it['rcept_dt']}] [{it['report_nm']}]({url})")
            st.caption("**▶** 표시: 분석에 사용된 공시")

# ── 실적 공시 캘린더 (항상 표시) ────────────────────────
st.divider()
_today = date.today()
_bgn_cal = (_today - timedelta(days=7)).strftime("%Y%m%d")
_end_cal = (_today + timedelta(days=14)).strftime("%Y%m%d")
_analyzed_corp = (st.session_state.get("earnings_result") or {}).get("corp_name", "")
with st.spinner("실적 캘린더 로딩 중..."):
    _cal_df = _fetch_earnings_calendar(_bgn_cal, _end_cal, settings.dart_api_key)
    _kind_df = _fetch_kind_ir_calendar(_bgn_cal, _end_cal)
_render_earnings_calendar(_cal_df, _kind_df, _analyzed_corp)
