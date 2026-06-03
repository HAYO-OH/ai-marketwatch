import re
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.claude_client import ClaudeClient
from services.dart_client import DartClient
from utils.nav import render_top_nav
from utils.watchlist import render_watchlist_sidebar

st.set_page_config(page_title="포트폴리오 리스크", layout="wide")

# ── 섹터 매핑 ────────────────────────────────────────────
_SECTOR_MAP: dict[str, str] = {
    "삼성전자": "반도체", "SK하이닉스": "반도체",
    "LG에너지솔루션": "2차전지", "삼성SDI": "2차전지",
    "SK이노베이션": "화학", "LG화학": "화학", "롯데케미칼": "화학",
    "현대자동차": "자동차", "기아": "자동차", "현대모비스": "자동차",
    "NAVER": "인터넷", "카카오": "인터넷",
    "카카오페이": "핀테크", "카카오뱅크": "금융",
    "KB금융": "금융", "신한지주": "금융",
    "하나금융지주": "금융", "우리금융지주": "금융",
    "삼성바이오로직스": "바이오", "셀트리온": "바이오", "한미약품": "바이오",
    "POSCO홀딩스": "철강", "현대제철": "철강",
    "HD현대": "조선", "한화에어로스페이스": "방산",
    "크래프톤": "게임", "엔씨소프트": "게임", "넷마블": "게임",
    "아모레퍼시픽": "소비재", "LG생활건강": "소비재",
    "LG전자": "전자", "LG디스플레이": "전자",
    "삼성물산": "건설", "현대건설": "건설",
    "SK텔레콤": "통신", "LG유플러스": "통신",
}
_SECTOR_COLORS = [
    "#1a2744", "#2d4f8e", "#4a90d9", "#7ab4e8", "#b0c4de",
    "#00d084", "#22a355", "#f0a500", "#ff8c00", "#ff4b4b",
    "#8899bb", "#e8a0bf",
]


@st.cache_resource
def _get_clients():
    return DartClient(), ClaudeClient()


def parse_portfolio(raw: str) -> list[dict]:
    """Format: 종목명 수량 [매입가]  (공백 구분, 1줄 1종목)"""
    items = []
    for line in raw.strip().splitlines():
        line = re.sub(r"[,원주￦]", "", line).strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0]
        try:
            qty = int(parts[1])
        except ValueError:
            continue
        buy_price = None
        if len(parts) >= 3:
            try:
                buy_price = float(parts[2].replace(",", ""))
            except ValueError:
                pass
        items.append({"name": name, "qty": qty, "buy_price": buy_price})
    return items


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_prices(nt_tuple: tuple) -> dict[str, float]:
    """((name, ticker), ...) → {ticker: 현재가}"""
    from pykrx import stock as krx
    today = date.today()
    start = (today - timedelta(days=7)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")
    prices = {}
    for _, ticker in nt_tuple:
        if not ticker:
            continue
        try:
            df = krx.get_market_ohlcv_by_date(start, end, ticker)
            if not df.empty:
                prices[ticker] = float(df["종가"].iloc[-1])
        except Exception:
            pass
    return prices


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_history(nt_tuple: tuple, days: int = 60) -> dict[str, pd.DataFrame]:
    """((name, ticker), ...) → {ticker: DataFrame[종가]}"""
    from pykrx import stock as krx
    today = date.today()
    start = (today - timedelta(days=days + 10)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")
    hist = {}
    for _, ticker in nt_tuple:
        if not ticker:
            continue
        try:
            df = krx.get_market_ohlcv_by_date(start, end, ticker)
            if not df.empty and len(df) >= 5:
                hist[ticker] = df[["종가"]]
        except Exception:
            pass
    return hist


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_beta(nt_tuple: tuple, days: int = 60) -> dict[str, float | None]:
    """KODEX 200(069500) 대비 베타 계수 계산."""
    from pykrx import stock as krx
    today = date.today()
    start = (today - timedelta(days=days + 10)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")
    try:
        mkt_df = krx.get_market_ohlcv_by_date(start, end, "069500")
        if mkt_df.empty:
            return {}
        mkt_ret = mkt_df["종가"].pct_change().dropna()
    except Exception:
        return {}
    betas: dict[str, float | None] = {}
    for _, ticker in nt_tuple:
        if not ticker:
            continue
        try:
            df = krx.get_market_ohlcv_by_date(start, end, ticker)
            if df.empty or len(df) < 10:
                continue
            stk_ret = df["종가"].pct_change().dropna()
            common_idx = mkt_ret.index.intersection(stk_ret.index)
            if len(common_idx) < 10:
                continue
            m = mkt_ret.loc[common_idx]
            s = stk_ret.loc[common_idx]
            cov = float(s.cov(m))
            var = float(m.var())
            betas[ticker] = round(cov / var, 2) if var != 0 else None
        except Exception:
            pass
    return betas


def _build_df(items: list[dict], tickers: dict, prices: dict):
    rows = []
    total_val = 0.0
    for it in items:
        ticker = tickers.get(it["name"])
        cur  = prices.get(ticker) if ticker else None
        buy  = it["buy_price"]
        qty  = it["qty"]
        cost = (buy * qty) if buy else None
        cur_val = (cur * qty) if cur else None
        pnl  = (cur_val - cost) if (cur_val and cost) else None
        ret  = ((cur - buy) / buy * 100) if (cur and buy and buy > 0) else None
        if cur_val:
            total_val += cur_val
        rows.append({
            "종목명":  it["name"],
            "ticker":  ticker or "",
            "수량":    qty,
            "매입가":  buy,
            "현재가":  cur,
            "평가액":  cur_val,
            "손익":    pnl,
            "수익률":  ret,
            "섹터":    _SECTOR_MAP.get(it["name"], "기타"),
        })
    df = pd.DataFrame(rows)
    if total_val > 0:
        df["비중"] = df["평가액"].apply(
            lambda v: round(v / total_val * 100, 1) if v else None
        )
    else:
        df["비중"] = None
    return df, total_val


# ── 사이드바 + 네비게이션 ────────────────────────────────
render_watchlist_sidebar()
render_top_nav("pages/3_포트폴리오리스크.py")

with st.sidebar:
    _wl = st.session_state.get("watchlist", [])
    if _wl:
        st.subheader("관심 종목 불러오기")
        if st.button("포트폴리오에 추가", use_container_width=True):
            st.session_state["portfolio_raw_input"] = "\n".join(
                f"{s} 0 0" for s in _wl
            )
            st.rerun()
        st.divider()

# ── 전역 CSS ────────────────────────────────────────────
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

# ── Bloomberg 헤더 ────────────────────────────────────────
st.markdown(
    "<div style='background:#1a2744;padding:9px 18px;border-radius:6px;"
    "margin-bottom:14px;display:flex;align-items:center;justify-content:space-between'>"
    "<div><span style='color:#fff;font-size:1.2rem;font-weight:700'>포트폴리오 리스크</span>"
    "<span style='color:#7a8fbb;font-size:0.8rem;margin-left:12px'>"
    "수익률 · 리스크 분석 · 리밸런싱 제안</span></div>"
    f"<span style='color:#7a8fbb;font-size:0.78rem'>{date.today().strftime('%Y.%m.%d')}</span>"
    "</div>",
    unsafe_allow_html=True,
)

# ── 입력 폼 ──────────────────────────────────────────────
_DEFAULT = "삼성전자 100 55000\nSK하이닉스 50 130000\n현대자동차 30 220000\nNAVER 20 180000"
if "portfolio_raw_input" not in st.session_state:
    st.session_state["portfolio_raw_input"] = _DEFAULT

_, _fc, _ = st.columns([1, 2, 1])
with _fc:
    st.caption("종목명 수량 매입가  (1줄에 1종목 · 매입가 생략 가능)")
    raw_input = st.text_area(
        "포트폴리오",
        height=110,
        label_visibility="collapsed",
        placeholder="삼성전자 100 55000\nSK하이닉스 50 130000",
        key="portfolio_raw_input",
    )
    analyze_btn = st.button("📊 포트폴리오 분석", type="primary", use_container_width=True)

if not analyze_btn and "port_result" not in st.session_state:
    st.stop()

# ── 분석 실행 ─────────────────────────────────────────────
if analyze_btn:
    _items = parse_portfolio(raw_input)
    if not _items:
        st.error("올바른 형식으로 입력하세요. 예: 삼성전자 100 55000")
        st.stop()
    dart, _ = _get_clients()
    _prog = st.progress(0, "종목 코드 조회 중...")
    _tickers: dict[str, str | None] = {}
    for _i, _it in enumerate(_items):
        _tickers[_it["name"]] = dart.get_stock_code(_it["name"])
        _prog.progress((_i + 1) / len(_items), f"{_it['name']} 완료")
    _prog.empty()
    st.session_state["port_result"] = {"items": _items, "tickers": _tickers}

if "port_result" not in st.session_state:
    st.stop()

_port    = st.session_state["port_result"]
_items   = _port["items"]
_tickers = _port["tickers"]
_nt      = tuple((it["name"], _tickers.get(it["name"]) or "") for it in _items)

with st.spinner("현재가 조회 중..."):
    _prices = _fetch_prices(_nt)

_df, _total_val = _build_df(_items, _tickers, _prices)
_total_cost = sum((it["buy_price"] or 0) * it["qty"] for it in _items)
_total_pnl  = (_total_val - _total_cost) if _total_val and _total_cost else None
_total_ret  = (_total_pnl / _total_cost * 100) if _total_pnl and _total_cost else None


# ── 상단 메트릭 카드 ──────────────────────────────────────
def _mcard(label: str, value: str, color: str = "#1a2744", detail: str = "") -> str:
    dh = f"<div style='color:#999;font-size:0.69rem;margin-top:2px'>{detail}</div>" if detail else ""
    return (
        f"<div style='background:white;border:1px solid #e3e8f0;border-left:3px solid #1a2744;"
        f"border-radius:4px;padding:8px 14px'>"
        f"<div style='color:#7a8599;font-size:0.67rem;text-transform:uppercase;"
        f"letter-spacing:0.5px;margin-bottom:4px'>{label}</div>"
        f"<div style='color:{color};font-size:1.35rem;font-weight:700;line-height:1.1'>{value}</div>"
        f"{dh}</div>"
    )

_m1, _m2, _m3, _m4 = st.columns(4)
with _m1:
    _v = f"₩{_total_val:,.0f}" if _total_val else "—"
    st.markdown(_mcard("총 평가액", _v), unsafe_allow_html=True)
with _m2:
    if _total_pnl is not None:
        _c = "#00d084" if _total_pnl >= 0 else "#ff4b4b"
        _v = f"{'+'if _total_pnl>=0 else ''}₩{_total_pnl:,.0f}"
    else:
        _c, _v = "#888", "—"
    st.markdown(_mcard("총 손익", _v, _c), unsafe_allow_html=True)
with _m3:
    if _total_ret is not None:
        _c = "#00d084" if _total_ret >= 0 else "#ff4b4b"
        _v = f"{'+'if _total_ret>=0 else ''}{_total_ret:.2f}%"
    else:
        _c, _v = "#888", "—"
    st.markdown(_mcard("수익률", _v, _c), unsafe_allow_html=True)
with _m4:
    st.markdown(
        _mcard("종목 수", f"{len(_items)}개", detail=f"{date.today().strftime('%Y.%m.%d')} 기준"),
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# ── 서브 탭 ───────────────────────────────────────────────
_t1, _t2, _t3 = st.tabs(["📈 수익률", "⚠️ 리스크", "🔄 리밸런싱 제안"])

# ──────────────────────────────────────────────────────────
with _t1:
    _tl, _tr = st.columns([6, 4])

    with _tl:
        st.markdown(
            "<div style='background:#1a2744;color:white;padding:5px 12px;"
            "border-radius:4px 4px 0 0;font-size:0.79rem;font-weight:600'>"
            "종목별 수익률</div>",
            unsafe_allow_html=True,
        )
        for _, _row in _df.iterrows():
            _ret = _row.get("수익률")
            _rc  = "#00d084" if (_ret and _ret >= 0) else ("#ff4b4b" if _ret else "#888")
            _ret_s = f"{'+'if _ret and _ret>=0 else ''}{_ret:.1f}%" if _ret else "—"
            _pnl_s = (
                f"{'+'if (_row.get('손익') or 0)>=0 else ''}₩{(_row.get('손익') or 0):,.0f}"
                if _row.get("손익") else "—"
            )
            _cur_s = f"₩{_row.get('현재가',0):,}" if _row.get("현재가") else "—"
            _w_s   = f"{_row.get('비중','—')}%" if _row.get("비중") is not None else "—"
            _badge = ""
            if _ret and _ret > 5:
                _badge = "<span style='background:#00d084;color:white;border-radius:3px;padding:1px 5px;font-size:0.68rem;font-weight:700'>BEAT</span>"
            elif _ret and _ret < -5:
                _badge = "<span style='background:#ff4b4b;color:white;border-radius:3px;padding:1px 5px;font-size:0.68rem;font-weight:700'>MISS</span>"
            st.markdown(
                f"<div style='display:flex;align-items:center;padding:6px 4px;"
                f"border-bottom:1px solid #f0f2f6;gap:6px;font-size:0.83rem'>"
                f"<span style='font-weight:600;color:#1a2744;min-width:80px'>{_row['종목명']}</span>"
                f"<span style='color:#888;min-width:70px'>{_cur_s}</span>"
                f"<span style='color:{_rc};font-weight:700;min-width:60px'>{_ret_s}</span>"
                f"<span style='color:#aaa;min-width:40px;font-size:0.78rem'>{_w_s}</span>"
                f"{_badge}"
                f"<span style='color:#ccc;font-size:0.75rem;margin-left:auto'>{_pnl_s}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    with _tr:
        _sec_df = (
            _df[_df["비중"].notna()]
            .groupby("섹터")["비중"]
            .sum()
            .reset_index()
        )
        if not _sec_df.empty:
            _fig_pie = go.Figure(go.Pie(
                labels=_sec_df["섹터"],
                values=_sec_df["비중"],
                marker_colors=_SECTOR_COLORS[:len(_sec_df)],
                textinfo="label+percent",
                textfont_size=11,
                hole=0.35,
            ))
            _fig_pie.update_layout(
                title=dict(text="섹터 비중", font_size=13),
                showlegend=False,
                height=320,
                margin=dict(t=40, b=10, l=10, r=10),
            )
            st.plotly_chart(_fig_pie, use_container_width=True)
        else:
            st.info("현재가 조회 후 섹터 차트를 표시합니다.")

# ──────────────────────────────────────────────────────────
with _t2:
    with st.spinner("60일 가격 데이터 수집 중..."):
        _hist  = _fetch_history(_nt, days=60)
        _betas = _fetch_beta(_nt)

    _risk_rows = []
    _sector_cnt: dict[str, int] = {}
    for _it in _items:
        _tk = _tickers.get(_it["name"])
        _vol = None
        if _tk and _tk in _hist:
            _closes = _hist[_tk]["종가"]
            if len(_closes) >= 10:
                _dr = _closes.pct_change().dropna()
                _vol = round(float(_dr.std() * (252 ** 0.5) * 100), 1)
        _sec = _SECTOR_MAP.get(_it["name"], "기타")
        _sector_cnt[_sec] = _sector_cnt.get(_sec, 0) + 1
        _beta_val = _betas.get(_tk) if _tk else None
        _risk_rows.append({
            "종목명":     _it["name"],
            "섹터":       _sec,
            "연간변동성": f"{_vol:.1f}%" if _vol else "—",
            "베타":       str(_beta_val) if _beta_val is not None else "—",
        })
    _risk_df = pd.DataFrame(_risk_rows)

    # ── ① 변동성 ──────────────────────────────────────────
    st.markdown(
        "<div style='background:#1a2744;color:white;padding:5px 12px;"
        "border-radius:4px 4px 0 0;font-size:0.79rem;font-weight:600'>"
        "📊 변동성 (연간)</div>",
        unsafe_allow_html=True,
    )
    _vol_rows_html = ""
    for _, _rr in _risk_df.iterrows():
        try:
            _vf = float(_rr["연간변동성"].replace("%", ""))
            _vc = "#ff4b4b" if _vf >= 40 else ("#f0a500" if _vf >= 25 else "#00d084")
        except (ValueError, AttributeError):
            _vc = "#888"
        _vol_rows_html += (
            f"<div style='display:flex;align-items:center;padding:5px 10px;"
            f"border-bottom:1px solid #f0f2f6;gap:6px;font-size:0.83rem'>"
            f"<span style='font-weight:600;color:#1a2744;min-width:90px'>{_rr['종목명']}</span>"
            f"<span style='color:#888;min-width:70px;font-size:0.78rem'>{_rr['섹터']}</span>"
            f"<span style='color:{_vc};font-weight:700;margin-left:auto'>{_rr['연간변동성']}</span>"
            f"</div>"
        )
    st.markdown(
        f"<div style='border:1px solid #e2e5ea;border-top:none;border-radius:0 0 4px 4px;"
        f"background:white;margin-bottom:12px'>{_vol_rows_html}</div>",
        unsafe_allow_html=True,
    )

    # 상대 수익률 차트
    _rel_data: dict[str, pd.Series] = {}
    for _it in _items:
        _tk = _tickers.get(_it["name"])
        if _tk and _tk in _hist:
            _cl = _hist[_tk]["종가"]
            if len(_cl) >= 5:
                _rel_data[_it["name"]] = _cl / _cl.iloc[0] * 100
    if _rel_data:
        _fig_rel = go.Figure()
        for _nm, _ser in _rel_data.items():
            _fig_rel.add_trace(go.Scatter(
                x=_ser.index, y=_ser.values,
                name=_nm, mode="lines",
                line=dict(width=1.8),
            ))
        _fig_rel.add_hline(y=100, line_dash="dash", line_color="#ccc", opacity=0.6)
        _fig_rel.update_layout(
            title="종목별 상대 수익률 (기준일 = 100)",
            hovermode="x unified", height=240,
            margin=dict(t=36, b=24, l=46, r=16),
            plot_bgcolor="white",
            yaxis=dict(gridcolor="#f0f0f0"),
        )
        st.plotly_chart(_fig_rel, use_container_width=True)

    _rc1, _rc2 = st.columns(2)

    # ── ② 섹터 집중도 ────────────────────────────────────
    with _rc1:
        st.markdown(
            "<div style='background:#1a2744;color:white;padding:5px 12px;"
            "border-radius:4px 4px 0 0;font-size:0.79rem;font-weight:600'>"
            "🏢 섹터 집중도</div>",
            unsafe_allow_html=True,
        )
        _sec_rows_html = ""
        for _s, _cnt in sorted(_sector_cnt.items(), key=lambda x: -x[1]):
            _sec_pct = _cnt / max(len(_items), 1) * 100
            _bar_c = "#ff4b4b" if _sec_pct >= 50 else ("#f0a500" if _sec_pct >= 30 else "#1a2744")
            _sec_rows_html += (
                f"<div style='padding:6px 10px;border-bottom:1px solid #f0f2f6'>"
                f"<div style='display:flex;align-items:center;justify-content:space-between;"
                f"font-size:0.82rem;margin-bottom:4px'>"
                f"<span style='color:#1a2744;font-weight:600'>{_s}</span>"
                f"<span style='color:{_bar_c};font-weight:700'>"
                f"{_cnt}종목 ({_sec_pct:.0f}%)</span></div>"
                f"<div style='background:#f0f2f6;border-radius:3px;height:4px'>"
                f"<div style='background:{_bar_c};width:{min(_sec_pct,100):.0f}%;"
                f"height:100%;border-radius:3px'></div></div></div>"
            )
        st.markdown(
            f"<div style='border:1px solid #e2e5ea;border-top:none;border-radius:0 0 4px 4px;"
            f"background:white'>{_sec_rows_html}</div>",
            unsafe_allow_html=True,
        )
        for _s, _cnt in _sector_cnt.items():
            if _cnt >= 3:
                st.warning(f"⚠️ **{_s}** 섹터 집중 — 분산 투자 권장")

    # ── ③ 베타 계수 ──────────────────────────────────────
    with _rc2:
        st.markdown(
            "<div style='background:#1a2744;color:white;padding:5px 12px;"
            "border-radius:4px 4px 0 0;font-size:0.79rem;font-weight:600'>"
            "📐 베타 계수"
            "<span style='font-size:0.67rem;font-weight:400;color:#7a8fbb;margin-left:6px'>"
            "vs KODEX 200</span></div>",
            unsafe_allow_html=True,
        )
        _beta_rows_html = ""
        for _, _rr in _risk_df.iterrows():
            try:
                _bv = float(_rr["베타"])
                _bc = "#ff4b4b" if _bv >= 1.5 else ("#f0a500" if _bv >= 1.0 else "#00d084")
                _bl = "고위험" if _bv >= 1.5 else ("시장연동" if _bv >= 0.9 else "저위험")
            except (ValueError, AttributeError):
                _bc, _bl = "#888", ""
            _beta_rows_html += (
                f"<div style='display:flex;align-items:center;padding:6px 10px;"
                f"border-bottom:1px solid #f0f2f6;gap:6px;font-size:0.83rem'>"
                f"<span style='font-weight:600;color:#1a2744;min-width:80px'>{_rr['종목명']}</span>"
                f"<span style='color:{_bc};font-weight:700;margin-left:auto'>{_rr['베타']}</span>"
                f"<span style='color:{_bc};font-size:0.71rem;background:{_bc}22;"
                f"border-radius:3px;padding:1px 6px;min-width:46px;text-align:center'>{_bl}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='border:1px solid #e2e5ea;border-top:none;border-radius:0 0 4px 4px;"
            f"background:white'>{_beta_rows_html}</div>",
            unsafe_allow_html=True,
        )
        if _betas:
            st.caption("베타 < 1.0: 저위험 · 1.0~1.5: 시장연동 · > 1.5: 고위험")
        else:
            st.info("가격 데이터 부족으로 베타 계수를 계산하지 못했습니다.")

# ──────────────────────────────────────────────────────────
with _t3:
    st.markdown(
        "<div style='background:#1a2744;color:white;padding:5px 12px;"
        "border-radius:4px 4px 0 0;font-size:0.79rem;font-weight:600'>"
        "AI 리밸런싱 제안</div>",
        unsafe_allow_html=True,
    )

    if st.button("🤖 AI 리밸런싱 분석 실행", type="primary"):
        _, _claude = _get_clients()
        _port_data = [
            {
                "name":       _row["종목명"],
                "sector":     _row["섹터"],
                "weight":     _row.get("비중"),
                "return_pct": _row.get("수익률"),
                "cur_price":  _row.get("현재가"),
            }
            for _, _row in _df.iterrows()
        ]
        with st.spinner("Claude AI가 포트폴리오를 분석하는 중..."):
            _rb_result = _claude.analyze_portfolio_rebalancing(_port_data, _sector_cnt)
        st.session_state["rebal_result"] = _rb_result

    if "rebal_result" in st.session_state:
        _rb = st.session_state["rebal_result"]
        _rl = _rb.get("risk_level", "보통")
        _rl_c = {"낮음": "#00d084", "보통": "#f0a500", "높음": "#ff4b4b"}.get(_rl, "#888")
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;margin:10px 0'>"
            f"<span style='background:{_rl_c};color:white;border-radius:4px;"
            f"padding:3px 12px;font-size:0.82rem;font-weight:700'>리스크 {_rl}</span>"
            f"<span style='font-size:0.87rem;color:#555'>{_rb.get('overall_assessment','')}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if _rb.get("key_risk"):
            st.markdown(
                f"<div style='background:#fff3cd;border:1px solid #ffc107;border-radius:4px;"
                f"padding:8px 12px;margin-bottom:10px;font-size:0.85rem'>"
                f"⚠️ {_rb['key_risk']}</div>",
                unsafe_allow_html=True,
            )
        for _sg in _rb.get("suggestions", []):
            _ac = _sg.get("action", "유지")
            _ac_c = {"매수": "#00d084", "매도": "#ff4b4b", "유지": "#8899bb"}.get(_ac, "#888")
            _tw = _sg.get("target_weight")
            _tw_s = f"→ 목표 {_tw:.0f}%" if _tw else ""
            st.markdown(
                f"<div style='display:flex;align-items:center;padding:5px 4px;"
                f"border-bottom:1px solid #f0f2f6;gap:8px;font-size:0.84rem'>"
                f"<span style='background:{_ac_c};color:white;border-radius:3px;"
                f"padding:1px 8px;font-size:0.75rem;font-weight:700;min-width:36px;"
                f"text-align:center'>{_ac}</span>"
                f"<span style='font-weight:600;color:#1a2744;min-width:70px'>"
                f"{_sg.get('name','')}</span>"
                f"<span style='color:#666'>{_sg.get('reason','')}</span>"
                f"<span style='color:#aaa;margin-left:auto;font-size:0.79rem'>{_tw_s}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        if _rb.get("sector_comment"):
            st.caption(f"섹터 균형: {_rb['sector_comment']}")
    else:
        st.info(
            "버튼을 클릭하면 Claude AI가 종목별 조정 제안을 제공합니다.\n\n"
            "분석 기준: 수익률 흐름 · 섹터 집중도 · 비중 균형"
        )
