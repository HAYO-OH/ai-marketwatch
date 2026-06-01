import streamlit as st

_MAX = 10


def init_watchlist() -> None:
    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = []


def render_watchlist_sidebar() -> None:
    """모든 페이지 공통 관심 종목 사이드바 섹션."""
    init_watchlist()
    with st.sidebar:
        st.subheader("⭐ 관심 종목")
        watchlist: list[str] = st.session_state["watchlist"]

        col_in, col_btn = st.columns([4, 1])
        with col_in:
            new_stock = st.text_input(
                "종목 추가",
                placeholder="종목명 입력",
                label_visibility="collapsed",
                key="wl_new_input",
            )
        with col_btn:
            st.markdown("<div style='margin-top:4px'>", unsafe_allow_html=True)
            add_clicked = st.button("＋", key="wl_add_btn", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        if add_clicked:
            name = new_stock.strip()
            if not name:
                st.toast("종목명을 입력하세요.")
            elif name in watchlist:
                st.toast(f"'{name}'은(는) 이미 추가되어 있습니다.")
            elif len(watchlist) >= _MAX:
                st.toast(f"최대 {_MAX}개까지 추가 가능합니다.")
            else:
                st.session_state["watchlist"].append(name)
                st.rerun()

        if not watchlist:
            st.caption("아직 추가된 종목이 없습니다.")
        else:
            for i, stock in enumerate(list(watchlist)):
                c_name, c_del = st.columns([4, 1])
                with c_name:
                    st.markdown(
                        f"<div style='padding:2px 0;font-size:0.88rem'>{stock}</div>",
                        unsafe_allow_html=True,
                    )
                with c_del:
                    if st.button("✕", key=f"wl_del_{i}", use_container_width=True):
                        st.session_state["watchlist"].pop(i)
                        st.rerun()

        st.divider()
