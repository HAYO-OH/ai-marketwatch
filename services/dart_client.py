import io
import zipfile
import xml.etree.ElementTree as ET

import requests

from config.settings import settings

BASE_URL = "https://opendart.fss.or.kr/api"

# corpCode.xml은 자주 바뀌지 않으므로 프로세스 수명 동안 메모리에 캐시
_corp_code_cache: dict[str, str] | None = None


class DartClient:
    def __init__(self):
        self.api_key = settings.dart_api_key

    def _get_corp_codes(self) -> dict[str, str]:
        """기업명 → corp_code 딕셔너리. 최초 1회만 DART에서 다운로드."""
        global _corp_code_cache
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
        _corp_code_cache = {
            item.findtext("corp_name"): item.findtext("corp_code")
            for item in root.findall("list")
            if item.findtext("corp_name")
        }
        return _corp_code_cache

    def search_company(self, corp_name: str) -> dict | None:
        """기업명으로 corp_code 검색.
        정확히 일치하는 기업 우선, 없으면 이름을 포함하는 첫 번째 기업 반환.
        미발견 시 None."""
        codes = self._get_corp_codes()

        if corp_name in codes:
            return {"corp_code": codes[corp_name], "corp_name": corp_name}

        for name, code in codes.items():
            if corp_name in name:
                return {"corp_code": code, "corp_name": name}

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
