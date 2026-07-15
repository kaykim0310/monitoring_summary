import streamlit as st
import os
import tempfile
from pdf_summary_converter import convert_pdf_to_txt
from xls_summary_converter import convert_xls_to_txt

st.set_page_config(page_title="작업환경측정 분포실태 변환기", layout="wide")

st.title("📄 작업환경측정 결과 → 분포실태 변환기")

st.info("""
**📌 엑셀 파일 준비 방법 (권장)**

1. **MES 프로그램**의 보고서 화면에서 **소음제외** 화면과 **소음** 화면 각각 **F11**을 눌러 엑셀 파일을 다운로드합니다.
2. 다운로드한 **파일 2개를 그대로 함께** 아래에 업로드해 주세요. (합치거나 변환할 필요 없음)

※ 두 파일을 시트 2개로 합쳐 **xlsx 한 개**로 저장해 올려도 됩니다. PDF 결과서 1개도 지원합니다.
""")

uploaded_files = st.file_uploader(
    "측정결과 파일 선택 (엑셀 2개 또는 PDF 1개)",
    type=["pdf", "xls", "xlsx", "htm", "html"],
    accept_multiple_files=True,
)

if uploaded_files:
    pdfs = [f for f in uploaded_files if f.name.lower().endswith(".pdf")]
    excels = [f for f in uploaded_files if not f.name.lower().endswith(".pdf")]

    if pdfs and excels:
        st.warning("PDF와 엑셀을 섞어서 올릴 수 없습니다. 한 종류만 선택해 주세요.")
    elif st.button("변환 시작"):
        try:
            with st.spinner("분석 및 변환 중..."):
                if excels:
                    result_text = convert_xls_to_txt([f.getvalue() for f in excels])
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(pdfs[0].getvalue())
                        tmp_path = tmp.name
                    try:
                        result_text = convert_pdf_to_txt(tmp_path)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

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
