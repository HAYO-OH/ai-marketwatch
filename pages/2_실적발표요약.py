import requests
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import settings
from services.claude_client import ClaudeClient
from services.dart_client import DartClient

st.set_page_config(page_title="실적 발표 요약", layout="wide")

@st.cache_resource
def _get_clients():
    return DartClient(), ClaudeClient()

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
def _fetch_peer_fundamentals(ticker_items: tuple) -> pd.DataFrame:
    """(종목명, ticker) 튜플 기반 동종업계 PER/PBR/시가총액 조회."""
    try:
        from pykrx import stock as krx  # noqa: PLC0415
        today_str = date.today().strftime("%Y%m%d")
        cap_df = krx.get_market_cap_by_ticker(today_str, market="ALL")
        rows = []
        for name, ticker in ticker_items:
            try:
                fund = krx.get_market_fundamental(today_str, today_str, ticker)
                if fund.empty:
                    per = pbr = None
                else:
                    pv = fund["PER"].iloc[-1]
                    bv = fund["PBR"].iloc[-1]
                    per = round(float(pv), 1) if pv > 0 else None
                    pbr = round(float(bv), 2) if bv > 0 else None
            except Exception:
                per = pbr = None
            cap = int(cap_df.loc[ticker, "시가총액"]) if ticker in cap_df.index else None
            rows.append({"종목명": name, "ticker": ticker, "시가총액": cap, "PER": per, "PBR": pbr})
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
    df[""] = df["종목명"].apply(lambda x: "◀ 현재" if x == current_corp else "")

    def _fmt_cap(v):
        if v and isinstance(v, (int, float)) and v > 0:
            return f"{v / 1e12:.1f}조"
        return "—"

    df["시가총액"] = df["시가총액"].apply(_fmt_cap)
    df["PER"] = df["PER"].apply(lambda x: f"{x:.1f}x" if x else "—")
    df["PBR"] = df["PBR"].apply(lambda x: f"{x:.2f}x" if x else "—")
    st.dataframe(
        df[["", "종목명", "시가총액", "PER", "PBR"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "":       st.column_config.TextColumn("", width=75),
            "종목명": st.column_config.TextColumn("종목명", width=140),
            "시가총액": st.column_config.TextColumn("시가총액", width=100),
            "PER":    st.column_config.TextColumn("PER", width=80),
            "PBR":    st.column_config.TextColumn("PBR", width=80),
        },
    )
    st.caption("데이터 기준: pykrx(KRX) 오늘 종가 · PER/PBR 음수는 N/A 처리")


def _render_earnings_calendar(cal_df: pd.DataFrame, analyzed_corp: str):
    st.markdown("#### 📅 실적 공시 캘린더")
    today = date.today()
    # 3주 윈도우: 지난주 월요일 ~ 다음다음주 일요일
    start_mon = today - timedelta(days=today.weekday() + 7)
    all_days = [start_mon + timedelta(days=i) for i in range(21)]

    # date → 공시 목록 매핑
    visible = set(all_days)
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
                for item in items[:3]:
                    corp = item["corp"]
                    report_title = item["report"]
                    is_current = corp == analyzed_corp
                    color = "#FF4B4B" if is_current else ("#999" if is_past else "#333")
                    weight = "bold" if is_current else "normal"
                    st.markdown(
                        f"<div style='font-size:0.71rem;color:{color};font-weight:{weight};"
                        f"padding:1px 2px;overflow:hidden;white-space:nowrap;"
                        f"text-overflow:ellipsis;' title='{report_title}'>{corp}</div>",
                        unsafe_allow_html=True,
                    )
                if len(items) > 3:
                    st.markdown(
                        f"<div style='font-size:0.69rem;color:#aaa;padding:1px 2px'>"
                        f"+{len(items)-3}건</div>",
                        unsafe_allow_html=True,
                    )
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    if cal_df.empty:
        st.info("해당 기간 수집된 실적 공시가 없습니다. (DART 정기공시 기준)")
    else:
        note = f"※ DART 정기공시(분기·반기·사업보고서, 잠정실적) 기준 · 오늘({today.strftime('%Y.%m.%d')}) 기준 ±3주"
        if analyzed_corp:
            note += f" · 빨간 글씨: {analyzed_corp}"
        st.caption(note)


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

if analyze_btn:
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
            fig.add_vline(
                x=event_ts, line_dash="dash", line_color="crimson", opacity=0.75,
                annotation_text="📋 실적 발표", annotation_position="top right",
                annotation_font_color="crimson",
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

    # ── 경쟁사 비교 ──────────────────────────────────────
    peers = _PEER_GROUPS.get(corp_full_name, [])
    if peers:
        st.divider()
        dart_c, _ = _get_clients()
        ticker_map: dict[str, str] = {}
        if r["stock_code"]:
            ticker_map[corp_full_name] = r["stock_code"]
        for p in peers[:4]:
            tc = dart_c.get_stock_code(p)
            if tc:
                ticker_map[p] = tc
        if len(ticker_map) > 1:
            with st.spinner("동종업계 데이터 조회 중... (pykrx)"):
                peer_df = _fetch_peer_fundamentals(tuple(sorted(ticker_map.items())))
            _render_peer_comparison(peer_df, corp_full_name)
        else:
            st.info("동종업계 종목코드를 찾을 수 없습니다.")

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
_render_earnings_calendar(_cal_df, _analyzed_corp)
