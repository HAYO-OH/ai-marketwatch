# AI MarketWatch — Claude Code 가이드

> 🇰🇷 모든 응답과 설명은 한국어로. 코드 변수명·함수명은 영어 snake_case, UI 텍스트는 한국어.

---

## 자주 쓰는 명령어

**앱 실행:**
```
requirements.txt 설치하고 streamlit run app.py 실행해줘.
```

**파일 수정 (파일명·함수명 명시):**
```
pages/2_실적발표요약.py의 _fetch_peer_performance 함수 수정해줘.
```

**프로젝트 구조 확인:**
```
프로젝트 구조 보여줘.
```

**GitHub push:**
```
변경 사항 GitHub에 올려줘. push 전 git pull --rebase origin main 먼저 실행해줘.
```

**에러 해결:**
```
[에러 메시지 붙여넣기] 이 에러 해결해줘.
```

---

## 프로젝트 개요

DART API + Claude API + Tavily + pykrx 연동 AI 금융 대시보드.

| 탭 / 파일 | 역할 |
|---|---|
| `pages/1_DART공시모니터링.py` | 공시 AI 분류·중요도 점수화·감성 분석 |
| `pages/2_실적발표요약.py` | 실적 AI 분석·동종업계 비교·캘린더 |
| `pages/3_포트폴리오리스크.py` | 포트폴리오 리스크 AI 평가 |
| `services/` | dart_client · claude_client · tavily_client |
| `utils/watchlist.py` | 관심 종목 전역 관리 (모든 탭 공유) |
| `config/settings.py` | .env 환경변수 로딩 |

## 기술 스택

Streamlit · Plotly · Anthropic Claude API · DART Open API · Tavily · pykrx · pydantic-settings

## 환경 변수 (.env 파일에만, 코드에 직접 하드코딩 금지)

```
DART_API_KEY=...
ANTHROPIC_API_KEY=...
TAVILY_API_KEY=...
```

---

## 핵심 규칙

- **모델 고정:** Claude API 호출 시 `claude-haiku-4-5-20251001` 만 사용
- **API 키:** `config/settings.py`의 `Settings` 클래스를 통해서만 접근
- **캐싱 필수:** DART·pykrx 응답은 `@st.cache_data(ttl=3600)` 적용
- **에러 표시:** `st.error()` / `st.warning()` / `st.info()` 사용
- **pykrx 제한:** `get_market_ohlcv_by_date`만 사용 (bulk API는 KRX 인증 필요 — 사용 금지)

## session_state 키 (전역 상태)

| 키 | 용도 |
|---|---|
| `watchlist` | 관심 종목 리스트 — 모든 탭 공유 |
| `selected_stock` | Tab 1 → Tab 2 종목 전달 (소비 후 삭제) |
| `search_results` | Tab 1 조회 결과 |
| `earnings_result` | Tab 2 분석 결과 |
| `portfolio_raw_input` | Tab 3 포트폴리오 입력 |

---

## 파일 수정 요청 방법

**파일명 + 함수명을 반드시 명시하세요.**

```
# 좋은 예
pages/2_실적발표요약.py의 _render_earnings_calendar 함수에 기능 추가해줘.
services/claude_client.py의 analyze_earnings 프롬프트 바꿔줘.

# 나쁜 예
캘린더 고쳐줘. / 분석 바꿔줘.
```

---

## 에러가 났을 때

1. **파악** — 에러 메시지 전체를 읽는다
2. **붙여넣기** — 채팅창에 에러 메시지 그대로 입력
3. **수정** — 제안된 수정 적용
4. **확인** — `http://localhost:8501` 에서 직접 확인
