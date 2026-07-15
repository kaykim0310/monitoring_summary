import streamlit as st
from xls_summary_converter import convert_xls_to_txt

st.set_page_config(page_title="작업환경측정 분포실태 변환기", layout="wide")

st.title("📄 작업환경측정 결과 → 분포실태 변환기")

st.info("""
**📌 엑셀 파일 준비 방법**

1. **MES 프로그램**의 보고서 화면에서 **소음제외** 화면과 **소음** 화면 각각 **F11**을 눌러 엑셀 파일을 다운로드합니다.
2. 다운로드한 파일을 각각 열어서 **반드시 [다른 이름으로 저장] → 파일 형식 "Excel 통합 문서(*.xlsx)"** 로 저장합니다.
   (⚠️ "웹 페이지" 형식으로 저장하면 데이터가 분리되어 변환할 수 없습니다)
3. 저장한 **xlsx 파일 2개를 함께** 아래에 업로드해 주세요.

※ 두 파일을 시트 2개로 합쳐 xlsx 한 개로 올려도 됩니다.
""")

uploaded_files = st.file_uploader(
    "측정결과 엑셀 파일 선택 (소음제외 + 소음)",
    type=["xls", "xlsx", "htm", "html"],
    accept_multiple_files=True,
)

if uploaded_files:
    if st.button("변환 시작"):
        try:
            with st.spinner("분석 및 변환 중..."):
                result_text = convert_xls_to_txt([f.getvalue() for f in uploaded_files])

            st.success("변환이 완료되었습니다!")
            st.subheader("📝 변환 결과 미리보기")
            st.text_area("결과 내용", result_text, height=400)
            st.download_button(
                label="📥 텍스트 파일 다운로드",
                data=result_text,
                file_name="분포실태_결과.txt",
                mime="text/plain",
            )
        except Exception as e:
            st.error(f"오류가 발생했습니다: {e}")
