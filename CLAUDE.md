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

## 파일별 구조 맵

> 수정 전 이 맵을 보고 정확한 줄 번호와 함수명을 확인하세요.

### `app.py` (137줄) — 홈 대시보드
| 줄 | 내용 |
|---|---|
| 1–12 | imports |
| 14–20 | `_card()` — 메트릭 카드 HTML 생성 |
| 22–57 | session_state에서 search_results / earnings_result 읽어 메트릭 표시 |
| 58–137 | 최근 공시 목록 (왼쪽) + 실적 서프라이즈 요약 (오른쪽) |

---

### `pages/1_DART공시모니터링.py` (893줄)
| 줄 | 함수 / 섹션 |
|---|---|
| 1–19 | imports + `_get_clients()` |
| 20–37 | `score_badge()`, `score_label()` — 중요도 뱃지/라벨 |
| 39–47 | `_display_summary()` — 요약 메트릭 4개 카드 |
| 48–106 | `_render_disclosure_card()` — 공시 카드 HTML + 주가반응 버튼 |
| 107–176 | `_detect_anomalies()` — 공시 이상 탐지 (급증/반복정정/중요) |
| 177–230 | `_importance_bar_html()`, `_list_card_html()` — 카드 UI 헬퍼 |
| 228–376 | 사이드바 + 메인 입력폼 (기업명·기간·키워드·슬라이더) |
| 376–537 | Phase 1: DART 조회 + AI 분류, Phase 2: 뉴스 + 감성 분석 |
| 537–576 | `_kw_match()` — 키워드 알림 매칭 |
| 577–590 | 이상 탐지 배너 계산 |
| 586–893 | **서브 탭 5개** |
| 592–705 | `tab_list` — 공시 목록 (필터 바 + 카드 + 전체보기 토글) |
| 706–738 | `tab_monitor` — 공시 원문 모니터링 |
| 739–792 | `tab_chart` — 카테고리/중요도 Plotly 차트 |
| 793–869 | `tab_sentiment` — 뉴스 감성 차트 |
| 870–893 | `tab_alert` — 주요 공시 알림 |

---

### `pages/2_실적발표요약.py` (977줄)
| 줄 | 함수 / 섹션 |
|---|---|
| 1–20 | imports + `_get_clients()` |
| 22–46 | `_date_to_quarter()` + Tab1→Tab2 자동 분석 트리거 |
| 48–99 | `_QUARTERS` 분기 dict + `_PEER_GROUPS` 동종업계 dict |
| 101–233 | **캐시 함수 4개** |
| 104 | `_fetch_price()` — pykrx 주가 ±5거래일 |
| 125 | `_fetch_peer_performance()` — 동종업계 1M/3M 수익률 |
| 152 | `_fetch_earnings_calendar()` — DART 실적 캘린더 |
| 180 | `_fetch_kind_ir_calendar()` — KIND IR 예정 캘린더 |
| 235–277 | `_surprise_ui()`, `_render_peer_comparison()` — 렌더링 헬퍼 |
| 279–394 | `_render_earnings_calendar()` — 3주 캘린더 그리드 |
| 396–481 | `_fetch_earnings_history()` — 8분기 DART + Claude 배치 분석 (캐시) |
| 483–574 | `_render_earnings_history_chart()` — 히스토리 Plotly 차트 |
| 576–664 | `_fetch_mgmt_comments()`, `_render_mgmt_comments()` — 경영진 코멘트 |
| 667–712 | 사이드바 + 메인 입력폼 (기업명 · 분기 · 분석 버튼) |
| 713–780 | 분석 실행 블록 (5단계 progress + session_state 저장) |
| 782–900 | **분석 결과 렌더링** (`if earnings_result:`) |
| 806 | 요약 카드 (BEAT/MISS 배지 + 핵심 수치 st.metric) |
| 838 | AI 분석 섹션 (핵심변화/가이던스/리스크) |
| 854 | 주가 반응 Plotly 차트 |
| 902 | 동종업계 비교 |
| 931 | PDF 다운로드 버튼 (`generate_earnings_pdf`) |
| 951 | 실적 히스토리 차트 호출 |
| 961 | 경영진 코멘트 호출 |
| 968–977 | 실적 공시 캘린더 (항상 표시) |

---

### `pages/3_포트폴리오리스크.py` (156줄)
| 줄 | 내용 |
|---|---|
| 1–12 | imports |
| 13–30 | `parse_portfolio()` — 텍스트 입력 파싱 |
| 31–156 | 사이드바 입력 + Claude 리스크 분석 + 결과 표시 |

---

### `services/dart_client.py` (306줄) — `DartClient` 클래스
| 줄 | 메서드 |
|---|---|
| 1–148 | module-level: `_EN_TO_KO` 영문→한글 매핑 dict |
| 150 | `class DartClient` |
| 154 | `_get_corp_codes()` — CORPCODE.xml 다운로드 + 파싱 (1회 캐시) |
| 183 | `get_stock_code(corp_name)` — KRX 종목코드 조회 |
| 198 | `_resolve_name(query)` — 영문 입력 → 한글 기업명 |
| 209 | `search_company(corp_name)` — corp_code 검색 |
| 232 | `get_disclosures(corp_code, bgn, end)` — 공시 목록 |
| 248 | `get_all_disclosures(bgn, end)` — 전체 기업 공시 |
| 264 | `get_document_text(rcept_no)` — 공시 원문 ZIP 파싱 |

---

### `services/claude_client.py` (354줄) — `ClaudeClient` 클래스
| 줄 | 내용 |
|---|---|
| 1–145 | 시스템 프롬프트 상수 5개 |
| 10 | `_SENTIMENT_SYSTEM` — 뉴스 감성 분석 |
| 26 | `_EARNINGS_ANALYSIS_SYSTEM` — 실적 공시 분석 |
| 53 | `_SUMMARIZE_SYSTEM` — 공시 3줄 요약 |
| 64 | `_CLASSIFY_SYSTEM` — 공시 분류 + 중요도 |
| 145 | `_MGMT_COMMENT_SYSTEM` — 경영진 발언 추출 |
| 168 | `_HISTORY_ANALYSIS_SYSTEM` — 8분기 배치 분석 |
| 190 | `_strip_code_fence()` — JSON 마크다운 제거 |
| 196 | `class ClaudeClient` |
| 200 | `analyze()` — 범용 Claude 호출 |
| 209 | `_classify_batch()` — 공시 분류 배치 |
| 224 | `analyze_sentiment()` — 뉴스 감성 분석 |
| 259 | `summarize_disclosure()` — 공시 3줄 요약 |
| 275 | `analyze_earnings()` — 실적 분석 (단일 분기) |
| 297 | `extract_mgmt_comments()` — 경영진 발언 추출 |
| 320 | `analyze_earnings_history()` — 8분기 배치 분석 |
| 346 | `classify_disclosures()` — 공시 분류 (배치 50건) |

---

### `utils/pdf_report.py` (326줄)
| 줄 | 내용 |
|---|---|
| 1–14 | imports + 색상 상수 |
| 16 | `_find_korean_font()` — 시스템 한글 폰트 자동 탐색 |
| 31 | `_section()` — PDF 섹션 헤더 그리기 |
| 53 | `_s()` — cp949 안전 문자 변환 |
| 60 | `_fmt_ret()` — 수익률 포맷 |
| 66 | `generate_earnings_pdf(r, peer_df)` — 금융 리포트 PDF 생성 |

---

### `utils/nav.py` (54줄)
| 줄 | 내용 |
|---|---|
| 4–9 | `_PAGES` 네비게이션 항목 정의 |
| 15 | `render_top_nav(current)` — 상단 가로 네비게이션 렌더링 |

### `utils/watchlist.py` (58줄)
| 줄 | 내용 |
|---|---|
| 전체 | `render_watchlist_sidebar()` — 사이드바 관심 종목 추가/삭제/표시 |

### `config/settings.py` (13줄)
| 줄 | 내용 |
|---|---|
| 전체 | `Settings` (pydantic-settings) — `.env`에서 API 키 3개 로딩 |

---

## 에러가 났을 때

1. **파악** — 에러 메시지 전체를 읽는다
2. **붙여넣기** — 채팅창에 에러 메시지 그대로 입력
3. **수정** — 제안된 수정 적용
4. **확인** — `http://localhost:8501` 에서 직접 확인
