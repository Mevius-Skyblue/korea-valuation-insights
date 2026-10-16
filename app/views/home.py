"""Home: what / why / how in five lines, methodology links (filled when the public repository exists), disclaimer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import streamlit as st  # noqa: E402

from app.lib.common import footer, md, meta  # noqa: E402

st.title("한국 상장사 가치평가 툴킷 — 공개 화면(예시)")
m = meta()
st.markdown(f"""
- **무엇을**: 증권신고서(합병)에 실린 외부평가 의견서 {m['n_assumption_opinions']}건의 할인율 가정과, 그 추정이 합병 뒤 실제 실적과 얼마나 달랐는지를 집계했다.
- **왜**: 실무 할인율(MRP·SRP·Rf 만기·WACC)의 분포와 추정의 낙관 정도를 숫자로 보이면, 가치평가 가정의 합리성을 점검하는 기준이 된다.
- **어떻게**: DART 공시 원문을 자동으로 읽어 표를 파싱하고, 핵심 항등식(현가·영구가치·가치 사슬)이 맞는 건만 쓰며, 실적은 합병 후 사업보고서에서 가져왔다.
- **화면**: ① 실무 할인율 가정 ② 외부평가 추정 vs 실적 ③ 사용자 입력형 DCF 계산기(같은 계산 엔진).
- **한계**: 스팩 합병 중심 표본, 2015\\~2016 원문 미수신, 2017\\~2019는 정정 전 신고서, 일부 값은 2차 인용(🔸)이다. 집계만 보여 준다.
""")
st.subheader("방법론 문서")
st.markdown(f"- [METHODOLOGY.md]({m['methodology_url']}) — 표본 정의·건수 사슬·달성률 정의·출처 분류 규칙·계산기 공식·한계\n"
            f"- [DATA_NOTICE.md]({m['data_notice_url']}) — 데이터 출처·2차 인용·무보증\n"
            f"- 공개 저장소: [{m['repo_url'].removeprefix('https://')}]({m['repo_url']}) (코드 MIT)")
st.subheader("데이터 범위")
st.write(md(f"{m['data_scope']} · 집계 기준일 {m['as_of']}"))
footer()
