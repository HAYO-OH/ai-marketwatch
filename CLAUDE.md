# ai-marketwatch

DART API + Claude API + Tavily API를 연동한 AI 기반 주식/기업 분석 Streamlit 앱.

## 프로젝트 구조

```
ai-marketwatch/
├── app.py                  # Streamlit 진입점 (홈 화면)
├── pages/                  # Streamlit 멀티페이지
│   ├── 1_DART공시모니터링.py
│   ├── 2_실적발표요약.py
│   └── 3_포트폴리오리스크.py
├── services/               # 외부 API 클라이언트
│   ├── dart_client.py      # DART Open API
│   ├── claude_client.py    # Anthropic Claude API
│   └── tavily_client.py    # Tavily Search API
├── utils/                  # 공통 유틸리티
│   ├── formatters.py       # 데이터 포맷 변환
│   └── cache.py            # Streamlit 캐시 헬퍼
├── config/
│   └── settings.py         # 환경변수 로딩 (pydantic-settings)
├── .env                    # 로컬 시크릿 (gitignore)
├── .env.example            # 환경변수 템플릿
├── requirements.txt
└── .gitignore
```

## API 키 설정

`.env` 파일에 아래 값을 채워 넣으세요:

```
DART_API_KEY=...
ANTHROPIC_API_KEY=...
TAVILY_API_KEY=...
```

## 개발 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 주요 의존성

| 패키지 | 용도 |
|---|---|
| streamlit | UI 프레임워크 |
| anthropic | Claude API SDK |
| tavily-python | Tavily Search |
| requests | DART API HTTP 호출 |
| pydantic-settings | 환경변수 타입 검증 |
| pandas | 데이터 처리 |
| plotly | 차트 시각화 |

## 코드 규칙

- 서비스 레이어(`services/`)는 Streamlit에 의존하지 않는 순수 Python 클래스로 작성
- API 응답은 항상 `@st.cache_data`로 캐싱 (TTL 설정 필수)
- Claude 호출 시 prompt caching 활성화 (`cache_control` 헤더 사용)
- 환경변수는 `config/settings.py`의 `Settings` 클래스를 통해서만 접근
