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
컨센서스(시장 예상) 데이터가 제공된 경우 → 실제 수치와 컨센서스를 직접 비교해 판단하세요.
컨센서스가 없는 경우 → 전년동기(YoY) 또는 전분기(QoQ) 성장률로 판단하세요.

- BEAT: ① 컨센서스 있음: 실제값이 컨센서스 영업이익/매출을 5% 이상 상회
         ② 컨센서스 없음: 영업이익 YoY +20% 초과 또는 원문에 "서프라이즈" 긍정 언급
- MISS:  ① 컨센서스 있음: 실제값이 컨센서스 하회
         ② 컨센서스 없음: 영업이익 YoY -10% 이하 또는 원문에 "쇼크" 부정 언급
- IN_LINE: 컨센서스와 ±5% 이내, 또는 YoY ±10~20% 이내
- UNKNOWN: 컨센서스도 없고 YoY/QoQ 비교 가능한 수치도 부족

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


_MGMT_COMMENT_SYSTEM = """당신은 한국 주식시장 IR 분석 전문가입니다.
실적발표 관련 뉴스/기사에서 경영진(CEO/CFO/대표이사/회장) 발언을 추출하세요.

## 출력 형식
반드시 아래 JSON만 반환하세요. 설명 없이 JSON만 출력합니다.
{
  "ceo_comment": "CEO/대표이사 핵심 발언 1~2문장. 없으면 null",
  "ceo_speaker": "발언자 직함 또는 이름 (예: '대표이사', '이재용 회장'). 모르면 '대표이사'",
  "cfo_comment": "CFO/재무담당 가이던스 발언 1~2문장. 없으면 null",
  "cfo_speaker": "발언자 직함 또는 이름. 모르면 'CFO'",
  "outlook_keywords": ["키워드1", "키워드2", "키워드3"],
  "has_content": true 또는 false
}

## 규칙
- 직접 인용구(따옴표)가 있으면 그대로 추출
- 없으면 기사 내용 기반으로 발언 취지를 1~2문장으로 요약
- outlook_keywords: 향후 전망 관련 핵심 키워드 최대 3개
- 발언 정보가 전혀 없으면 has_content=false, 나머지 null"""


_PORTFOLIO_REBALANCE_SYSTEM = """당신은 한국 주식시장 전문 포트폴리오 매니저입니다.
포트폴리오 구성 데이터와 섹터 현황을 분석하여 리밸런싱을 제안하세요.

## 출력 형식
반드시 아래 JSON만 반환하세요. 설명 없이 JSON만 출력합니다.
{
  "overall_assessment": "전체 포트폴리오 평가 1~2문장",
  "risk_level": "낮음" | "보통" | "높음",
  "suggestions": [
    {
      "name": "종목명",
      "action": "매도" | "매수" | "유지",
      "reason": "사유 20자 이내",
      "target_weight": 목표비중 float 또는 null
    }
  ],
  "sector_comment": "섹터 균형 평가 1문장",
  "key_risk": "가장 큰 리스크 요인 1문장"
}

## 분석 기준
- 특정 섹터 50% 이상 집중 → 높음 리스크
- 수익률 -10% 이하 종목 → 매도 검토
- 수익률 +30% 이상 → 차익 실현 검토
- 섹터 분산 권장 (3섹터 이상), 종목 수 5~15개 적정"""


_ANALYST_REPORT_SYSTEM = """당신은 한국 주식시장 리서치 분석 전문가입니다.
뉴스/기사에서 증권사 애널리스트 리포트 정보를 추출하세요.

## 출력 형식
반드시 아래 JSON만 반환하세요. 설명 없이 JSON만 출력합니다.
{
  "brokers": [
    {
      "name": "증권사명",
      "opinion": "매수" | "중립" | "매도",
      "target_price": 목표주가 int 또는 null,
      "comment": "핵심 코멘트 25자 이내"
    }
  ],
  "consensus_target": 컨센서스 평균 목표주가 int 또는 null,
  "core_comment": "전체 리포트 핵심 요약 1~2문장",
  "has_content": true 또는 false
}

## 규칙
- brokers: 최대 3개 증권사만 추출
- opinion 표준화: "매수"/"비중확대"/"Strong Buy" → "매수", "중립"/"보유"/"시장수익률"/"Neutral" → "중립", "매도"/"비중축소" → "매도"
- consensus_target: 여러 목표주가가 있으면 평균, 단일이면 그 값, 없으면 null
- 정보가 전혀 없으면 has_content=false, brokers=[], 나머지 null"""


_HISTORY_ANALYSIS_SYSTEM = """당신은 한국 주식시장 실적 분석 전문가입니다.
여러 분기의 실적 공시 원문(또는 공시명)을 읽고 각 분기의 핵심 수치와 어닝 서프라이즈를 추출하세요.
원문이 없거나 정보가 부족한 경우 공시명 기반으로 최대한 추론하세요.

## 출력 형식
반드시 아래 JSON 배열만 반환하세요. 설명 없이 JSON만 출력합니다.
[
  {
    "quarter": "분기명 (입력값과 동일하게)",
    "sales_val": 조 단위 float 또는 null,
    "op_profit_val": 조 단위 float 또는 null,
    "op_profit_qoq": 전분기대비 % float (증가=양수, 감소=음수) 또는 null,
    "surprise": "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN"
  }
]

## 수치 변환 규칙
- 백만원 단위면 ÷ 1,000,000 → 조 단위
- 억원 단위면 ÷ 10,000 → 조 단위
- 수치 불명이면 null (임의 추측 금지)
- surprise: 전분기/전년대비 크게 상회=BEAT, 하회=MISS, 부합=IN_LINE, 정보부족=UNKNOWN"""


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

    def analyze_earnings(
        self,
        corp_name: str,
        quarter: str,
        report_name: str,
        text: str,
        consensus_text: str = "",
    ) -> dict:
        """실적 공시 분석. {earnings_surprise, surprise_reason, key_metrics, key_changes, guidance, risks} 반환.

        Args:
            corp_name: 기업명
            quarter: 분기 (예: "2025 4Q")
            report_name: 공시 보고서명
            text: DART 공시 원문
            consensus_text: Tavily 컨센서스 검색 결과. BEAT/MISS 판단에 활용.
        """
        _FALLBACK = {
            "earnings_surprise": "UNKNOWN", "surprise_reason": "분석 실패",
            "key_metrics": [], "key_changes": [], "guidance": "정보 없음", "risks": [],
        }
        _consensus_section = (
            f"\n\n## 컨센서스 (시장 예상) — Tavily 검색 결과\n{consensus_text}"
            if consensus_text.strip() else ""
        )
        if text:
            user_msg = (
                f"기업명: {corp_name}\n분기: {quarter}\n공시명: {report_name}"
                f"\n\n원문:\n{text}{_consensus_section}"
            )
        else:
            user_msg = (
                f"기업명: {corp_name}\n분기: {quarter}\n공시명: {report_name}"
                f"\n\n원문 없음 — 공시명 기반으로 추론{_consensus_section}"
            )
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

    def extract_mgmt_comments(self, corp_name: str, quarter: str, articles_text: str) -> dict:
        """Tavily 검색 결과에서 경영진 발언 추출.
        반환: {ceo_comment, ceo_speaker, cfo_comment, cfo_speaker, outlook_keywords, has_content}"""
        _FALLBACK = {
            "ceo_comment": None, "ceo_speaker": "대표이사",
            "cfo_comment": None, "cfo_speaker": "CFO",
            "outlook_keywords": [], "has_content": False,
        }
        if not articles_text.strip():
            return _FALLBACK
        user_msg = f"기업명: {corp_name}\n분기: {quarter}\n\n뉴스/기사:\n{articles_text[:3000]}"
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=[{"type": "text", "text": _MGMT_COMMENT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = json.loads(_strip_code_fence(response.content[0].text))
            return raw if isinstance(raw, dict) else _FALLBACK
        except Exception:
            return _FALLBACK

    def extract_analyst_report(self, corp_name: str, quarter: str, articles_text: str) -> dict:
        """증권사 애널리스트 리포트 정보 추출.
        반환: {has_content, brokers, consensus_target, core_comment}"""
        _FALLBACK = {
            "has_content": False, "brokers": [],
            "consensus_target": None, "core_comment": None,
        }
        if not articles_text.strip():
            return _FALLBACK
        user_msg = f"기업명: {corp_name}\n분기: {quarter}\n\n뉴스/기사:\n{articles_text[:3000]}"
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=[{"type": "text", "text": _ANALYST_REPORT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = json.loads(_strip_code_fence(response.content[0].text))
            return raw if isinstance(raw, dict) else _FALLBACK
        except Exception:
            return _FALLBACK

    def analyze_earnings_history(self, corp_name: str, quarters_data: list[dict]) -> list[dict]:
        """여러 분기 실적 배치 분석.
        quarters_data = [{quarter, report_nm, doc_text}, ...]
        returns [{quarter, sales_val, op_profit_val, op_profit_qoq, surprise}, ...]"""
        if not quarters_data:
            return []
        parts = []
        for qd in quarters_data:
            part = f"[{qd['quarter']}] 공시명: {qd.get('report_nm') or '없음'}"
            text = (qd.get("doc_text") or "")[:1200]
            if text:
                part += f"\n원문(발췌):\n{text}"
            parts.append(part)
        user_msg = f"기업명: {corp_name}\n\n" + "\n\n---\n\n".join(parts)
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=[{"type": "text", "text": _HISTORY_ANALYSIS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = json.loads(_strip_code_fence(response.content[0].text))
            return raw if isinstance(raw, list) else []
        except Exception:
            return []

    def analyze_portfolio_rebalancing(self, portfolio_data: list[dict], sector_summary: dict) -> dict:
        """포트폴리오 리밸런싱 AI 제안.
        portfolio_data = [{name, sector, weight, return_pct, cur_price}, ...]
        반환: {overall_assessment, risk_level, suggestions, sector_comment, key_risk}"""
        _FALLBACK = {
            "overall_assessment": "분석 실패",
            "risk_level": "보통",
            "suggestions": [],
            "sector_comment": "",
            "key_risk": "",
        }
        user_msg = (
            f"포트폴리오:\n{json.dumps(portfolio_data, ensure_ascii=False)}\n\n"
            f"섹터 집중도:\n{json.dumps(sector_summary, ensure_ascii=False)}"
        )
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=[{"type": "text", "text": _PORTFOLIO_REBALANCE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = json.loads(_strip_code_fence(response.content[0].text))
            return raw if isinstance(raw, dict) else _FALLBACK
        except Exception:
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
