"""한국 주요 기업 로고 유틸리티.

서버 사이드(requests + PIL)로 이미지를 가져와 base64로 변환 후
HTML <img> 태그에 임베딩. st.image()는 블록 요소라 인라인 레이아웃에
쓸 수 없으므로 data URI 방식을 사용.
"""

import base64
from io import BytesIO

import requests
import streamlit as st
from PIL import Image

CORP_LOGOS: dict[str, str] = {
    # 반도체·전자
    "삼성전자":         "samsung.com",
    "SK하이닉스":       "skhynix.com",
    "LG전자":           "lg.com",
    "삼성SDI":          "samsungsdi.com",
    "LG디스플레이":     "lgdisplay.com",
    "삼성전기":         "samsungsem.com",

    # 자동차
    "현대자동차":       "hyundai.com",
    "기아":             "kia.com",
    "현대모비스":       "mobis.co.kr",
    "현대위아":         "hyundai-wia.com",

    # IT·플랫폼
    "카카오":           "kakao.com",
    "네이버":           "naver.com",
    "카카오뱅크":       "kakaobank.com",
    "카카오게임즈":     "kakaogames.com",
    "크래프톤":         "krafton.com",
    "엔씨소프트":       "ncsoft.com",
    "넷마블":           "netmarble.com",
    "넥슨":             "nexon.com",
    "하이브":           "ibighit.com",

    # 통신
    "SK텔레콤":         "sktelecom.com",
    "KT":               "kt.com",
    "LG유플러스":       "uplus.co.kr",

    # 바이오·제약
    "셀트리온":         "celltrion.com",
    "삼성바이오로직스": "samsungbiologics.com",
    "한미약품":         "hanmipharm.com",
    "유한양행":         "yuhan.co.kr",
    "SK바이오팜":       "skbiopharmaceuticals.com",

    # 금융
    "KB금융":           "kbfg.com",
    "신한지주":         "shinhan.com",
    "하나금융지주":     "hanafn.com",
    "우리금융지주":     "woorifg.com",
    "삼성생명":         "samsunglife.com",
    "삼성화재":         "samsungfire.com",
    "미래에셋증권":     "miraeasset.com",
    "키움증권":         "kiwoom.com",

    # 에너지·화학
    "POSCO홀딩스":      "posco.co.kr",
    "LG에너지솔루션":   "lgenergysolution.com",
    "SK이노베이션":     "skinnovation.com",
    "롯데케미칼":       "lottechem.com",
    "한화솔루션":       "hanwhasolutions.com",
    "LG화학":           "lgchem.com",
    "한국전력":         "kepco.co.kr",
    "GS칼텍스":         "gscaltex.com",

    # 건설·중공업
    "현대건설":         "hdec.co.kr",
    "두산에너빌리티":   "doosan.com",
    "한국항공우주":     "koreaaero.com",
    "HD현대":           "hdhyundai.com",

    # 소비재·유통
    "아모레퍼시픽":     "amorepacific.com",
    "LG생활건강":       "lgcare.com",
    "CJ제일제당":       "cj.co.kr",
    "롯데지주":         "lotte.co.kr",
    "코웨이":           "coway.co.kr",
    "오리온":           "orionworld.com",
    "삼성물산":         "samsung.com",
    "현대백화점":       "hyundaigroupkorea.com",
    "이마트":           "emart.com",
}

_FALLBACK_DOMAINS: list[str] = [
    "https://logo.clearbit.com/{domain}",
    "https://www.google.com/s2/favicons?domain={domain}&sz=64",
    "https://{domain}/favicon.ico",
]

_EMOJI_HTML = "<span style='font-size:{size}px;vertical-align:middle;margin-right:6px'>🏢</span>"


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_logo_b64(domain: str) -> str | None:
    """기업 도메인으로 로고를 가져와 PNG base64 문자열 반환. 24시간 캐시."""
    urls = [t.format(domain=domain) for t in _FALLBACK_DOMAINS]
    for url in urls:
        try:
            resp = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and len(resp.content) > 100:
                img = Image.open(BytesIO(resp.content)).convert("RGBA")
                buf = BytesIO()
                img.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            continue
    return None


def get_logo_html(corp_name: str, size: int = 28) -> str:
    """기업명으로 로고 HTML 반환.

    서버에서 이미지를 다운로드해 base64 data URI로 임베딩.
    실패 시 🏢 이모지 span 반환.
    """
    domain = CORP_LOGOS.get(corp_name)
    emoji = _EMOJI_HTML.format(size=int(size * 0.85))
    if not domain:
        return emoji
    b64 = _fetch_logo_b64(domain)
    if not b64:
        return emoji
    return (
        f"<img src='data:image/png;base64,{b64}' "
        f"width='{size}' height='{size}' "
        f"style='border-radius:3px;object-fit:contain;"
        f"vertical-align:middle;margin-right:8px;flex-shrink:0'>"
    )


def get_logo_img(corp_name: str) -> Image.Image | None:
    """PIL Image 반환. st.image() 등 별도 렌더링이 필요한 경우 사용."""
    domain = CORP_LOGOS.get(corp_name)
    if not domain:
        return None
    b64 = _fetch_logo_b64(domain)
    if not b64:
        return None
    return Image.open(BytesIO(base64.b64decode(b64)))
