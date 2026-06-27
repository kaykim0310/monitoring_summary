import pdfplumber
import re
from collections import defaultdict
import sys

# Windows console encoding fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def clean_text(text):
    if not text:
        return ""
    return text.replace("\n", " ").strip()

def classify_factor(factor_name):
    """유해인자 이름을 기반으로 카테고리를 분류합니다 ([별표 12] 참조)."""
    factor_name = factor_name.replace("\n", "").strip()
    if not factor_name or factor_name == "유해인자":
        return None
    
    # 0. 물리적 인자
    if "소음" in factor_name or "고열" in factor_name:
        return "물리적인자"

    # 1. 금속가공유 (미네랄오일 등) - 별표 12 기준
    if any(x in factor_name for x in ["미네랄오일", "오일미스트", "금속가공유"]):
        return "금속가공유"

    # 2. 유기화합물 (가장 많음, 우선순위 높여서 산성 오분류 방지)
    # 아세톤, 톨루엔, 크실렌(자일렌), 메탄올, 에탄올, 이소프로필알코올, 
    # 초산메틸/에틸/부틸, 디메틸..., 벤젠, 헥산, 신너, 가솔린, 나프타 등
    organic_keywords = [
        "아세톤", "톨루엔", "크실렌", "자일렌", "부틸", "에탄올", "메탄올", "이소프로필", "알코올",
        "초산메틸", "초산에틸", "초산부틸", "초산이소", "초산(아세트산)", "아세트산", # 아세트산은 사실 산류일수도 있지만 유기용제로 주로 분류됨 (별표12 유기화합물 108호 초산 등)
        "디메틸", "벤젠", "헥산", "신너", "가솔린", "나프타", "와이어", "유기화합물", "트리클로로",
        "디클로로", "메틸", "에틸", "스티렌", "포름알데히드", "에테르", "케톤", "솔벤트", "세척제", "유기용제"
    ]
    # '초산' 단독은 산류로 분류될 수 있으나, '초산XX'는 유기화합물
    if any(x in factor_name for x in organic_keywords):
        # 예외: 무기산이 섞여있어서 유기화합물로 분류되면 안되는 경우? (거의 없음)
        return "유기화합물"

    # 3. 산 및 알칼리류
    acid_alkali_keywords = [
        "황산", "염산", "질산", "불산", "불소", "수산화", "암모니아", "과산화", "산 및 알칼리", "포르말린" # 포르말린은 알데히드지만 관리상.. 별표12에선 유기화합물(포름알데히드). 여기선 키워드 주의
    ]
    # 별표12에 포름알데히드는 유기화합물임. 위에서 처리됨.
    if any(x in factor_name for x in acid_alkali_keywords):
        return "산 및 알칼리류"
    
    # '산'이 들어가지만 유기가 아닌것 (위에서 유기 다 걸러짐)
    if "산" in factor_name and not any(x in factor_name for x in ["산화", "탄산", "규산", "초산", "유산", "젖산"]): 
        # 산화철(금속), 규산(분진), 탄산(가스/분진) 등 제외
        # 초산은 위에서 유기화합물로 처리 (아세트산)
        # 하지만 그냥 '산' 글자만으로는 위험. 구체적 산 이름 위주로.
        pass

    if "알칼리" in factor_name:
        return "산 및 알칼리류"

    # 4. 금속류
    metal_keywords = [
        "산화철", "망간", "티타늄", "용접흄", "구리", "납", "니켈", "크롬", "아연", "알루미늄", 
        "카드뮴", "코발트", "주석", "안티몬", "비소", "수은", "금속", "스테인리스", "철분"
    ]
    if any(x in factor_name for x in metal_keywords):
        return "금속류"

    # 5. 분진류
    dust_keywords = [
        "분진", "석영", "규소", "시멘트", "광물", "곡물", "목재", "면", "활석", "카본", "유리"
    ]
    if any(x in factor_name for x in dust_keywords):
        return "분진류"

    return "기타"

# ---------------------------------------------------------------------------
# 공정명(그룹) 줄바꿈 보정용 유틸리티
#   text 전략은 '소재양산 QA그룹'처럼 긴 공정명이 '소재양산 QA' + '그룹'으로
#   행이 쪼개져 별도 공정으로 잘못 인식된다. 표 괘선(lines) 전략으로 추출한
#   '정식 공정명' 목록을 사전(canonical)으로 만들어, text 전략에서 나온 조각을
#   원래 공정명으로 합쳐 준다.
# ---------------------------------------------------------------------------
_GROUP_HEADER_WORDS = {
    "부서또는", "공정명", "공정", "단위", "단위작업장소", "작업장소", "유해인자",
    "자수", "근로", "근로형태및", "측정", "측정위치", "발생시간", "발생형태및",
    "노출", "노출기준", "평가결과", "측정농도", "비고", "측정치", "전회", "금회",
    "기준", "횟수",
}
_GROUP_JUNK_KEYWORDS = (
    "측정방법", "여과채취", "검출한계", "고체채취", "확산포집", "소음계",
    "소음노출", "dB", "도시소음", "주어진",
)


def _norm_group(s):
    return re.sub(r"\s+", "", s or "").lower()


def _is_noise_text(txt):
    return ("결과(소음)" in txt) or ("(소음)" in txt and "소음 제외" not in txt)


def _is_group_junk(c0):
    n = _norm_group(c0)
    if not n or n in _GROUP_HEADER_WORDS:
        return True
    return any(k.lower() in c0.lower() for k in _GROUP_JUNK_KEYWORDS)


def build_canonical_groups(pdf):
    """표 괘선 전략으로 0열(공정명)을 모아 정식 공정명 목록을 만든다."""
    cand, seen = [], set()
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    for page in pdf.pages:
        if _is_noise_text(page.extract_text() or ""):
            continue
        try:
            tables = page.extract_tables(table_settings=settings) or []
        except Exception:
            tables = []
        for t in tables:
            for r in t:
                if not r or not r[0]:
                    continue
                g = str(r[0]).replace("\n", "").strip()
                if _is_group_junk(g):
                    continue
                gn = _norm_group(g)
                if gn not in seen:
                    seen.add(gn)
                    cand.append(g)

    # 짧은 것부터 보며, 이미 확보한 공정명들의 연결로 만들어지는 후보(여러 공정이
    # 한 셀에 합쳐진 행)는 제외하고 '원자' 공정명만 남긴다.
    cand.sort(key=lambda x: len(_norm_group(x)))

    def can_segment(s, parts):
        if not s:
            return True
        return any(s.startswith(p) and can_segment(s[len(p):], parts)
                   for p in parts if p)

    atoms = []
    atom_norms = []
    for g in cand:
        gn = _norm_group(g)
        if can_segment(gn, atom_norms):
            continue
        atoms.append(g)
        atom_norms.append(gn)

    # 여러 공정이 한 셀에 합쳐진 '병합 공정명'(예: '장비운전원보통인부',
    # '목공사면보강...')은 다른 공정명을 접두/접미로 포함한다. 이런 항목은
    # 신뢰할 수 없으므로 제거한다. (이 경우 text 전략 원본값으로 폴백)
    cleaned = []
    for a in atoms:
        an = _norm_group(a)
        merged = any(b != a and (an.startswith(_norm_group(b)) or an.endswith(_norm_group(b)))
                     for b in atoms)
        if not merged:
            cleaned.append(a)
    return cleaned


def map_group_name(g, state, canon, canon_norm):
    """text 전략에서 나온 0열 조각 g를 정식 공정명으로 매핑.

    반환값:
      - 문자열: 그 공정으로 전환(새 공정 시작)
      - None  : 직전 공정명의 이어진 조각이므로 흡수(공정 전환 아님)
    """
    gn = _norm_group(g)
    if not gn:
        return state.get("canon")

    # 1) 정식 공정명의 '시작 부분'이면 새 공정 (정확히 일치 우선, 없으면 최단)
    prefix = [c for c, cn in zip(canon, canon_norm) if cn.startswith(gn)]
    if prefix:
        exact = [c for c in prefix if _norm_group(c) == gn]
        chosen = exact[0] if exact else min(prefix, key=lambda x: len(_norm_group(x)))
        state["canon"] = chosen
        return chosen

    # 2) 현재 공정명 안에 들어있는 조각이면 흡수 (예: '소재양산 QA그룹'의 '그룹',
    #    '패키징소재그룹(EMC)'의 '룹(EMC)')
    cc = state.get("canon")
    if cc and gn in _norm_group(cc):
        return None

    # 3) 사전에 없으면 조각 그대로 새 공정
    state["canon"] = g
    return g


def resolve_noise_group(g, canon, canon_norm):
    """소음표 0열 값을 정식 공정명으로 해석. 줄바꿈 조각(접미/중간 부분)은
    None을 반환해 가짜 공정 생성을 막는다."""
    gn = _norm_group(g)
    if not gn:
        return None
    for c, cn in zip(canon, canon_norm):
        if cn == gn:
            return c
    prefix = [c for c, cn in zip(canon, canon_norm) if cn.startswith(gn)]
    if prefix:
        return min(prefix, key=lambda x: len(_norm_group(x)))
    # 어떤 정식 공정명의 일부 조각이면 버림(예: '그룹', '룹(EMC)', 'Slurry)')
    if any(gn in cn for cn in canon_norm):
        return None
    # 사전에 없는 독립 공정명이면 그대로 사용
    return g


def extract_job_data(pdf_path):
    # 계층적 데이터 저장: jobs[group_name][unit_name] = data
    jobs = defaultdict(lambda: defaultdict(lambda: {
        "job_content": "", # text accumulating
        "factors": defaultdict(set),
        "workers": 0,
        "work_form": set()
    }))
    
    company_info = {}

    with pdfplumber.open(pdf_path) as pdf:
        # 1. 개요 정보
        try:
            first_page_text = pdf.pages[0].extract_text()
            if "공장명" in first_page_text:
                match = re.search(r"공장명\s*:\s*(.*?)\s*[○\n]", first_page_text)
                if match: company_info["name"] = match.group(1).strip()
            if "공 사 명" in first_page_text:
                match = re.search(r"공 사 명\s*:\s*(.*)", first_page_text)
                if match: company_info["project"] = match.group(1).strip()
        except: pass
        
        # 2. 테이블 데이터 추출 (text layout strategy)
        for page in pdf.pages:
            # horizontal_strategy="text" 사용
            tables = page.extract_tables(table_settings={"horizontal_strategy": "text"})
            
            for table in tables:
                if not table: continue
                
                # State variables
                current_group = None
                current_unit_key = None # 임시 식별자(카운터 등) 또는 unit_name
                
                # 현재 Unit의 상태
                unit_completed = False
                unit_text_buffer = []
                
                # 이전 루프의 Group 유지를 위해
                if not 'last_persistent_group' in locals():
                    last_persistent_group = None

                for row in table:
                    # 너무 짧거나 헤더인 경우 스킵
                    if not row or len(row) < 5: continue
                    # 헤더 판별 (텍스트 포함 여부)
                    row_str = "".join([str(x) for x in row if x])
                    if "공정명" in row_str or "부서" in row_str: continue

                    # 컬럼 추출 (인덱스 조심, text strategy는 컬럼이 밀릴 수 있음)
                    # 보통 0:Group, 1:Null?, 2..:Unit?, ..:Workers?
                    # Col 0: Group (might be empty)
                    # Col 2: Job Content (might be empty)
                    # Col 3: Factors
                    # Col 4: Worker Count (Numeric?)
                    # Col 5: Work Form
                    
                    # Col 4 (Worker) Check
                    worker_val = None
                    if len(row) > 4 and row[4]:
                         val = str(row[4]).replace("\n", "").strip()
                         # 숫자 포함 여부
                         if any(c.isdigit() for c in val):
                             worker_val = val

                    # Col 0 (Group) Check
                    group_text = row[0]
                    if group_text:
                        group_text = str(group_text).replace("\n", "").strip()

                    # Col 2 (Unit Text)
                    unit_text_part = ""
                    if len(row) > 2 and row[2]:
                        unit_text_part = str(row[2]).replace("\n", " ").strip()

                    # Logic to Switch Unit/Group
                    if group_text:
                        # Case 1: Start New Group -> Force New Unit
                        last_persistent_group = group_text
                        current_group = group_text
                        
                        # Start New Unit
                        if unit_text_buffer: # Commit previous if buffer exists (though logic should have handled it)
                            pass 
                        
                        unit_text_buffer = [unit_text_part] if unit_text_part else []
                        unit_completed = False
                        
                        # 만약 이 라인에 worker도 있다면? -> Completed immediately
                        if worker_val:
                            unit_completed = True
                            
                    else:
                        # Case 2: Same Group (Col 0 empty)
                        current_group = last_persistent_group
                        
                        if not current_group: continue # Skip junk rows before first group
                        
                        if unit_completed and unit_text_part:
                            # Previous unit finished, and we see new text -> Start New Unit
                            unit_text_buffer = [unit_text_part]
                            unit_completed = False
                        else:
                            # Continuation
                            if unit_text_part:
                                unit_text_buffer.append(unit_text_part)
                        
                        if worker_val:
                             unit_completed = True

                    # Factor Accumulation & Store
                    # Since we don't know "When unit ends" until we start new one, 
                    # we should update the "Current Unit object" continuously.
                    # But the "Key" for the unit is the Text itself?
                    # Issue: Text accumulates over lines.
                    # Solution: Use a "Unit Object" reference.
                    
                    # Instead of dict jobs[group][name], let's use a list of units or keeping a pointer.
                    # jobs[group] = [ {unit_data}, ... ]
                    
                    # But return format expects dict items.
                    # Let's use `jobs[group][index]` or maintain a "Current Unit Object".
                    
                    # Simpler: Update the `last unit object` in the list.
                    # Whenever "Start New Unit" happens, create new object.
                    
                    # "Start New Unit" condition re-evaluated:
                    is_new_unit = False
                    if group_text: 
                        is_new_unit = True
                    elif unit_completed and unit_text_part: # Was completed, seeing new text implies new unit
                        # Wait, `unit_completed` was set in PREVIOUS row?
                        # Yes, I used `unit_completed` state variable.
                        # BUT, I need to check `unit_completed` (from prev row) BEFORE setting it for this row.
                        # My logic above: 
                        # `if unit_completed and unit_text_part:` -> Start New Unit.
                        is_new_unit = True
                    
                    # Re-structuring the loop logic properly:
                    
                table_iterator = iter(table)
                # ... rewriting inside `extract_job_data` ...
                pass 
                
    # Re-writing the function logic cleanly
    # (Since I cannot edit inside tool call as text, I will write the full function string below)
    return extract_job_data_impl(pdf_path)

def extract_job_data_impl(pdf_path):
    jobs = defaultdict(list) 
    company_info = {}
    
    # Default indices (heuristic)
    col_map = {
        "group": 0,
        "unit": 3,
        "factor": 4, 
        "worker": 5, 
        "form": 6
    }
    
    with pdfplumber.open(pdf_path) as pdf:
        try:
            first_page_text = pdf.pages[0].extract_text()
            if first_page_text:
                lines = first_page_text.split('\n')
                if lines:
                    for line in lines:
                        clean_line = line.strip()
                        if not clean_line: continue
                        
                        # Skip typical report headers
                        if "나-1" in clean_line or "단위작업" in clean_line:
                            if ":" in clean_line:
                                # Extract content after colon
                                temp = clean_line.split(":", 1)[1].strip()
                                if temp:
                                    company_info["name"] = temp
                                    break
                            continue
                        
                        if "측정" in clean_line and "결과" in clean_line: continue
                        
                        # If we reached here, it might be the company name line
                        company_info["name"] = clean_line
                        break
                        
            # Use regex if specific pattern found (more reliable)
            if "공장명" in first_page_text:
                m = re.search(r"공장명\s*:\s*(.*?)\s*[○\n]", first_page_text)
                if m: company_info["name"] = m.group(1).strip()

            if "공 사 명" in first_page_text:
                m = re.search(r"공 사 명\s*:\s*(.*)", first_page_text)
                if m: company_info["project"] = m.group(1).strip()
        except: pass

        # 소음 측정표(나-2)에 등장한 공정 -> 근로자수/단위작업 (fallback용)
        noise_info = {}

        # 공정명 줄바꿈 보정용 정식 공정명 사전 + 진행 상태
        canonical = build_canonical_groups(pdf)
        canonical_norm = [_norm_group(c) for c in canonical]
        canon_state = {"canon": None, "matched": ""}

        for page in pdf.pages:
            page_text = page.extract_text() or ""
            # 나-2 "결과(소음)" 페이지 식별. 나-1은 "결과(소음 제외)"이므로 제외.
            is_noise_page = ("결과(소음)" in page_text) or \
                            ("(소음)" in page_text and "소음 제외" not in page_text)

            tables = page.extract_tables(table_settings={"horizontal_strategy": "text"})
            for table in tables:
                if not table: continue

                # 소음 결과표(나-2)는 '유해인자' 열이 없고 '발생형태' 열에 '불규칙소음'이
                # 들어 있어 일반 표 파서가 인식하지 못한다. 나-2 표 전체가 소음 측정이므로
                # 여기 등장하는 모든 공정(0열)을 수집해, 뒤에서 물리적인자(소음)를 추가한다.
                # (공정명과 '불규칙소음' 셀이 서로 다른 행에 찍히는 경우가 있어 같은 행 조건을
                #  걸지 않는다.)
                if is_noise_page:
                    header_words = ("공정", "부서", "단위작업장소", "발생형태", "근로자수", "작업내용")
                    for nrow in table:
                        if not nrow: continue
                        joined = "".join([str(c) for c in nrow if c])
                        if "측정방법" in joined: continue
                        g = str(nrow[0]).replace("\n", " ").strip() if nrow[0] else ""
                        if not g or g in header_words:
                            continue
                        g = resolve_noise_group(g, canonical, canonical_norm)
                        if not g:
                            continue
                        w = str(nrow[3]).replace("\n", " ").strip() if len(nrow) > 3 and nrow[3] else ""
                        u = str(nrow[2]).replace("\n", " ").strip() if len(nrow) > 2 and nrow[2] else ""
                        noise_info.setdefault(g, {"worker": w, "unit": u})
                    continue


                # 1. Detect Header
                header_found = False
                for row in table[:5]:
                    if not row: continue
                    row_str = "".join([str(x) for x in row if x])
                    if "공정" in row_str and ("작업" in row_str or "장소" in row_str):
                        for cb_idx, cell in enumerate(row):
                            if not cell: continue
                            txt = str(cell).replace(" ", "")
                            if "공정" in txt or "부서" in txt: col_map["group"] = cb_idx
                            elif "작업" in txt or "장소" in txt or "단위" in txt: col_map["unit"] = cb_idx
                            elif "유해" in txt or "인자" in txt: col_map["factor"] = cb_idx
                            elif "자수" in txt or "인원" in txt or ("근로" in txt and "자명" not in txt and "시간" not in txt and "형태" not in txt):
                                # "근로자수" matches "자수" and "근로".
                                # "근로자명" matches "근로" but has "자명".
                                # "실제근로시간" matches "근로" but has "시간".
                                # "근로형태" matches "근로" but has "형태".
                                # Strict priority: If already set by "자수", don't overwrite with vague "근로".
                                if "자수" in txt or "인원" in txt:
                                     col_map["worker"] = cb_idx
                                elif "worker" not in col_map: # Only set if empty
                                     col_map["worker"] = cb_idx
                            elif "형태" in txt or "근무" in txt: col_map["form"] = cb_idx
                        header_found = True
                        break
                
                # Loop variables init
                last_group = None
                last_job = None
                factor_buf = ""   # 괄호로 줄바꿈된 유해인자명 재조립용 버퍼

                for row in table:
                    if not row or len(row) < 3: continue
                    
                    row_full = "".join([str(x) for x in row if x])
                    if "공정" in row_full and "작업" in row_full: continue
                    if "측정방법" in row_full or "비고" in row_full: continue 
                    if "평균치" in row_full: continue
                    if "측정시각" in row_full: continue 

                    def get_col(idx):
                        if idx < len(row) and row[idx]:
                            return str(row[idx]).replace("\n", " ").strip()
                        return ""
                    
                    g_text = get_col(col_map["group"])
                    u_text = get_col(col_map["unit"])
                    f_text = get_col(col_map["factor"])
                    w_text = get_col(col_map["worker"])
                    form_text = get_col(col_map["form"])
                    
                    # Garbage Filter: 셀 단위 타임스탬프 정리
                    # (행 전체에 측정시각(~15:51)이 있다고 통째로 버리면, 같은 행에 실린
                    #  단위작업명 연장부분/근로자수/유해인자 뒷부분이 함께 사라진다.
                    #  -> 행을 버리지 말고, 측정시각이 잘못 들어온 셀만 비운다.)
                    _ts = r'\d{1,2}\s*:\s*\d{2}'
                    if u_text and (re.search(_ts, u_text) or u_text.lstrip().startswith("~")):
                        u_text = ""
                    if f_text and (re.search(_ts, f_text) or f_text.lstrip().startswith("~")):
                        f_text = ""

                    # Heuristic: Column Shift Correction
                    # If Worker Count is empty but Unit/Factor has pure number, it's likely the count shifted.
                    
                    # 1. Check Unit Name column
                    if u_text and (u_text.isdigit() or re.match(r'^\d+(\s+\d+)*$', u_text)):
                         if not w_text: 
                              w_text = u_text
                         u_text = ""
                    
                    # 2. Check Factor column
                    if f_text and f_text.isdigit():
                         if not w_text:
                              w_text = f_text
                         f_text = ""

                    # Worker Text Cleanup
                    if w_text:
                        if re.match(r'^P\s*\d+$', w_text, re.IGNORECASE):
                             w_text = ""
                        # Filter out "Shift" info like "1조1교대" or "480분" appearing in Count column
                        if "교대" in w_text or "분" in w_text or ":" in w_text:
                             w_text = ""

                    # Strict Row Separation Logic
                    # 공정명 줄바꿈 보정: g_text를 정식 공정명으로 매핑.
                    group_absorbed = False
                    if g_text:
                        mapped = map_group_name(g_text, canon_state, canonical, canonical_norm)
                        if mapped is None:
                            # 직전 공정명의 이어진 조각 -> 공정 전환 아님(이어붙임)
                            group_absorbed = True
                            current_group = last_group
                        else:
                            current_group = mapped
                            last_group = mapped
                    else:
                        current_group = last_group

                    if not current_group: continue

                    # Determine if this row starts a new unit
                    is_new_unit_row = False
                    should_merge_prev = False
                    
                    # Logic:
                    # 1. If u_text exists:
                    #    - If w_text exists (Data Present):
                    #         - If last_unit has NO workers -> MERGE (Assume it was a header/part 1).
                    #         - Else -> NEW UNIT (Distinct).
                    #    - If w_text is Empty:
                    #         - NEW UNIT (Inherit workers) -> Supports MQC/NMR split.
                    # 2. If u_text empty:
                    #    - MERGE (Continuation).
                    
                    if u_text:
                        if w_text:
                            # Check previous unit
                            if jobs[current_group]:
                                last_val = jobs[current_group][-1]["workers"]
                                if not last_val:
                                    should_merge_prev = True
                                    is_new_unit_row = False
                                else:
                                    is_new_unit_row = True
                            else:
                                is_new_unit_row = True
                        else:
                            # Name present, No Data -> New Unit (Inherit)
                            # (Unless we want to treat "No Data" as continuation? 
                            #  User wants split for MQC. So Inherit is safer for "Split" preference.)
                            is_new_unit_row = True
                    else:
                        # No name -> Continuation
                        is_new_unit_row = False
                        should_merge_prev = True # Implicitly merge

                    # 공정명 조각이 흡수된 행(예: '소재양산 QA' 다음의 '그룹')은
                    # 단위작업도 직전 단위의 이어진 부분이므로 새 단위로 만들지 않는다.
                    if group_absorbed and jobs[current_group]:
                        is_new_unit_row = False
                        should_merge_prev = True

                    if is_new_unit_row:
                        # Prepare workers: if empty, inherit
                        use_workers = w_text
                        if not use_workers and jobs[current_group]:
                             use_workers = jobs[current_group][-1]["workers"]

                        entry = {
                            "group": current_group,
                            "name_parts": [u_text] if u_text else [],
                            "factors": defaultdict(set),
                            "workers": use_workers if use_workers else "",
                            "work_form": set()
                        }
                        if form_text: entry["work_form"].add(form_text)
                        jobs[current_group].append(entry)
                        factor_buf = ""   # 새 단위작업 시작 -> 유해인자 버퍼 초기화
                    else:
                        if not jobs[current_group]:
                             # Edge case: No start unit but data implies continuation? 
                             # Create fallback unit
                             entry = {
                                "group": current_group,
                                "name_parts": [u_text] if u_text else [],
                                "factors": defaultdict(set),
                                "workers": w_text if w_text else "",
                                "work_form": set()
                             }
                             if form_text: entry["work_form"].add(form_text)
                             jobs[current_group].append(entry)
                        else:
                             entry = jobs[current_group][-1]
                             if u_text and u_text not in entry["name_parts"]:
                                  entry["name_parts"].append(u_text)
                             
                             if w_text:
                                  # If we are merging, and w_text is present, update.
                                  entry["workers"] = w_text

                             if form_text: entry["work_form"].add(form_text)

                    # Extract factors (괄호 기준으로 줄바꿈된 유해인자명 재조립)
                    if f_text:
                        for sub in re.split(r'[\n]', f_text):
                            sub = sub.strip()
                            if not sub: continue
                            combined = (factor_buf + sub) if factor_buf else sub
                            # 여는 괄호가 아직 안 닫혔으면 다음 조각과 이어붙임
                            if combined.count("(") > combined.count(")"):
                                factor_buf = combined
                                continue
                            factor_buf = ""
                            cat = classify_factor(combined)
                            if jobs[current_group]:
                                target_cat = cat if cat else "기타"
                                jobs[current_group][-1]["factors"][target_cat].add(combined)

    # 소음 결과표(나-2)에서 수집한 공정에 물리적인자(소음) 추가
    for grp, info in noise_info.items():
        if not grp or grp in ("공정", "부서", "부서 또는", "단위작업장소"):
            continue
        if grp in jobs and jobs[grp]:
            jobs[grp][0]["factors"]["물리적인자"].add("소음")
        else:
            # 소음 표에만 존재하는 공정 -> 최소 항목 생성
            entry = {
                "group": grp,
                "name_parts": [info.get("unit")] if info.get("unit") else [],
                "factors": defaultdict(set),
                "workers": info.get("worker", ""),
                "work_form": set(),
            }
            entry["factors"]["물리적인자"].add("소음")
            jobs[grp].append(entry)

    # Post-process: 단위작업명 정리 + 페이지에 걸쳐 쪼개진/중복된 단위 병합
    final_jobs = defaultdict(list)

    for grp, unit_list in jobs.items():
        if not grp: continue
        # Filter out Header Groups
        if grp == "공정" or grp == "부서" or grp == "단위작업장소": continue

        consolidated = []  # 같은 공정 내 병합된 단위 목록
        for u in unit_list:
            full_name = "".join(u["name_parts"]).strip()

            # Check for timestamp in worker field (e.g. 07:07) -> Garbage unit
            w_str = str(u["workers"])
            if re.search(r'\d{2}:\d{2}', w_str):
                continue

            if not full_name:
                # If no name, and no significant data, skip
                if not u["factors"] and not w_str: continue
                full_name = "(공정명 없음)"

            # If name is still empty/placeholder and no meaningful data, skip
            if full_name == "(공정명 없음)" and (not w_str or w_str.strip() == ""):
                 continue

            u["job_content"] = full_name

            # 같은 단위가 페이지마다 반복되거나, 줄바꿈으로 쪼개진 조각
            # (예: '비계/거푸집 조립' + '&해체, 타설')은 하나로 합친다.
            nkey = re.sub(r"\s+", "", full_name)
            target = None
            for c in consolidated:
                ckey = re.sub(r"\s+", "", c["job_content"])
                if nkey == ckey or nkey in ckey or ckey in nkey:
                    target = c
                    break
            if target is None:
                # 새 단위 (factors를 합치기 좋게 복사)
                new_u = {
                    "job_content": full_name,
                    "name_parts": list(u["name_parts"]),
                    "factors": defaultdict(set),
                    "workers": u["workers"],
                    "work_form": set(u["work_form"]),
                }
                for c, s in u["factors"].items():
                    new_u["factors"][c] |= s
                consolidated.append(new_u)
            else:
                # 더 긴(완전한) 이름 채택
                if len(re.sub(r"\s+", "", full_name)) > len(re.sub(r"\s+", "", target["job_content"])):
                    target["job_content"] = full_name
                    target["name_parts"] = list(u["name_parts"])
                for c, s in u["factors"].items():
                    target["factors"][c] |= s
                if u["workers"] and not target["workers"]:
                    target["workers"] = u["workers"]
                target["work_form"] |= u["work_form"]

        for c in consolidated:
            final_jobs[grp].append(c)

    return company_info, final_jobs

def extract_job_data(pdf_path):
    return extract_job_data_impl(pdf_path)

def convert_pdf_to_txt(pdf_path):
    company_info, jobs = extract_job_data(pdf_path)
    
    lines = []
    lines.append("-" * 93)
    
    company = company_info.get("name", "OOO회사") # Default to generic
    if company and "(주)" not in company and "동양" not in company and "건설" in company: 
         # Simple heuristic, but safer to just use what is found or generic
         pass
    
    project_name = company_info.get("project", "OOOO 공사") # Generic default
    
    lines.append(f"■ {company} {project_name}에 대한 공정별 작업내용과")
    lines.append(f"   작업환경측정 대상 유해인자는 다음과 같습니다.")
    lines.append("-" * 93)
    
    lines.append("-" * 93)
    
    # lines.append("□ 공사개요")
    # lines.append(f"   ◆ 공 사 명: {project_name}")
    # lines.append(f"   ◆ 착공일자: 20  .   .   .") 
    # lines.append(f"   ◆ 준공일자: 20  .   .   .(예정)")
    # lines.append(f"   ◇ 특이사항: 공사현장의 경우 공기에 따라 작업내용이 달라질 수 있으므로 작업환경측정 당일") 
    # lines.append(f"                진행되는 작업을 대상으로 작업환경측정을 실시함.")
    # lines.append("-" * 93)
    
    # 계층적 출력
    # jobs: group -> list of unit objects
    # Refined Logic based on Example File:
    # 1. Group by "Group Name" (e.g. 목공, 사면보강) -> This is the main block "■ 목공"
    # 2. Inside the block:
    #    ◇ 작업내용 : Combine names of units (e.g. 비계, 거푸집조립 및 해체...)
    #    ◇ 유해인자 : Merge all factors for this group
    #    ◇ 근무현황 : List distinct worker entries, formatted like "UnitName (N명, Form)" if multiple, or just "N명, Form" if single/uniform.
    
    for group_name, unit_list in jobs.items():
        if not group_name: continue
        # Filter out Header Groups
        if group_name == "공정" or group_name == "부서" or group_name == "단위작업장소": continue
        
        # Valid Units Filter
        valid_units = []
        for u in unit_list:
            full_name = "".join(u["name_parts"]).strip()
            w_str = str(u["workers"])
            if re.search(r'\d{2}:\d{2}', w_str): continue # detailed timestamp filter
            
            if not full_name:
                if not u["factors"] and not w_str: continue
                full_name = "(공정명 없음)"
            if full_name == "(공정명 없음)" and (not w_str or w_str.strip() == ""): continue
            
            u["job_content"] = full_name 
            valid_units.append(u)
            
        if not valid_units: continue

        # Start Output Block
        lines.append(f"■ {group_name}")
        lines.append("-" * 93)
        
        # 1. 작업내용 Merge AND/OR Listing
        # Example uses commas: "비계, 거푸집조립 및 해체, 기타 공사용 목공작업"
        # We can collect unique names
        unique_names = []
        seen_names = set()
        for u in valid_units:
            nm = u["job_content"]
            if nm and nm != "(공정명 없음)" and nm not in seen_names:
                unique_names.append(nm)
                seen_names.add(nm)
        
        content_str = ", ".join(unique_names)
        if not content_str: content_str = group_name # Fallback
        
        lines.append(f"   ◇ 작업내용 : {content_str}")
        lines.append("")
        
        # 2. 유해인자 Merge
        merged_factors = defaultdict(set)
        for u in valid_units:
            for cat, f_set in u["factors"].items():
                merged_factors[cat].update(f_set)
                
        category_order = ["물리적인자", "분진류", "금속류", "유기화합물", "산 및 알칼리류", "금속가공유", "기타"]
        has_factors = any(merged_factors[cat] for cat in category_order)
        
        if has_factors:
            lines.append("   ◇ 유해인자 :")
            current_line_idx = len(lines) - 1
            is_first = True
            
            for cat in category_order:
                if cat in merged_factors and merged_factors[cat]:
                    factors = sorted(list(merged_factors[cat]))
                    factors_str = ", ".join(factors)
                    
                    if cat == "물리적인자": cat_disp = "물리적인자 :"
                    elif cat == "분진류":     cat_disp = "분진류     :"
                    elif cat == "금속류":     cat_disp = "금속류     :"
                    elif cat == "유기화합물": cat_disp = "유기화합물 :"
                    elif cat == "금속가공유": cat_disp = "금속가공유 :"
                    else:                     cat_disp = f"{cat:<10} :"
                    
                    if is_first:
                         lines[current_line_idx] = f"   ◇ 유해인자 : * {cat_disp} {factors_str}"
                         is_first = False
                    else:
                         lines.append(f"                 * {cat_disp} {factors_str}")
            lines.append("")

        # 3. 근무현황 Listing
        # Example Style 1: "13명, 1조1교대" (Simple)
        # Example Style 2: "격자블록설치 (6명, 1조1교대) \n : 낙석방지망설치(3명...)" (Detailed)
        
        # Check if basic aggregation is possible (all same form? names correlate?)
        # Let's collect lines
        worker_lines = []
        for u in valid_units:
            nm = u["job_content"]
            w = u["workers"]
            forms = ", ".join(sorted(list(u["work_form"])))
            
            info = ""
            if w: info += f"{w}명" if str(w).isdigit() else f"{w}"
            if forms: 
                if info: info += f", {forms}"
                else: info = forms
            
            if not info: continue
            
            worker_lines.append((nm, info))

        if worker_lines:
            # Force Detailed Output for consistency
            is_first_print = True
            for nm, info in worker_lines:
                # If Name is strictly same as group, we might want to hide it, 
                # BUT user complaints suggest they want explicit naming context.
                # Only hide if strictly "(공정명 없음)"
                
                disp_name = nm
                if nm == "(공정명 없음)":
                    disp_name = ""
                    
                # Format: "Name (Info)"
                # If Name is empty, just "(Info)"? Or "Info"?
                # Standard: "(Info)" if no name.
                
                content = ""
                if disp_name:
                    content = f"{disp_name:<13}({info})"
                else:
                    content = f"({info})"
                
                prefix = "   ◇ 근무현황 :" if is_first_print else "                 :"
                lines.append(f"{prefix} {content}")
                is_first_print = False
        
        lines.append("-" * 93)

    return "\n".join(lines)

if __name__ == "__main__":
    # 로컬 테스트 용
    result = convert_pdf_to_txt("측정결과_동양건설(창녕12공구)_25하.pdf")
    print(result)
    with open("분포실태_결과_test.txt", "w", encoding="utf-8") as f:
        f.write(result)
