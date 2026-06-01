import streamlit as st
from streamlit_option_menu import option_menu

_PAGES = [
    ("🏠 홈",         "app.py",                    "house"),
    ("📋 공시모니터링", "pages/1_DART공시모니터링.py", "clipboard-data"),
    ("📊 실적발표",    "pages/2_실적발표요약.py",     "bar-chart-line"),
    ("💼 포트폴리오",  "pages/3_포트폴리오리스크.py", "briefcase"),
]
_LABELS = [p[0] for p in _PAGES]
_PATHS  = [p[1] for p in _PAGES]
_ICONS  = [p[2] for p in _PAGES]


def render_top_nav(current: str) -> None:
    """상단 가로 네비게이션. current = 현재 페이지 경로 문자열."""
    # 사이드바 자동 페이지 링크 숨김 (watchlist 등 직접 추가한 요소는 유지)
    st.markdown(
        "<style>[data-testid='stSidebarNav']{display:none!important}</style>",
        unsafe_allow_html=True,
    )
    default = _PATHS.index(current) if current in _PATHS else 0
    selected = option_menu(
        menu_title=None,
        options=_LABELS,
        icons=_ICONS,
        default_index=default,
        orientation="horizontal",
        styles={
            "container": {
                "padding": "0!important",
                "margin-bottom": "8px",
                "background-color": "#ffffff",
                "border-bottom": "2px solid #f0f2f6",
            },
            "icon": {"font-size": "15px"},
            "nav-link": {
                "font-size": "14px",
                "text-align": "center",
                "padding": "10px 20px",
                "--hover-color": "#fff5f5",
            },
            "nav-link-selected": {
                "background-color": "#FF4B4B",
                "color": "white",
                "font-weight": "600",
            },
        },
    )
    idx = _LABELS.index(selected)
    if idx != default:
        st.switch_page(_PATHS[idx])
