import glob
import os
from datetime import date

import pandas as pd
from fpdf import FPDF

_NAVY   = (22, 43, 80)
_RED    = (220, 50, 50)
_GREEN  = (34, 163, 85)
_GRAY   = (120, 120, 120)
_LIGHT  = (248, 249, 250)
_BORDER = (224, 224, 224)


def _find_korean_font() -> str | None:
    candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NotoSansKR-VF.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    kr_kw = ["malgun", "nanum", "noto", "gungsuh", "gulim"]
    for p in glob.glob("C:/Windows/Fonts/*.ttf") + glob.glob("C:/Windows/Fonts/*.TTF"):
        if any(k in os.path.basename(p).lower() for k in kr_kw) and p not in candidates:
            candidates.append(p)
    return next((p for p in candidates if os.path.isfile(p)), None)


def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(4)
    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("KR", "B", 10)
    pdf.cell(0, 8, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(2)


_UNSAFE: dict = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "◄": "<",  # ◄
    "▶": ">",  # ▶
    "◆": "*",  # ◆
    "•": "*",  # •
    "‘": "'", "’": "'",
    "“": '"',  "”": '"',
}


def _s(text: str) -> str:
    """cp949-safe: 인코딩 불가 유니코드 문자를 ASCII로 대체."""
    for ch, rep in _UNSAFE.items():
        text = text.replace(ch, rep)
    return text


def _fmt_ret(v) -> str:
    if v is None:
        return "N/A"
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"


def generate_earnings_pdf(r: dict, peer_df: pd.DataFrame | None = None) -> bytes:
    """earnings_result dict → PDF bytes. 실패 시 RuntimeError."""
    font_path = _find_korean_font()
    if font_path is None:
        raise RuntimeError("한글 폰트를 시스템에서 찾을 수 없습니다.")

    analysis       = r.get("analysis", {})
    corp_name      = r.get("corp_name", "")
    quarter        = r.get("quarter", "")
    rcept_dt       = r.get("rcept_dt", "")
    report_nm      = r.get("report_nm", "")
    rcept_no       = r.get("rcept_no", "")
    price_df       = r.get("price_df")

    surprise        = analysis.get("earnings_surprise", "UNKNOWN")
    surprise_reason = analysis.get("surprise_reason", "")
    key_metrics     = analysis.get("key_metrics", [])
    key_changes     = analysis.get("key_changes", [])
    guidance        = analysis.get("guidance", "")
    risks           = analysis.get("risks", [])

    today_str = date.today().strftime("%Y.%m.%d")

    pdf = FPDF("P", "mm", "A4")
    pdf.set_margins(20, 15, 20)
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_font("KR", "",  font_path)
    pdf.add_font("KR", "B", font_path)
    pdf.add_page()

    # ── 1. 헤더 배너 ─────────────────────────────────────
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 0, 210, 30, "F")
    pdf.set_xy(20, 7)
    pdf.set_font("KR", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, "AI MarketWatch", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(20)
    pdf.set_font("KR", "", 9)
    pdf.set_text_color(190, 205, 225)
    pdf.cell(0, 6,
        f"실적 분석 리포트  |  {corp_name} {quarter}  |  작성일: {today_str}",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(30, 30, 30)
    pdf.set_y(38)

    # ── 2. Executive Summary ──────────────────────────────
    _section(pdf, "EXECUTIVE SUMMARY")

    _SURP: dict = {
        "BEAT":    (_GREEN,            "BEAT  어닝 서프라이즈 (예상 상회)"),
        "MISS":    (_RED,              "MISS  어닝 쇼크 (예상 하회)"),
        "IN_LINE": ((100, 100, 100),   "IN-LINE  예상치 부합"),
        "UNKNOWN": ((150, 150, 150),   "UNKNOWN  판단 불가"),
    }
    surp_color, surp_label = _SURP.get(surprise, ((150, 150, 150), surprise))
    pdf.set_fill_color(*surp_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("KR", "B", 11)
    pdf.cell(0, 10, f"  {surp_label}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(4)

    # 핵심 수치 카드 (최대 3개)
    cards = key_metrics[:3]
    if cards:
        cw     = 170 / len(cards)
        y0     = pdf.get_y()
        for i, m in enumerate(cards):
            x = 20 + i * cw
            pdf.set_draw_color(*_BORDER)
            pdf.set_fill_color(*_LIGHT)
            pdf.rect(x, y0, cw - 2, 24, "FD")
            # 항목명
            pdf.set_xy(x + 3, y0 + 3)
            pdf.set_font("KR", "", 8)
            pdf.set_text_color(*_GRAY)
            pdf.cell(cw - 6, 5, m.get("항목", ""))
            # 수치
            pdf.set_xy(x + 3, y0 + 9)
            pdf.set_font("KR", "B", 12)
            pdf.set_text_color(*_NAVY)
            pdf.cell(cw - 6, 8, _s(m.get("값", "-")))
            # 델타
            delta = m.get("전분기대비", "")
            if delta and delta not in ("해당없음", ""):
                pdf.set_xy(x + 3, y0 + 18)
                pdf.set_font("KR", "", 8)
                pdf.set_text_color(*(_GREEN if "+" in delta else _RED))
                pdf.cell(cw - 6, 4, _s(delta))
        pdf.set_y(y0 + 28)
        pdf.set_text_color(30, 30, 30)

    # 투자 포인트
    if surprise_reason:
        inv_pt = surprise_reason.split(". ")[0].rstrip(".") + "."
        if len(inv_pt) > 120:
            inv_pt = inv_pt[:120] + "..."
        pdf.set_font("KR", "B", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(25, 6, "투자 포인트", new_x="END", new_y="TOP")
        pdf.set_font("KR", "", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(145, 6, _s(inv_pt))
    pdf.ln(2)

    # ── 3. 실적 분석 ──────────────────────────────────────
    _section(pdf, "실적 분석")

    pdf.set_font("KR", "", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 5, f"기준 공시: [{rcept_dt}] {report_nm}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.ln(2)

    if key_metrics:
        col_w   = [55, 45, 40, 30]
        headers = ["항목", "값", "전분기대비", "비고"]
        pdf.set_fill_color(*_NAVY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("KR", "B", 8.5)
        for w, h in zip(col_w, headers):
            pdf.cell(w, 7, f"  {h}", fill=True, border=1)
        pdf.ln()
        pdf.set_font("KR", "", 8.5)
        for seq, m in enumerate(key_metrics):
            pdf.set_fill_color(*(_LIGHT if seq % 2 == 0 else (255, 255, 255)))
            pdf.set_text_color(30, 30, 30)
            delta = m.get("전분기대비", "")
            note  = m.get("비고", "")
            row_vals = [
                _s(m.get("항목", "")),
                _s(m.get("값", "-")),
                _s(delta) if delta and delta != "해당없음" else "-",
                _s(note[:14]) if note else "-",
            ]
            for w, v in zip(col_w, row_vals):
                pdf.cell(w, 7, f"  {v}", fill=True, border=1)
            pdf.ln()
        pdf.ln(3)

    if key_changes:
        pdf.set_font("KR", "B", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(0, 6, "전분기 대비 핵심 변화", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("KR", "", 9)
        pdf.set_text_color(30, 30, 30)
        for ch in key_changes[:3]:
            pdf.set_x(24)
            pdf.multi_cell(166, 5.5, _s(f"* {ch}"))
        pdf.ln(2)

    if surprise_reason:
        pdf.set_font("KR", "B", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(0, 6, "어닝 서프라이즈 배경", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("KR", "", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.set_x(24)
        pdf.multi_cell(166, 5.5, _s(surprise_reason))
    pdf.ln(2)

    # ── 4. 리스크 분석 ────────────────────────────────────
    _section(pdf, "리스크 분석")

    if risks:
        pdf.set_font("KR", "B", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(0, 6, "리스크 포인트", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("KR", "", 9)
        pdf.set_text_color(30, 30, 30)
        for risk in risks[:3]:
            pdf.set_x(24)
            pdf.multi_cell(166, 5.5, _s(f"* {risk}"))
        pdf.ln(2)

    if guidance:
        pdf.set_font("KR", "B", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(0, 6, "가이던스", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("KR", "", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.set_x(24)
        pdf.multi_cell(166, 5.5, _s(guidance))
    pdf.ln(2)

    # ── 5. 동종업계 비교 ──────────────────────────────────
    if peer_df is not None and not peer_df.empty:
        _section(pdf, "동종업계 비교")
        col_w = [55, 35, 30, 30, 20]
        hdrs  = ["종목명", "현재가", "1M 수익률", "3M 수익률", "현재"]
        pdf.set_fill_color(*_NAVY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("KR", "B", 8.5)
        for w, h in zip(col_w, hdrs):
            pdf.cell(w, 7, f"  {h}", fill=True, border=1)
        pdf.ln()
        pdf.set_font("KR", "", 8.5)
        for seq, (_, row_data) in enumerate(peer_df.iterrows()):
            is_cur = bool(row_data.get("is_current", False))
            row_bg = (235, 245, 255) if is_cur else (_LIGHT if seq % 2 == 0 else (255, 255, 255))
            pdf.set_fill_color(*row_bg)
            pdf.set_text_color(30, 30, 30)
            cur = row_data.get("현재가")
            vals = [
                str(row_data.get("종목명", "")),
                f"{int(cur):,}원" if cur else "N/A",
                _fmt_ret(row_data.get("1M수익률")),
                _fmt_ret(row_data.get("3M수익률")),
                "[현재]" if is_cur else "",
            ]
            for w, v in zip(col_w, vals):
                pdf.cell(w, 7, f"  {v}", fill=True, border=1)
            pdf.ln()
        pdf.set_text_color(30, 30, 30)
        pdf.ln(3)

    # ── 6. 주가 반응 ──────────────────────────────────────
    if price_df is not None and not price_df.empty:
        _section(pdf, "주가 반응")
        pdf.set_font("KR", "", 9)
        try:
            ev_rows = price_df[price_df["is_event"] == True] if "is_event" in price_df.columns else pd.DataFrame()
            if not ev_rows.empty:
                ev_price = int(ev_rows["종가"].iloc[0])
                ev_date  = str(ev_rows.index[0])[:10]
                ev_idx   = price_df.index.get_loc(ev_rows.index[0])
                after    = price_df.iloc[ev_idx + 1: ev_idx + 4]
                if not after.empty:
                    last  = int(after["종가"].iloc[-1])
                    chg   = (last - ev_price) / ev_price * 100
                    dirs  = "상승" if chg > 0 else "하락"
                    summary = (
                        f"실적 발표일({ev_date}) 종가: {ev_price:,}원\n"
                        f"발표 후 {len(after)}거래일 기준 종가: {last:,}원 ({dirs} {abs(chg):.1f}%)"
                    )
                else:
                    summary = f"실적 발표일({ev_date}) 종가: {ev_price:,}원"
            else:
                summary = "주가 반응 데이터 조회 완료 (발표일 특정 불가)"
        except Exception:
            summary = "주가 데이터 포함 (자세한 차트는 앱에서 확인)"
        pdf.multi_cell(0, 5.5, _s(summary))
        pdf.ln(2)

    # ── 7. 푸터 ───────────────────────────────────────────
    footer_y = pdf.h - 24
    pdf.set_y(max(pdf.get_y() + 4, footer_y))
    pdf.set_draw_color(*_BORDER)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("KR", "", 7.5)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 4.5, "본 리포트는 AI MarketWatch가 자동 생성한 분석 자료입니다.", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 4.5, "투자 판단의 근거로 사용하지 마세요. AI 분석 결과는 부정확할 수 있습니다.", new_x="LMARGIN", new_y="NEXT")
    if rcept_no:
        dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
        pdf.cell(0, 4.5, f"DART 원문: {dart_url}", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
