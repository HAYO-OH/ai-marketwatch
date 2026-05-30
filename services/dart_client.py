import io
import re
import zipfile
import xml.etree.ElementTree as ET

import requests

from config.settings import settings

BASE_URL = "https://opendart.fss.or.kr/api"

# corpCode.xml은 자주 바뀌지 않으므로 프로세스 수명 동안 메모리에 캐시
_corp_code_cache: dict[str, str] | None = None
_stock_code_cache: dict[str, str] | None = None

# 영문 입력 → 한글 기업명 매핑 (소문자 기준, 공백 제거 포함)
_EN_TO_KO: dict[str, str] = {
    # 삼성
    "samsung": "삼성전자",
    "samsungelectronics": "삼성전자",
    "samsung electronics": "삼성전자",
    "samsungbio": "삼성바이오로직스",
    "samsung biologics": "삼성바이오로직스",
    "samsungsdi": "삼성SDI",
    "samsung sdi": "삼성SDI",
    "samsungfire": "삼성화재",
    "samsung fire": "삼성화재",
    "samsunglife": "삼성생명",
    "samsung life": "삼성생명",
    "samsungct": "삼성물산",
    "samsung c&t": "삼성물산",
    "samsungcnt": "삼성물산",
    # SK
    "skhynix": "SK하이닉스",
    "sk hynix": "SK하이닉스",
    "skhynix inc": "SK하이닉스",
    "sk": "SK",
    "sktelecommunication": "SK텔레콤",
    "skt": "SK텔레콤",
    "sk telecom": "SK텔레콤",
    "skieoc": "SK이노베이션",
    "sk innovation": "SK이노베이션",
    "skins": "SK이노베이션",
    "sknetworks": "SK네트웍스",
    "sk networks": "SK네트웍스",
    # 현대 (DART 등록명: 현대자동차)
    "hyundai": "현대자동차",
    "hyundai motor": "현대자동차",
    "hyundai motors": "현대자동차",
    "hyundaimotors": "현대자동차",
    "hyundaimobis": "현대모비스",
    "hyundai mobis": "현대모비스",
    "hyundaiglovis": "현대글로비스",
    "hyundai glovis": "현대글로비스",
    "kia": "기아",
    "kiamotors": "기아",
    "kia motors": "기아",
    # 한글 약칭 → DART 정식 등록명
    "현대차": "현대자동차",
    "기아차": "기아",
    "현대모비스": "현대모비스",
    # LG
    "lg": "LG",
    "lgelectronics": "LG전자",
    "lg electronics": "LG전자",
    "lgchem": "LG화학",
    "lg chem": "LG화학",
    "lgenergysolution": "LG에너지솔루션",
    "lg energy solution": "LG에너지솔루션",
    "lges": "LG에너지솔루션",
    "lguplus": "LG유플러스",
    "lgu+": "LG유플러스",
    "lg uplus": "LG유플러스",
    "lgdisplay": "LG디스플레이",
    "lg display": "LG디스플레이",
    # 네이버/카카오
    "naver": "NAVER",
    "kakao": "카카오",
    "kakaobank": "카카오뱅크",
    "kakao bank": "카카오뱅크",
    "kakaopay": "카카오페이",
    "kakao pay": "카카오페이",
    # 포스코
    "posco": "POSCO홀딩스",
    "posco holdings": "POSCO홀딩스",
    "poscohd": "POSCO홀딩스",
    "posco future m": "POSCO퓨처엠",
    "posfuturem": "POSCO퓨처엠",
    # 셀트리온
    "celltrion": "셀트리온",
    "celltrionhealthcare": "셀트리온헬스케어",
    "celltrion healthcare": "셀트리온헬스케어",
    "celltrionpharm": "셀트리온제약",
    "celltrion pharm": "셀트리온제약",
    # 기타 대형주
    "kb": "KB금융",
    "kbfinancial": "KB금융",
    "kb financial": "KB금융",
    "shinhan": "신한지주",
    "shinhanfinancial": "신한지주",
    "shinhan financial": "신한지주",
    "hana": "하나금융지주",
    "hanafinancial": "하나금융지주",
    "hana financial": "하나금융지주",
    "woori": "우리금융지주",
    "woorifinancial": "우리금융지주",
    "woori financial": "우리금융지주",
    "kakaobank": "카카오뱅크",
    "krafton": "크래프톤",
    "netmarble": "넷마블",
    "ncsoft": "엔씨소프트",
    "nc soft": "엔씨소프트",
    "nexon": "넥슨코리아",
    "hanwha": "한화",
    "hanwhaaerosapce": "한화에어로스페이스",
    "hanwha aerospace": "한화에어로스페이스",
    "hanwhaqcells": "한화큐셀",
    "lotte": "롯데쇼핑",
    "lottechem": "롯데케미칼",
    "lotte chemical": "롯데케미칼",
    "ks": "카카오",
    "kepco": "한국전력",
    "korea electric power": "한국전력",
    "hyundaisteel": "현대제철",
    "hyundai steel": "현대제철",
    "samsung heavy": "삼성중공업",
    "samsungheavy": "삼성중공업",
    "hyundaiheavy": "HD현대중공업",
    "hd hyundai": "HD현대",
    "ksoe": "HD현대중공업",
    "gs": "GS",
    "gscaltex": "GS칼텍스",
    "gs caltex": "GS칼텍스",
    "gsretail": "GS리테일",
    "gs retail": "GS리테일",
    "cj": "CJ",
    "cjlogistics": "CJ대한통운",
    "cj logistics": "CJ대한통운",
    "cjcheiljedang": "CJ제일제당",
    "cj cheiljedang": "CJ제일제당",
    "amore": "아모레퍼시픽",
    "amorepacific": "아모레퍼시픽",
    "amore pacific": "아모레퍼시픽",
    "lhcorp": "LH",
    "lhcorporation": "LH",
    "kospi": "코스피",
}


class DartClient:
    def __init__(self):
        self.api_key = settings.dart_api_key

    def _get_corp_codes(self) -> dict[str, str]:
        """기업명 → corp_code 딕셔너리. 최초 1회만 DART에서 다운로드."""
        global _corp_code_cache, _stock_code_cache
        if _corp_code_cache is not None:
            return _corp_code_cache

        resp = requests.get(
            f"{BASE_URL}/corpCode.xml",
            params={"crtfc_key": self.api_key},
            timeout=30,
        )
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_data = zf.read("CORPCODE.xml")

        root = ET.fromstring(xml_data)
        _corp_code_cache = {}
        _stock_code_cache = {}
        for item in root.findall("list"):
            name = item.findtext("corp_name")
            if not name:
                continue
            _corp_code_cache[name] = item.findtext("corp_code")
            sc = (item.findtext("stock_code") or "").strip()
            if sc:
                _stock_code_cache[name] = sc
        return _corp_code_cache

    def get_stock_code(self, corp_name: str) -> str | None:
        """기업명으로 KRX 종목코드 조회. 미상장이면 None."""
        self._get_corp_codes()
        global _stock_code_cache
        if _stock_code_cache is None:
            return None
        code = _stock_code_cache.get(corp_name)
        if code:
            return code
        query_lower = corp_name.lower()
        for name, sc in _stock_code_cache.items():
            if query_lower in name.lower() or name.lower() in query_lower:
                return sc
        return None

    def _resolve_name(self, query: str) -> str:
        """영문 입력을 한글 기업명으로 변환. 이미 한글이면 그대로 반환."""
        normalized = query.lower().strip()
        # 공백 제거 버전도 함께 시도
        normalized_nospace = normalized.replace(" ", "")
        return (
            _EN_TO_KO.get(normalized)
            or _EN_TO_KO.get(normalized_nospace)
            or query
        )

    def search_company(self, corp_name: str) -> dict | None:
        """기업명으로 corp_code 검색.
        1) 영문 입력이면 한글 기업명으로 변환
        2) 대소문자 무시 정확 일치
        3) 대소문자 무시 부분 일치
        미발견 시 None."""
        query = self._resolve_name(corp_name.strip())
        codes = self._get_corp_codes()

        # 정확 일치 (대소문자 무시)
        query_lower = query.lower()
        for name, code in codes.items():
            if name.lower() == query_lower:
                return {"corp_code": code, "corp_name": name}

        # 부분 일치 (대소문자 무시) — 가장 짧은 이름 우선으로 과매칭 방지
        matches = [(name, code) for name, code in codes.items() if query_lower in name.lower()]
        if matches:
            best_name, best_code = min(matches, key=lambda x: len(x[0]))
            return {"corp_code": best_code, "corp_name": best_name}

        return None

    def get_disclosures(self, corp_code: str, bgn_de: str, end_de: str, page_count: int = 100) -> list[dict]:
        """공시 목록 반환. 결과 없으면 빈 리스트."""
        resp = requests.get(
            f"{BASE_URL}/list.json",
            params={
                "crtfc_key": self.api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "page_count": page_count,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("list", [])

    def get_all_disclosures(self, bgn_de: str, end_de: str, pblntf_ty: str = "A", page_count: int = 100) -> list[dict]:
        """corp_code 없이 전체 기업 공시 목록 반환 (실적 캘린더용)."""
        resp = requests.get(
            f"{BASE_URL}/list.json",
            params={
                "crtfc_key": self.api_key,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": pblntf_ty,
                "page_count": page_count,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("list", [])

    def get_document_text(self, rcept_no: str, max_chars: int = 4000) -> str:
        """공시 원문 ZIP에서 텍스트 추출.
        DART는 ZIP 안에 {rcept_no}.xml 또는 .htm 파일을 제공함.
        파일 크기 기준 가장 큰 파일을 본문으로 간주."""
        resp = requests.get(
            f"{BASE_URL}/document.xml",
            params={"crtfc_key": self.api_key, "rcept_no": rcept_no},
            timeout=30,
        )
        resp.raise_for_status()

        # 응답이 ZIP인지 확인 (에러 응답은 XML 텍스트로 옴)
        if not resp.content[:4] == b"PK\x03\x04":
            return ""

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            doc_infos = [
                info for info in zf.infolist()
                if info.filename.lower().endswith((".htm", ".html", ".xml"))
                and not info.filename.lower().endswith("dart4.xsd")
            ]
            if not doc_infos:
                return ""
            doc_infos.sort(key=lambda x: x.file_size, reverse=True)
            raw = zf.read(doc_infos[0].filename)

        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            content = raw.decode("utf-8", errors="ignore")

        # XML/HTML 태그 제거 후 텍스트 추출
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&[a-zA-Z#0-9]+;", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
