import json
import re

import anthropic

from config.settings import settings

MODEL = "claude-haiku-4-5-20251001"

_SENTIMENT_SYSTEM = """당신은 한국 주식시장 뉴스 감성 분석 전문가입니다.
뉴스 기사 목록을 보고 투자자 관점에서 해당 기업에 대한 감성 점수를 매기세요.

## 감성 점수 기준 (-5 ~ +5 정수)
+5: 매우 긍정 — 대규모 계약, 어닝 서프라이즈, 신기술 성과
+3: 긍정 — 실적 개선, 신사업 진출, 파트너십
+1: 약간 긍정 — 소폭 성장, 긍정적 전망
 0: 중립 — 단순 사실 보도, 영향 불분명
-1: 약간 부정 — 소폭 하락, 우려 표명
-3: 부정 — 실적 하락, 소송, 규제 리스크
-5: 매우 부정 — 대규모 손실, 스캔들, 상장폐지 위험

## 출력 형식
반드시 JSON 배열만 반환하세요. 날짜는 출력하지 마세요. index·score·headline만 반환합니다.
[{"index": 0, "score": 정수, "headline": "핵심 내용 15자 이내"}]"""

_EARNINGS_ANALYSIS_SYSTEM = """당신은 한국 주식시장 실적 분석 전문가입니다.
공시 원문을 읽고 투자자 관점에서 실적을 분석하세요.
원문이 없거나 정보가 불충분하면 공시명과 분기 정보로 추론 가능한 수준으로 작성하세요.

## 어닝 서프라이즈 판단 기준
- BEAT: 영업이익/매출이 전분기 또는 전년 동기 대비 시장 예상을 크게 상회, 또는 긍정적 서프라이즈 언급
- MISS: 영업이익/매출이 예상치 하회, 어닝 쇼크 또는 급감 언급
- IN_LINE: 예상치 부합, 소폭 증감
- UNKNOWN: 비교 기준 불명확하거나 원문 정보 부족

## 출력 형식
반드시 아래 JSON 객체만 반환하세요. 설명 없이 JSON만 출력합니다.
{
  "earnings_surprise": "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN",
  "surprise_reason": "판단 근거 30자 이내",
  "key_metrics": [
    {"항목": "매출액", "값": "숫자+단위", "전분기대비": "+N%" 또는 "-N%" 또는 "해당없음"}
  ],
  "key_changes": ["변화1 30자 이내", "변화2 30자 이내", "변화3 30자 이내"],
  "guidance": "가이던스 요약 50자 이내. 없으면 '명시된 가이던스 없음'",
  "risks": ["리스크1 30자 이내", "리스크2 30자 이내", "리스크3 30자 이내"]
}

## key_metrics 규칙
원문에서 찾을 수 있는 핵심 수치 최대 5개. 없으면 빈 배열.
항목 예시: 매출액, 영업이익, 당기순이익, 영업이익률, 부채비율, ROE"""

_SUMMARIZE_SYSTEM = """당신은 한국 주식시장 공시 분석 전문가입니다.
공시 원문 텍스트를 읽고 투자자 관점에서 3줄로 요약하세요.

## 출력 형식
반드시 아래 JSON 객체만 반환하세요. 설명 없이 JSON만 출력합니다.
{
  "핵심내용": "핵심 내용 1줄 (30자 이내)",
  "투자자관점": "투자자 관점에서 주목할 점 1줄 (30자 이내)",
  "리스크기회": "리스크 또는 기회 요인 1줄 (30자 이내)"
}"""

_CLASSIFY_SYSTEM = """당신은 한국 주식시장 공시 분류 전문가입니다.
공시 제목을 보고 아래 7개 카테고리 중 하나로 반드시 분류하고 중요도를 점수화합니다.

## 카테고리 분류 기준 (반드시 7개 중 하나만 선택)

1. 실적
   키워드: 사업보고서, 분기보고서, 반기보고서, 영업(잠정)실적, 매출액, 손익, 재무제표, 연결재무

2. 유상증자
   키워드: 유상증자, 주주배정, 일반공모, 제3자배정, 신주발행, 전환사채, 신주인수권부사채, BW, CB

3. 자사주
   키워드: 자기주식, 자사주, 주식소각, 자기주식취득, 자기주식처분

4. 배당
   키워드: 배당, 현금배당, 주식배당, 중간배당, 배당기준일

5. 지배구조
   키워드: 합병, 분할, 인수, 최대주주변경, 주요주주, 임원변경, 대표이사, 이사회, 감사위원회, 경영권, 지분취득,
           계열회사, 특수관계인, 주주총회, 대규모기업집단, 출자, 계약체결

6. 소송
   키워드: 소송, 판결, 가처분, 공정거래위원회, 금융감독원, 제재, 과징금, 행정처분, 고발, 횡령, 배임

7. 공시정정
   키워드: 정정, 기재정정, 정정공시, 첨부추가

## 분류 우선순위 규칙 (위에서 아래 순서대로 적용)
1. 제목에 "정정" 또는 "기재정정" 포함 → 공시정정
2. 제목에 "자기주식" 또는 "자사주" 포함 → 자사주
3. 제목에 "증자" 포함 → 유상증자
4. 제목에 "배당" 포함 → 배당
5. 제목에 "소송" 또는 "판결" 또는 "과징금" 또는 "횡령" 또는 "배임" 포함 → 소송
6. 제목에 "사업보고서" 또는 "분기보고서" 또는 "반기보고서" 또는 "실적" 포함 → 실적
7. 나머지 모두 (계열사 거래, 특수관계인, 출자, 주주총회, 임원변경, 최대주주 등) → 지배구조

## score 기준 (1~10) — IB·자산운용·리서치 기준, 아래 범위를 반드시 준수하세요

9점 (즉각적 대형 주가 충격):
- 최대주주등소유주식변동신고서 중 1대주주 교체 또는 지분 5%↑ 급변동
- 경영권 분쟁·적대적 M&A, 대규모 유상증자(자본금 30%↑)
- 횡령·배임 혐의, 상장폐지 사유, 워크아웃·법정관리 신청

7점 (상당한 주가 영향):
- 대표이사 교체, 합병·분할·주식교환
- 대규모 소송 패소·과징금(자본금 10%↑), 유상증자(자본금 10~30%), CB·BW 발행

4~5점 (중기 영향):
- 최대주주등소유주식변동신고서 중 소규모 정기 지분 변동(1~3%, 1대주주 유지) → 반드시 4~5점
- 분기·반기·사업보고서, 영업(잠정)실적 공시
- 자사주 취득·처분(발행주식 1~5%), 특별배당
- 신규 사업 진출, 대규모 시설투자, 주요 계약 체결

2~3점 (제한적 영향):
- 소액 정기 배당, 자기주식 소각, 감사보고서 제출
- 임원 변경(대표이사 제외), 계열사 거래·특수관계인 공시
- 주주총회 결과, 대량보유상황보고서(단순 보고)
- 공시 정정(수치 오류·첨부 추가)

1점 (영향 거의 없음):
- 단순 형식 정정, 오탈자 수정, IR 개최 안내
- 반복적 정기 공시(주주명부 폐쇄, 의결권 대리행사 등)

위 범위를 벗어난 점수는 절대 부여하지 마세요.

## reason 작성 규칙
- 공시 제목을 그대로 반복하지 마세요.
- "공시 유형 — 구체적 판단 근거" 형식으로 작성하세요.
- 예시:
  - "최대주주 지분 변동 신고 — 소규모 정기 변동으로 경영권 교체 아님, 4~5점 적용"
  - "분기보고서 제출 — 정기 실적 공시, 서프라이즈 여부 미확인"
  - "대표이사 교체 공시 — 최고경영자 변경으로 경영 불확실성 증가"
  - "기재정정 공시 — 단순 수치 오류 정정, 실질 내용 변경 없음"

## 출력 형식
반드시 아래 JSON 배열만 출력하세요. 설명이나 다른 텍스트 없이 JSON만 반환합니다.
[
  {"index": 0, "category": "카테고리명", "score": 점수, "reason": "공시 유형 — 구체적 판단 근거"},
  ...
]"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    return match.group(1) if match else text


class ClaudeClient:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def analyze(self, system_prompt: str, user_message: str) -> str:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _classify_batch(self, corp_name: str, items: list[dict], offset: int) -> list[dict]:
        """items 배치 하나를 분류. index는 offset 기준으로 반환."""
        disclosure_text = "\n".join(
            f"{offset + i}. [{it['rcept_dt']}] {it['report_nm']}"
            for i, it in enumerate(items)
        )
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=[{"type": "text", "text": _CLASSIFY_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"{corp_name} 공시 목록:\n{disclosure_text}"}],
        )
        raw = json.loads(_strip_code_fence(response.content[0].text))
        return raw if isinstance(raw, list) else next(iter(raw.values()))

    def analyze_sentiment(self, corp_name: str, articles: list[dict]) -> list[dict]:
        """뉴스 기사 감성 분석. 날짜는 Tavily 원본에서 가져와 병합."""
        if not articles:
            return []
        article_text = "\n".join(
            f"{i}. [{a.get('published_date', '날짜미상')}] {a['title']}\n   {a['content'][:200]}"
            for i, a in enumerate(articles)
        )
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=4096,
            timeout=60.0,
            system=[{"type": "text", "text": _SENTIMENT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"{corp_name} 뉴스:\n{article_text}"}],
        )
        try:
            raw = json.loads(_strip_code_fence(response.content[0].text))
            if not isinstance(raw, list):
                return []
            # 날짜를 Claude에게 맡기지 않고 Tavily 원본 published_date로 직접 병합
            result = []
            for item in raw:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(articles):
                    date = articles[idx].get("published_date", "")
                    if date:
                        result.append({
                            "date": date,
                            "score": item.get("score", 0),
                            "headline": item.get("headline", ""),
                        })
            return result
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def summarize_disclosure(self, corp_name: str, report_name: str, text: str) -> dict:
        """공시 원문 3줄 요약. {핵심내용, 투자자관점, 리스크기회} 반환."""
        if not text:
            return {"error": "원문 내용을 가져올 수 없습니다."}
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=[{"type": "text", "text": _SUMMARIZE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"기업명: {corp_name}\n공시명: {report_name}\n\n원문:\n{text}"}],
        )
        try:
            raw = json.loads(_strip_code_fence(response.content[0].text))
            return raw if isinstance(raw, dict) else {"error": "응답 파싱 실패"}
        except (json.JSONDecodeError, KeyError):
            return {"error": "응답 파싱 실패"}

    def analyze_earnings(self, corp_name: str, quarter: str, report_name: str, text: str) -> dict:
        """실적 공시 분석. {earnings_surprise, surprise_reason, key_metrics, key_changes, guidance, risks} 반환."""
        _FALLBACK = {
            "earnings_surprise": "UNKNOWN", "surprise_reason": "분석 실패",
            "key_metrics": [], "key_changes": [], "guidance": "정보 없음", "risks": [],
        }
        if text:
            user_msg = f"기업명: {corp_name}\n분기: {quarter}\n공시명: {report_name}\n\n원문:\n{text}"
        else:
            user_msg = f"기업명: {corp_name}\n분기: {quarter}\n공시명: {report_name}\n\n원문 없음 — 공시명 기반으로 추론"
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": _EARNINGS_ANALYSIS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        try:
            raw = json.loads(_strip_code_fence(response.content[0].text))
            return raw if isinstance(raw, dict) else _FALLBACK
        except (json.JSONDecodeError, KeyError):
            return _FALLBACK

    def classify_disclosures(self, corp_name: str, items: list[dict]) -> list[dict]:
        """공시 목록을 카테고리 분류 + 중요도 점수화. [{index, category, score, reason}, ...]
        50건씩 배치 처리하여 max_tokens 초과 방지."""
        BATCH_SIZE = 50
        results = []
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start : start + BATCH_SIZE]
            results.extend(self._classify_batch(corp_name, batch, offset=start))
        return results
