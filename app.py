import streamlit as st
import os
import hmac
from pdf_summary_converter import convert_pdf_to_txt
import tempfile

st.set_page_config(page_title="PDF 작업환경측정 요약 프로그램", layout="wide")


def _expected_password():
    """접근 비밀번호: 배포 환경변수(APP_PASSWORD) 우선, 없으면 secrets.toml."""
    pw = os.environ.get("APP_PASSWORD")
    if pw:
        return pw
    try:
        return st.secrets["APP_PASSWORD"]
    except Exception:
        return ""


def check_password():
    """비밀번호가 맞아야 앱을 사용할 수 있게 하는 접근 제한 게이트."""
    expected = _expected_password()

    # 관리자가 비밀번호를 설정하지 않았으면 접근 차단(코드에 비밀번호를 두지 않음)
    if not expected:
        st.title("🔒 접근 제한")
        st.error("접근 비밀번호가 설정되지 않았습니다. 관리자에게 문의하세요.\n\n"
                 "(배포 환경에 `APP_PASSWORD` 환경변수를 설정해야 합니다.)")
        st.stop()

    if st.session_state.get("password_ok", False):
        return True

    def _on_submit():
        if hmac.compare_digest(st.session_state.get("password", ""), expected):
            st.session_state["password_ok"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_ok"] = False

    st.title("🔒 접근 제한")
    st.text_input("비밀번호를 입력하세요", type="password",
                  on_change=_on_submit, key="password")
    if "password_ok" in st.session_state and not st.session_state["password_ok"]:
        st.error("비밀번호가 올바르지 않습니다.")
    st.stop()


check_password()

st.title("📄 작업환경측정 결과 PDF 요약 변환기")
st.markdown("""
PDF 파일을 업로드하면 **분포실태 조사용 텍스트 파일**형식으로 요약 변환해줍니다.
""")

uploaded_file = st.file_uploader("PDF 파일을 선택하세요", type=["pdf"])

if uploaded_file is not None:
    st.info("파일이 업로드되었습니다. 변환을 준비합니다.")
    
    # 임시 파일로 저장 (pdfplumber가 경로를 요구하는 경우가 많음, 혹은 객체 직접 지원 확인)
    # pdfplumber.open()은 file-like object도 지원하므로 바로 넘겨도 되지만, 
    # 로직상 path를 썼다면 임시파일 생성 필요.
    # 여기서는 pdf_summary_converter.py가 path를 받도록 되어있으므로 임시파일 생성.
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name

    try:
        if st.button("변환 시작"):
            with st.spinner("PDF 분석 및 변환 중..."):
                result_text = convert_pdf_to_txt(tmp_path)
            
            st.success("변환이 완료되었습니다!")
            
            # 결과 미리보기
            st.subheader("📝 변환 결과 미리보기")
            st.text_area("결과 내용", result_text, height=400)
            
            # 다운로드 버튼
            st.download_button(
                label="📥 텍스트 파일 다운로드",
                data=result_text,
                file_name="분포실태_결과.txt",
                mime="text/plain"
            )
            
    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")
    finally:
        # 임시 파일 삭제
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
