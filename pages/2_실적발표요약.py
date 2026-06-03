import re
import requests
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import settings
from services.claude_client import ClaudeClient
from services.dart_client import DartClient
from utils.logos import get_logo_html
from utils.nav import render_top_nav
from utils.pdf_report import generate_earnings_pdf
from utils.watchlist import render_watchlist_sidebar

st.set_page_config(page_title="실적 발표 요약", layout="wide")

@st.cache_resource
def _get_clients():
    return DartClient(), ClaudeClient()


def _date_to_quarter(date_str: str) -> str:
    """YYYYMMDD → '2025 4Q' 형태의 분기 키."""
    _Q_KEYS = [
        "2026 1Q", "2025 4Q", "2025 3Q", "2025 2Q", "2025 1Q",
        "2024 4Q", "2024 3Q", "2024 2Q", "2024 1Q",
    ]
    try:
        year = int(date_str[:4])
        month = int(date_str[4:6])
        q = "1Q" if month <= 3 else "2Q" if month <= 6 else "3Q" if month <= 9 else "4Q"
        key = f"{year} {q}"
        return key if key in _Q_KEYS else "2025 4Q"
    except (ValueError, IndexError):
        return "2025 4Q"


# ── Tab 1 → Tab 2 선택 종목 자동 분석 ───────────────────
if st.session_state.get("selected_stock"):
    _incoming = st.session_state.pop("selected_stock")
    _incoming_date = st.session_state.pop("selected_date", "")
    st.session_state["earn_corp_input"] = _incoming
    st.session_state["_auto_analyze"] = True
    if _incoming_date:
        st.session_state["earn_quarter_sel"] = _date_to_quarter(_incoming_date)

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

def _shorten_metric_label(label: str) -> str:
    """'매출액(2026년 1Q 전년동기대비)' → '매출액 YoY' 형태로 단축."""
    yoy = "전년동기" in label or "yoy" in label.lower()
    qoq = ("전분기" in label or "qoq" in label.lower()) and not yoy
    short = re.sub(r"\s*\([^)]*\)", "", label).strip()
    short = re.sub(r"\s*(전년동기대비|전분기대비|전년대비|전분기|YoY|QoQ)", "", short, flags=re.IGNORECASE).strip()
    if yoy:
        short += " YoY"
    elif qoq:
        short += " QoQ"
    return short or label


def _fmt_krw(val: str) -> str:
    """수치 문자열을 조/억 단위로 변환.
    기준: 1조 이상 → X.XX조원 / 1000억 이상 → XXXX억원 / 그 이하 → 원래 단위 유지
    단위가 없거나 % 등 비금융 값은 그대로 반환.
    """
    if not val or val in ("—", "해당없음", "N/A"):
        return val

    s = val.strip()
    sign = ""
    if s.startswith(("+", "▲")):
        sign, s = "+", s[1:]
    elif s.startswith(("-", "▼")):
        sign, s = "-", s[1:]

    if "백만원" in s:
        raw = s.replace("백만원", "").replace(",", "").strip()
        try:
            num = float(raw)
        except ValueError:
            return val
        if abs(num) >= 1_000_000:       # 1조 이상 (1,000,000백만)
            return sign + f"{num / 1_000_000:.2f}조원"
        if abs(num) >= 100_000:         # 1000억 이상 (100,000백만)
            return sign + f"{num / 100:,.0f}억원"
        return val                      # 1000억 미만 → 원래 단위 유지

    if "억원" in s:
        raw = s.replace("억원", "").replace(",", "").strip()
        try:
            num = float(raw)
        except ValueError:
            return val
        if abs(num) >= 10_000:          # 1조 이상 (10,000억)
            return sign + f"{num / 10_000:.2f}조원"
        if abs(num) >= 1_000:           # 1000억 이상
            return sign + f"{num:,.0f}억원"
        return val

    return val


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


# ── 실적 히스토리 헬퍼 ───────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_earnings_history(corp_name: str, n_quarters: int = 8) -> list[dict]:
    """최근 n_quarters 분기 실적 공시 수집 + Claude 배치 분석.
    반환: [{quarter, rcept_dt, report_nm, sales_val, op_profit_val, op_profit_qoq, surprise}]"""
    from concurrent.futures import ThreadPoolExecutor

    dart  = DartClient()
    claude = ClaudeClient()

    company = dart.search_company(corp_name)
    if company is None:
        return []
    corp_code = company["corp_code"]

    today = date.today()
    quarter_list = [
        (k, s, e)
        for k, (s, e) in list(_QUARTERS.items())[:n_quarters]
        if e <= today + timedelta(days=30)
    ]

    # 1. 각 분기 공시 목록 조회
    disc_items: list[dict] = []
    for qkey, qstart, qend in quarter_list:
        try:
            items = dart.get_disclosures(
                corp_code,
                qstart.strftime("%Y%m%d"),
                (qend + timedelta(days=120)).strftime("%Y%m%d"),
                page_count=30,
            )
        except Exception:
            items = []
        best = None
        for kw in _EARNINGS_KW:
            for it in items:
                if kw in it.get("report_nm", ""):
                    best = it
                    break
            if best:
                break
        disc_items.append({
            "quarter":   qkey,
            "rcept_dt":  best.get("rcept_dt", "") if best else "",
            "report_nm": best.get("report_nm", "") if best else "",
            "rcept_no":  best.get("rcept_no", "") if best else "",
            "doc_text":  "",
        })

    # 2. 원문 병렬 수집 (4 workers)
    def _fetch_text(item: dict) -> tuple[str, str]:
        if not item["rcept_no"]:
            return item["quarter"], ""
        try:
            return item["quarter"], dart.get_document_text(item["rcept_no"], max_chars=1500)
        except Exception:
            return item["quarter"], ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        text_map: dict[str, str] = dict(pool.map(_fetch_text, disc_items))
    for it in disc_items:
        it["doc_text"] = text_map.get(it["quarter"], "")

    # 3. Claude 배치 분석
    analysis_map = {
        a["quarter"]: a
        for a in claude.analyze_earnings_history(corp_name, disc_items)
    }

    # 4. 머지
    return [
        {
            "quarter":       it["quarter"],
            "rcept_dt":      it["rcept_dt"],
            "report_nm":     it["report_nm"],
            "rcept_no":      it["rcept_no"],
            "sales_val":     analysis_map.get(it["quarter"], {}).get("sales_val"),
            "op_profit_val": analysis_map.get(it["quarter"], {}).get("op_profit_val"),
            "op_profit_qoq": analysis_map.get(it["quarter"], {}).get("op_profit_qoq"),
            "surprise":      analysis_map.get(it["quarter"], {}).get("surprise", "UNKNOWN"),
        }
        for it in disc_items
    ]


def _render_earnings_history_chart(history: list[dict], corp_name: str, current_quarter: str) -> None:
    """8분기 실적 히스토리 차트 렌더링."""
    if not history:
        st.info("실적 히스토리 데이터를 가져올 수 없습니다.")
        return

    ordered   = list(reversed(history))          # 시간 순(오래된 → 최신)
    quarters  = [h["quarter"]         for h in ordered]
    sales_v   = [h.get("sales_val")   for h in ordered]
    op_v      = [h.get("op_profit_val") for h in ordered]
    qoq_v     = [h.get("op_profit_qoq") for h in ordered]
    surprises = [h.get("surprise", "UNKNOWN") for h in ordered]

    _BAR_COLOR = {
        "BEAT":    "#22a355",
        "MISS":    "#FF4B4B",
        "IN_LINE": "#4A90D9",
        "UNKNOWN": "#aaaaaa",
    }
    _BADGE = {"BEAT": "BEAT", "MISS": "MISS", "IN_LINE": "LINE", "UNKNOWN": "N/A"}

    bar_colors  = [_BAR_COLOR.get(s, "#aaa") for s in surprises]
    badge_texts = [_BADGE.get(s, "N/A")      for s in surprises]

    fig = go.Figure()

    # 매출액 bars
    fig.add_trace(go.Bar(
        name="매출액",
        x=quarters, y=sales_v,
        marker=dict(color="#B0C4DE", opacity=0.75),
        yaxis="y1",
        hovertemplate="<b>%{x}</b><br>매출액: %{y:.1f}조원<extra></extra>",
    ))

    # 영업이익 bars (BEAT/MISS 색상 + 배지 텍스트)
    fig.add_trace(go.Bar(
        name="영업이익",
        x=quarters, y=op_v,
        marker=dict(color=bar_colors, opacity=0.9),
        text=badge_texts,
        textposition="outside",
        textfont=dict(size=9, color=bar_colors),
        yaxis="y1",
        hovertemplate="<b>%{x}</b><br>영업이익: %{y:.1f}조원<extra></extra>",
    ))

    # 영업이익 QoQ 라인 (오른쪽 축)
    fig.add_trace(go.Scatter(
        name="영업이익 QoQ%",
        x=quarters, y=qoq_v,
        mode="lines+markers",
        line=dict(color="#FF8C00", width=2.5, dash="dot"),
        marker=dict(size=8, color="#FF8C00", line=dict(width=1.5, color="white")),
        yaxis="y2",
        connectgaps=False,
        hovertemplate="<b>%{x}</b><br>QoQ: %{y:+.1f}%<extra></extra>",
    ))

    # 현재 분기 배경 강조
    if current_quarter in quarters:
        ci = quarters.index(current_quarter)
        fig.add_shape(
            type="rect",
            x0=ci - 0.45, x1=ci + 0.45, y0=0, y1=1,
            xref="x", yref="paper",
            fillcolor="rgba(255, 75, 75, 0.07)", line_width=0,
        )

    fig.update_layout(
        title=dict(text=f"📊 {corp_name} 실적 히스토리 (최근 8분기)", font=dict(size=15)),
        barmode="group",
        xaxis=dict(title="분기", tickfont=dict(size=11)),
        yaxis=dict(title="금액 (조원)", side="left", gridcolor="#f0f0f0"),
        yaxis2=dict(
            title="영업이익 QoQ (%)", side="right",
            overlaying="y", showgrid=False,
            zeroline=True, zerolinecolor="#cccccc",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
        margin=dict(t=70, b=40, l=60, r=60),
        plot_bgcolor="white", paper_bgcolor="white",
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "※ 영업이익 막대 색상: 초록=BEAT  빨강=MISS  파랑=IN-LINE  회색=N/A  |"
        "  점선: 전분기 대비 영업이익 증감률  |  음영: 현재 분석 분기"
    )


# ── 경영진 코멘트 헬퍼 ───────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_mgmt_comments(corp_name: str, quarter: str) -> dict:
    """Tavily 검색 + Claude 추출로 경영진 코멘트 수집."""
    from services.tavily_client import TavilyClient as _TavCli

    tavily = _TavCli()
    claude  = ClaudeClient()

    results: list[dict] = []
    for query in [
        f"{corp_name} {quarter} 실적발표 CEO 대표이사 발언",
        f"{corp_name} 어닝콜 경영진 가이던스",
    ]:
        try:
            results = tavily.search(query, max_results=5)
        except Exception:
            results = []
        if results:
            break

    articles_text = ""
    source_url = ""
    for res in results[:5]:
        title   = res.get("title", "")
        content = res.get("content", "")
        url     = res.get("url", "")
        if title or content:
            articles_text += f"제목: {title}\n내용: {content[:400]}\n\n"
        if url and not source_url:
            source_url = url

    comments = claude.extract_mgmt_comments(corp_name, quarter, articles_text)
    if source_url:
        comments["source"] = source_url
    return comments


def _render_mgmt_comments(comments: dict) -> None:
    """경영진 코멘트 인용구 UI 렌더링."""
    if not comments.get("has_content"):
        st.info("공개된 경영진 발언을 찾을 수 없습니다.")
        return

    ceo_text = comments.get("ceo_comment")
    cfo_text = comments.get("cfo_comment")
    ceo_name = comments.get("ceo_speaker") or "대표이사"
    cfo_name = comments.get("cfo_speaker") or "CFO"
    keywords = comments.get("outlook_keywords") or []

    def _quote_html(text: str, speaker: str, accent: str) -> str:
        return (
            f"<div style='border-left:3px solid {accent};padding:10px 14px;"
            f"background:#f8f9fa;border-radius:0 6px 6px 0'>"
            f"<p style='font-style:italic;color:#333;font-size:0.88rem;"
            f"line-height:1.55;margin:0 0 6px 0'>"
            f"&ldquo;{text}&rdquo;</p>"
            f"<span style='font-size:0.76rem;color:#888;font-weight:500'>"
            f"&mdash; {speaker}</span></div>"
        )

    col_l, col_r = st.columns(2)
    if ceo_text:
        with col_l:
            st.markdown("**💬 CEO 발언**")
            st.markdown(_quote_html(ceo_text, ceo_name, "#4A90D9"), unsafe_allow_html=True)
    if cfo_text:
        _cfo_col = col_r if ceo_text else col_l
        with _cfo_col:
            st.markdown("**💬 CFO 가이던스**")
            st.markdown(_quote_html(cfo_text, cfo_name, "#22a355"), unsafe_allow_html=True)

    if keywords:
        kw_html = "".join(
            f"<span style='background:#eef3fb;color:#2563eb;padding:3px 10px;"
            f"border-radius:12px;font-size:0.8rem;margin-right:6px'>{k}</span>"
            for k in keywords[:3]
        )
        st.markdown(
            f"<div style='margin-top:10px'>"
            f"<span style='font-size:0.82rem;color:#888;font-weight:600'>향후 전망&nbsp;&nbsp;</span>"
            f"{kw_html}</div>",
            unsafe_allow_html=True,
        )

    source = comments.get("source", "")
    if source:
        st.markdown(
            f"<div style='font-size:0.75rem;color:#aaa;margin-top:8px'>"
            f"<a href='{source}' target='_blank' style='color:#aaa;text-decoration:none'>"
            f"출처 보기 →</a></div>",
            unsafe_allow_html=True,
        )


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_analyst_report(corp_name: str, quarter: str) -> dict:
    """Tavily 검색 + Claude 추출로 애널리스트 리포트 요약 수집."""
    from services.tavily_client import TavilyClient as _TavCli
    tavily = _TavCli()
    claude  = ClaudeClient()

    results: list[dict] = []
    for query in [
        f"{corp_name} {quarter} 애널리스트 리포트 목표주가 투자의견",
        f"{corp_name} 증권사 목표주가 매수의견 리포트",
    ]:
        try:
            results = tavily.search(query, max_results=5)
        except Exception:
            results = []
        if results:
            break

    articles_text = ""
    for res in results[:5]:
        title   = res.get("title", "")
        content = res.get("content", "")
        if title or content:
            articles_text += f"제목: {title}\n내용: {content[:400]}\n\n"

    return claude.extract_analyst_report(corp_name, quarter, articles_text)


def _render_analyst_report(report: dict, current_price: float | None) -> None:
    """애널리스트 리포트 요약 UI 렌더링."""
    st.markdown(
        "<div style='background:#1a2744;color:white;padding:5px 12px;"
        "border-radius:4px 4px 0 0;font-size:0.79rem;font-weight:600;margin-top:18px'>"
        "📋 애널리스트 리포트 요약</div>",
        unsafe_allow_html=True,
    )

    brokers   = report.get("brokers") or []
    consensus = report.get("consensus_target")
    core_cmt  = report.get("core_comment")

    if not report.get("has_content") or not brokers:
        st.markdown(
            "<div style='border:1px solid #e2e5ea;border-top:none;"
            "border-radius:0 0 4px 4px;background:white;"
            "padding:14px 16px;font-size:0.85rem;color:#aaa'>"
            "공개된 리포트 없음</div>",
            unsafe_allow_html=True,
        )
        return

    _OP_COLOR = {"매수": "#00d084", "중립": "#f0a500", "매도": "#ff4b4b"}

    def _gap_html(tp: int | None) -> str:
        if not tp or not current_price or current_price <= 0:
            return ""
        gap = (tp - current_price) / current_price * 100
        col = "#00d084" if gap >= 0 else "#ff4b4b"
        arr = "▲" if gap >= 0 else "▼"
        return (
            f"<div style='color:{col};font-size:0.74rem;margin-top:1px'>"
            f"{arr} {abs(gap):.1f}% 괴리</div>"
        )

    brokers = [bk for bk in brokers if bk.get("target_price")]
    if not brokers:
        st.markdown(
            "<div style='border:1px solid #e2e5ea;border-top:none;"
            "border-radius:0 0 4px 4px;background:white;"
            "padding:14px 16px;font-size:0.85rem;color:#aaa'>"
            "공개된 리포트 없음</div>",
            unsafe_allow_html=True,
        )
        return

    cols = st.columns(min(len(brokers), 3))
    for i, bk in enumerate(brokers[:3]):
        op    = bk.get("opinion", "중립")
        op_c  = _OP_COLOR.get(op, "#888")
        tp    = bk.get("target_price")
        tp_s  = f"₩{tp:,}"
        with cols[i]:
            st.markdown(
                f"<div style='border:1px solid #e2e5ea;border-top:3px solid {op_c};"
                f"border-radius:4px;padding:10px 12px;background:white;height:100%'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                f"<span style='font-size:0.82rem;font-weight:700;color:#1a2744'>{bk.get('name','—')}</span>"
                f"<span style='background:{op_c};color:white;border-radius:3px;"
                f"padding:1px 8px;font-size:0.73rem;font-weight:700'>{op}</span>"
                f"</div>"
                f"<div style='font-size:1.1rem;font-weight:700;color:#1a2744;margin-top:7px'>{tp_s}</div>"
                f"{_gap_html(tp)}"
                f"<div style='font-size:0.78rem;color:#666;margin-top:6px;line-height:1.4'>"
                f"{bk.get('comment','')}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # 컨센서스 + 핵심 코멘트
    _con_html = ""
    if consensus:
        gap = (consensus - current_price) / current_price * 100 if current_price and current_price > 0 else None
        gap_s = (
            f" <span style='color:{'#00d084' if gap>=0 else '#ff4b4b'};font-size:0.8rem'>"
            f"({'▲' if gap>=0 else '▼'}{abs(gap):.1f}%)</span>"
            if gap is not None else ""
        )
        _con_html = (
            f"<span style='font-size:0.83rem;color:#555'>컨센서스 목표주가</span>"
            f"<span style='font-size:1.0rem;font-weight:700;color:#1a2744;margin-left:8px'>"
            f"₩{consensus:,}{gap_s}</span>"
        )

    st.markdown(
        f"<div style='border:1px solid #e2e5ea;border-top:none;"
        f"background:#f8f9fa;padding:10px 14px;margin-top:-1px;"
        f"border-radius:0 0 4px 4px'>"
        + (f"<div style='margin-bottom:{'6px' if core_cmt else '0'}'>{_con_html}</div>" if _con_html else "")
        + (f"<div style='font-size:0.83rem;color:#555;line-height:1.5'>{core_cmt}</div>" if core_cmt else "")
        + "</div>",
        unsafe_allow_html=True,
    )


# ── 사이드바: 관심 종목 + 상단 네비게이션 ─────────────────
render_watchlist_sidebar()
render_top_nav("pages/2_실적발표요약.py")

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
    f"실적 발표 요약</span>"
    f"<span style='color:#7a8fbb;font-size:0.78rem;margin-left:12px'>"
    f"AI 실적 분석 · 동종업계 비교 · 히스토리</span></div>"
    f"<span style='color:#7a8fbb;font-size:0.78rem'>{date.today().strftime('%Y.%m.%d')}</span>"
    f"</div>",
    unsafe_allow_html=True,
)

# ── 메인: 컴팩트 검색 바 ─────────────────────────────────
_bi1, _bi2, _bi3 = st.columns([5, 3, 1])
with _bi1:
    corp_input = st.text_input(
        "기업명",
        placeholder="기업명 입력 (예: 삼성전자)",
        label_visibility="collapsed",
        key="earn_corp_input",
    )
with _bi2:
    quarter_sel = st.selectbox(
        "분기",
        options=list(_QUARTERS.keys()),
        index=1,
        label_visibility="collapsed",
        key="earn_quarter_sel",
    )
with _bi3:
    analyze_btn = st.button(
        "📊 분석",
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
        search_end = (q_end + timedelta(days=90)).strftime("%Y%m%d")

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
            # 오름차순 정렬 → 선택 분기에 가장 가까운 공시를 우선 선택
            earnings_items.sort(key=lambda x: x.get("rcept_dt", ""))
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

                progress_slot.progress(0.57, text=f"[4/5] {corp_full_name} — 컨센서스 검색 중...")
                _consensus_text = ""
                try:
                    from services.tavily_client import TavilyClient as _TavCli
                    _tav = _TavCli()
                    for _cq in [
                        f"{corp_full_name} {quarter} 영업이익 컨센서스 시장예상",
                        f"{corp_full_name} {quarter} 실적 어닝 서프라이즈 예상치",
                    ]:
                        _cr = _tav.search(_cq, max_results=3)
                        if _cr:
                            _consensus_text = "\n".join(
                                f"제목: {r.get('title','')}\n내용: {r.get('content','')[:400]}"
                                for r in _cr[:3]
                            )
                            break
                except Exception:
                    pass

                progress_slot.progress(0.70, text=f"[5/5] {corp_full_name} — AI 실적 분석 중...")
                analysis = claude.analyze_earnings(
                    corp_full_name, quarter, report_nm, doc_text,
                    consensus_text=_consensus_text,
                )

                progress_slot.progress(0.88, text=f"[6/6] {corp_full_name} — 주가 데이터 수집 중...")
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
    analysis       = r["analysis"]
    corp_full_name = r["corp_name"]
    quarter        = r["quarter"]
    price_df       = r["price_df"]

    surprise        = analysis.get("earnings_surprise", "UNKNOWN")
    surprise_reason = analysis.get("surprise_reason", "")
    key_metrics     = analysis.get("key_metrics", [])
    key_changes     = analysis.get("key_changes", [])
    guidance        = analysis.get("guidance", "정보 없음")
    risks           = analysis.get("risks", [])

    # ── Bloomberg 헤더 ────────────────────────────────────
    _disc_link = ""
    if r["rcept_no"]:
        _du = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"
        _disc_link = (
            f"&nbsp;<a href='{_du}' target='_blank' "
            f"style='color:#7a8fbb;font-size:0.73rem;text-decoration:none'>📋 DART</a>"
        )
    _dt = r["rcept_dt"]
    _dt_fmt = f"{_dt[:4]}.{_dt[4:6]}.{_dt[6:]}" if len(_dt) == 8 else _dt
    _logo_html = get_logo_html(corp_full_name, 28)
    st.markdown(
        f"<div style='background:#1a2744;padding:9px 18px;border-radius:6px;"
        f"margin-bottom:12px;display:flex;align-items:center;justify-content:space-between'>"
        f"<div style='display:flex;align-items:center'>"
        f"<span style='display:inline-flex;align-items:center;margin-right:10px'>{_logo_html}</span>"
        f"<span style='color:#fff;font-size:1.15rem;font-weight:700'>{corp_full_name}</span>"
        f"<span style='color:#8899bb;font-size:0.82rem;margin-left:10px'>{quarter}</span>"
        f"{_disc_link}</div>"
        f"<span style='color:#8899bb;font-size:0.78rem'>{_dt_fmt} 공시</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── 상단 2단: 어닝 서프라이즈(60%) + 주가 반응(40%) ──
    _top_l, _top_r = st.columns([6, 4])

    with _top_l:
        _SURP = {
            "BEAT":    ("#00d084", "BEAT",    "어닝 서프라이즈 — 예상 상회"),
            "MISS":    ("#ff4b4b", "MISS",    "어닝 쇼크 — 예상 하회"),
            "IN_LINE": ("#8899bb", "IN-LINE", "예상치 부합"),
            "UNKNOWN": ("#bbbbbb", "UNKNOWN", "판단 불가"),
        }
        sc, sl, sd = _SURP.get(surprise, ("#bbb", surprise, ""))
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px'>"
            f"<span style='background:{sc};color:white;border-radius:5px;"
            f"padding:5px 18px;font-size:1.05rem;font-weight:700'>{sl}</span>"
            f"<span style='color:#555;font-size:0.88rem'>{sd}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if surprise_reason:
            st.markdown(
                f"<div style='color:#555;font-size:0.82rem;margin-bottom:8px;"
                f"background:#f8f9fc;border-left:3px solid {sc};padding:6px 10px;"
                f"border-radius:0 4px 4px 0'>{surprise_reason}</div>",
                unsafe_allow_html=True,
            )
        if key_metrics:
            _mc = st.columns(4)
            for _i, _m in enumerate(key_metrics[:4]):
                with _mc[_i]:
                    _label = _shorten_metric_label(_m.get("항목", ""))
                    _val   = _fmt_krw(_m.get("값", "—"))
                    _dv    = _m.get("전분기대비", "") or _m.get("전년동기대비", "")
                    _dv    = _dv if (_dv and _dv not in ("해당없음", "N/A")) else ""
                    if _dv:
                        _dc = "#00d084" if "+" in _dv else "#ff4b4b"
                        _dv_html = (
                            f"<div style='color:{_dc};font-size:0.8rem;"
                            f"font-weight:600;margin-top:6px'>{_dv}</div>"
                        )
                    else:
                        _dv_html = ""
                    st.markdown(
                        f"<div style='border:1px solid #e2e5ea;border-left:3px solid #1a2744;"
                        f"border-radius:4px;padding:14px 16px;background:white;height:100%'>"
                        f"<div style='color:#888;font-size:0.68rem;font-weight:500;"
                        f"margin-bottom:8px;line-height:1.4'>{_label}</div>"
                        f"<div style='font-size:1.3rem;font-weight:800;color:#1a2744;"
                        f"line-height:1.2'>{_val}</div>"
                        f"{_dv_html}</div>",
                        unsafe_allow_html=True,
                    )
        else:
            st.caption("수치 데이터 추출 불가")

    with _top_r:
        if not price_df.empty:
            _ev_ts = None
            if "is_event" in price_df.columns:
                _evr = price_df[price_df["is_event"]]
                _ev_ts = _evr.index[0] if not _evr.empty else None
            _fp = go.Figure()
            _fp.add_trace(go.Scatter(
                x=price_df.index, y=price_df["종가"],
                mode="lines+markers", name="종가",
                line=dict(color="#4A90D9", width=2), marker=dict(size=5),
                hovertemplate="%{x|%m/%d}<br>%{y:,}원<extra></extra>",
            ))
            if _ev_ts is not None:
                _xd = str(_ev_ts)[:10]
                _fp.add_shape(type="line", x0=_xd, x1=_xd, y0=0, y1=1,
                              xref="x", yref="paper",
                              line=dict(color="#ff4b4b", width=1.5, dash="dash"))
                _fp.add_annotation(x=_xd, y=0.97, xref="x", yref="paper",
                                   text="발표", showarrow=False, xanchor="left",
                                   font=dict(color="#ff4b4b", size=10))
            _fp.update_layout(
                height=230, margin=dict(t=10, b=25, l=50, r=10),
                xaxis=dict(tickformat="%m/%d", tickfont=dict(size=9)),
                yaxis=dict(tickformat=",", tickfont=dict(size=9), gridcolor="#f0f0f0"),
                plot_bgcolor="white", showlegend=False, hovermode="x unified",
            )
            st.plotly_chart(_fp, use_container_width=True)
            st.caption("※ pykrx(KRX) 데이터 · 투자 판단 근거로 사용 금지")
        else:
            st.info("주가 데이터 없음" if r["stock_code"] else "비상장 종목")

    # ── 서브 탭 ──────────────────────────────────────────
    _st1, _st2, _st3, _st4, _st5 = st.tabs([
        "📊 실적요약", "📈 히스토리", "🏢 경쟁사", "💬 코멘트", "📄 리포트"
    ])

    with _st1:
        _sa_l, _sa_r = st.columns(2)
        with _sa_l:
            with st.container(border=True):
                st.markdown("**📈 전분기 대비 핵심 변화**")
                for _c in key_changes or ["정보 없음"]:
                    st.markdown(f"• {_c}")
            with st.container(border=True):
                st.markdown("**📋 가이던스**")
                st.markdown(guidance or "정보 없음")
        with _sa_r:
            with st.container(border=True):
                st.markdown("**⚠️ 리스크 포인트**")
                for _risk in risks or ["정보 없음"]:
                    st.markdown(f"• {_risk}")

    with _st2:
        with st.spinner("최근 8분기 실적 공시 수집 및 AI 분석 중... (최초 1회, 이후 1시간 캐시)"):
            _history = _fetch_earnings_history(corp_full_name)
        if _history:
            _render_earnings_history_chart(_history, corp_full_name, quarter)
        else:
            st.info("실적 히스토리 데이터를 가져올 수 없습니다.")

    with _st3:
        _peers = _PEER_GROUPS.get(corp_full_name, [])
        if r["stock_code"] and _peers:
            _dart_c, _ = _get_clients()
            _ti_list = [(corp_full_name, r["stock_code"], True)]
            for _p in _peers[:4]:
                _tc = _dart_c.get_stock_code(_p)
                if _tc:
                    _ti_list.append((_p, _tc, False))
            if len(_ti_list) > 1:
                with st.spinner("동종업계 주가 데이터 조회 중..."):
                    _peer_df = _fetch_peer_performance(
                        tuple(_ti_list), date.today().strftime("%Y%m%d")
                    )
                st.session_state["earn_peer_df"] = _peer_df
                _render_peer_comparison(_peer_df, corp_full_name)
            else:
                st.info("동종업계 종목코드를 찾을 수 없습니다.")
        elif not r["stock_code"]:
            st.info("상장 종목이 아니거나 종목코드를 찾을 수 없습니다.")

    with _st4:
        with st.spinner("경영진 발언 검색 중..."):
            _mgmt = _fetch_mgmt_comments(corp_full_name, quarter)
        _render_mgmt_comments(_mgmt)

        _cur_price = (
            float(price_df["종가"].iloc[-1])
            if price_df is not None and not price_df.empty
            else None
        )
        with st.spinner("애널리스트 리포트 검색 중..."):
            _analyst = _fetch_analyst_report(corp_full_name, quarter)
        _render_analyst_report(_analyst, _cur_price)

    with _st5:
        _pc, _ = st.columns([1, 2])
        with _pc:
            try:
                _pdf_bytes = generate_earnings_pdf(
                    r, st.session_state.get("earn_peer_df")
                )
                st.download_button(
                    label="📄 PDF 리포트 다운로드",
                    data=_pdf_bytes,
                    file_name=(
                        f"AI_MarketWatch_{r['corp_name'].replace(' ','_')}"
                        f"_{r['quarter'].replace(' ','_')}"
                        f"_{date.today().strftime('%Y%m%d')}.pdf"
                    ),
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as _e:
                st.warning(f"PDF 생성 실패: {_e}")
        if r["earnings_items"]:
            with st.expander(f"📄 수집된 실적 공시 ({len(r['earnings_items'])}건)", expanded=False):
                for _it in r["earnings_items"]:
                    _url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={_it.get('rcept_no','')}"
                    _mk = "**▶**" if _it.get("rcept_no") == r["rcept_no"] else "   "
                    st.markdown(f"{_mk} [{_it['rcept_dt']}] [{_it['report_nm']}]({_url})")
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
