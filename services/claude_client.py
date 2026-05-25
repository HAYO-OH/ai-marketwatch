import json

from groq import Groq

from config.settings import settings

MODEL = "llama-3.3-70b-versatile"

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


class ClaudeClient:
    def __init__(self):
        self._client = Groq(api_key=settings.groq_api_key)

    def analyze(self, system_prompt: str, user_message: str) -> str:
        response = self._client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content

    def classify_disclosures(self, corp_name: str, items: list[dict]) -> list[dict]:
        """공시 목록을 카테고리 분류 + 중요도 점수화. [{index, category, score, reason}, ...]"""
        disclosure_text = "\n".join(
            f"{i}. [{it['rcept_dt']}] {it['report_nm']}"
            for i, it in enumerate(items)
        )
        response = self._client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content": f"{corp_name} 공시 목록:\n{disclosure_text}"},
            ],
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content)
        # Groq json_object 모드는 최상위가 dict일 수 있으므로 배열 추출
        return raw if isinstance(raw, list) else next(iter(raw.values()))
