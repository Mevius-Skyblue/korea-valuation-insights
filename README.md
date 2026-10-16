# 한국 상장사 가치평가 툴킷 — 공개 화면(예시)

증권신고서(합병)에 실린 외부평가 의견서를 집계한 공개 화면과, 사용자 입력형 DCF 계산기입니다.

- 작성자: GitHub [Mevius-Skyblue](https://github.com/Mevius-Skyblue)
- 앱: https://korea-valuation-insights-nadjarrtmvgmg7kxs9ujyy.streamlit.app/ — 한동안 방문이 없으면 앱이 잠들어, 첫 접속 때 깨우는 데 시간이 걸릴 수 있다
- 방법론: [METHODOLOGY.md](METHODOLOGY.md) · 데이터 안내: [DATA_NOTICE.md](DATA_NOTICE.md) · 라이선스: 코드 [MIT](LICENSE)

## 화면
1. **실무 할인율 가정** — 의견서 157건의 MRP·SRP·WACC·영구성장률·영구가치 비중(평가기준 연도별 중앙값·사분위·n), Rf 만기 표시, 출처 분류 변화, 한공회 규모위험 프리미엄 인용 연표(2차 인용)
2. **외부평가 추정 vs 실적** — 의견서 예측 대비 합병 후 실적 달성률(매출·영업이익 × 1·2·3차연도), 금감원 보도치와 나란히, 예측 매출 CAGR 구간 참고 도구
3. **DCF 계산기** — 사용자가 넣은 가정으로 EV·영구가치 비중·함의 배수·민감도(WACC × g)를 계산(시세 입력 없음)

## 데이터 출처
- DART 전자공시(https://dart.fss.or.kr): 증권신고서(합병) 외부평가 의견서 2015-01\~2026-09 제출분(2015\~2016은 원문 미수신) + 합병 후 사업보고서 실적
- 표본·정의·한계: [METHODOLOGY.md](METHODOLOGY.md), 출처·무보증: [DATA_NOTICE.md](DATA_NOTICE.md)
- 집계 기준일 2026-09-30. `app/data/`에는 **집계값만** 있다(개별 거래·회사·평가기관 이름 없음)
- 계산 엔진: `src/valuation/dcf.py`, `wacc.py`, `levering.py`(프로젝트 평가 엔진과 같은 파일)

## 실행
Python 3.13에서 시험했다(새 가상환경에 `requirements.txt`만 설치해 모든 화면 기동 확인).
```
python -m venv venv
venv\Scripts\activate            (macOS·Linux: source venv/bin/activate)
pip install -r requirements.txt
streamlit run app/Home.py
```

## 면책
투자 권유가 아닙니다. 모든 수치는 공개 공시를 집계한 예시이며 특정 종목의 가치·가격에 대한 의견이 아닙니다. 금융투자업(투자자문·투자일임) 등록·신고를 하지 않은 개인 학습·포트폴리오 프로젝트입니다.

모든 수치는 가정 하의 예시이며 정확성을 보증하지 않습니다. 🔸 = 단일 출처·2차 인용, ⚠️ = 원문 미확인.
