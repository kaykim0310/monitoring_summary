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
    """유해인자 이름을 카테고리로 분류.

    1순위: 공식 분류 사전(FACTOR_CATEGORY, 별표21 + 측정·분석방법 표에서 생성)
    2순위: 키워드 휴리스틱 (사전에 없는 표기 변형 대응)
    """
    factor_name = factor_name.replace("\n", "").strip()
    if not factor_name or factor_name == "유해인자":
        return None

    n = re.sub(r"\s+|·", "", factor_name).lower()

    # 1. 사전 정확 일치 (괄호 이후 제거한 기본형 포함)
    cat = FACTOR_CATEGORY.get(n)
    if cat:
        return cat
    base = re.sub(r"\(.*$", "", n)
    cat = FACTOR_CATEGORY.get(base)
    if cat:
        return cat

    # 2. 사전 키가 이름 안에 포함 (가장 긴 키 우선, 3자 이상)
    best_key = None
    for k, c in FACTOR_CATEGORY.items():
        if len(k) >= 3 and k in n:
            if best_key is None or len(k) > len(best_key[0]):
                best_key = (k, c)
    if best_key:
        return best_key[1]

    # 3. 키워드 휴리스틱 (사전 미등재 표기 변형 대비)
    # 물리적 인자
    if any(x in factor_name for x in ["소음", "고열", "진동", "조도"]):
        return "물리적인자"
    # 금속가공유
    if any(x in factor_name for x in ["미네랄오일", "오일미스트", "오일 미스트", "금속가공유"]):
        return "금속가공유"
    # 유기화합물
    organic_keywords = [
        "아세톤", "톨루엔", "크실렌", "자일렌", "부틸", "에탄올", "메탄올", "이소프로필", "알코올",
        "초산메틸", "초산에틸", "초산부틸", "초산이소", "디메틸", "벤젠", "헥산", "신너", "가솔린",
        "나프타", "유기화합물", "트리클로로", "디클로로", "메틸", "에틸", "스티렌", "포름알데히드",
        "에테르", "케톤", "솔벤트", "세척제", "유기용제", "퓨란", "푸란", "니트릴", "피리딘",
        "글리콜", "아미드", "옥산", "헵탄", "펜탄", "옥탄",
    ]
    if any(x in factor_name for x in organic_keywords):
        return "유기화합물"
    # 가스상 물질류
    gas_keywords = [
        "오존", "암모니아", "일산화탄소", "황화수소", "이산화황", "아황산가스", "이산화질소",
        "일산화질소", "포스핀", "포스겐", "산화에틸렌", "가스",
    ]
    if any(x in factor_name for x in gas_keywords):
        return "가스상 물질류"
    # 산 및 알칼리류
    acid_alkali_keywords = [
        "황산", "염산", "질산", "불산", "불화수소", "브롬화수소", "염화수소", "시안화",
        "수산화", "과산화", "개미산", "인산", "알칼리",
    ]
    if any(x in factor_name for x in acid_alkali_keywords):
        return "산 및 알칼리류"
    # 금속류
    metal_keywords = [
        "산화철", "망간", "티타늄", "구리", "납", "니켈", "크롬", "아연", "알루미늄",
        "카드뮴", "코발트", "주석", "안티몬", "비소", "수은", "금속", "스테인리스", "철분",
        "백금", "은(", "셀레늄", "지르코늄", "텅스텐", "몰리브덴", "바나듐", "베릴륨", "마그네슘",
        "인디움", "인듐",
    ]
    if any(x in factor_name for x in metal_keywords):
        return "금속류"
    # 분진류
    dust_keywords = [
        "분진", "석영", "규소", "규산", "시멘트", "광물", "곡물", "목재", "활석", "카본",
        "유리", "석면", "흑연", "카올린", "소우프스톤", "운모", "먼지", "실리카",
        "리카겔",  # '산화규소-비결정체-실리카겔'이 페이지 경계에서 잘린 꼬리 조각
    ]
    if any(x in factor_name for x in dust_keywords):
        return "분진류"
    # 흄류: 금속명이 앞에서 안 걸린 흄은 분진류 (용접 흄, 조리흄 등)
    if base.endswith("흄") or "흄" in factor_name:
        return "분진류"

    return "기타"

# ---------------------------------------------------------------------------
# 유해인자명 줄바꿈 재조립
#   PDF 셀 안에서 긴 물질명이 줄바꿈되면 text 전략에서 두 조각으로 나뉜다.
#   (예: '1,1-디클로로-1-플루' + '오로에탄') 괄호 균형만으로는 괄호 없는
#   줄바꿈을 못 잡으므로, 공식 유해인자 목록(factor_reference)을 기준
#   사전으로 삼아 조각을 원래 물질명으로 합친다.
# ---------------------------------------------------------------------------
try:
    from factor_reference import (KNOWN_FACTOR_NAMES, KNOWN_FACTOR_TOKENS,
                                  FACTOR_CATEGORY)
except ImportError:
    KNOWN_FACTOR_NAMES = frozenset()
    KNOWN_FACTOR_TOKENS = frozenset()
    FACTOR_CATEGORY = {}


def _norm_factor(s):
    return re.sub(r"\s+", "", s or "")


def _is_known_factor(s):
    n = _norm_factor(s)
    return n in KNOWN_FACTOR_NAMES or n in KNOWN_FACTOR_TOKENS


def _should_join_factor(a, b):
    """유해인자명 조각 a 뒤에 오는 b가 줄바꿈으로 잘린 꼬리인지 판정."""
    if not a or not b:
        return False
    # 1) 여는 괄호가 아직 안 닫힘 -> 무조건 이어붙임
    if a.count("(") > a.count(")"):
        return True
    na, nb = _norm_factor(a), _norm_factor(b)
    nab = na + nb
    # 2) 합치면 공식 유해인자명 (예: '1,1-디클로로-1-플루'+'오로에탄')
    if nab in KNOWN_FACTOR_NAMES:
        return True
    # 3) 아직 공식 명칭을 만들어가는 중 (a가 미완성 접두어)
    if na not in KNOWN_FACTOR_NAMES and any(k.startswith(nab) for k in KNOWN_FACTOR_NAMES):
        return True
    # 4) b가 짧은 순한글 조각이고, 그 자체로 알려진 물질명/토큰도 아니고,
    #    키워드 분류도 안 되면(=독립 물질로 볼 근거가 없으면) 잘린 꼬리로 간주
    #    (예: '산화규소-비결정체-실'+'리카겔', '메틸렌 비스페닐디이'+'소시아네이트')
    #    반면 '산화철분진과흄'처럼 자체 분류되는 조각은 독립 물질이므로 합치지 않음.
    if (re.fullmatch(r"[가-힣]+", b) and len(b) <= 8
            and not _is_known_factor(b) and na not in KNOWN_FACTOR_NAMES
            and classify_factor(b) in (None, "기타")):
        return True
    return False


def _join_name_parts(parts):
    """줄바꿈으로 잘린 이름 조각 결합. 기본은 무공백 결합이되
    '및' 경계('철근가공 및'+'조립')는 공백을 유지한다."""
    out = ""
    for p in parts:
        if out and (out.endswith("및") or p.startswith("및")):
            out += " " + p
        else:
            out += p
    return out


def _commit_factor(entry, name):
    """완성된 유해인자명을 해당 단위작업 항목에 분류·기록."""
    if not entry or not name:
        return
    cat = classify_factor(name) or "기타"
    entry["factors"][cat].add(name)


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


_POS_RE = re.compile(r"[PN]\d{1,3}")


def _row_has_pos(row):
    """행에 측정위치 번호(P1, N12 등)가 있는지 — 새 측정 블록 시작 신호."""
    for c in row:
        if c and _POS_RE.fullmatch(str(c).replace("\n", "").strip()):
            return True
    return False


def build_canonical_groups(pdf):
    """표 괘선 전략으로 0열(공정명)을 모아 정식 공정명 목록을 만든다."""
    cand, seen = [], set()
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    for page in pdf.pages:
        try:
            tables = page.extract_tables(table_settings=settings) or []
        except Exception:
            tables = []
        for t in tables:
            for r in t:
                if not r or not r[0]:
                    continue
                # 통짜 연결 후보(기본) + 괄호로 이어진 '다중 줄' 재조립 조각 후보
                # (예: '기관학부(용\n접실습)\n기관학부' -> 통짜 + '기관학부(용접실습)')
                # 단일 줄 조각('소재양산 QA', '그룹')을 후보로 넣으면 통짜
                # '소재양산 QA그룹'이 세그먼트 규칙에 제거되므로 넣지 않는다.
                g_lines = [ln.strip() for ln in str(r[0]).split("\n") if ln.strip()]
                pieces, buf, nlines = ["".join(g_lines)], "", 0
                for ln in g_lines:
                    buf = buf + ln if buf else ln
                    nlines += 1
                    if buf.count("(") > buf.count(")"):
                        continue
                    if nlines > 1 and buf != pieces[0]:
                        pieces.append(buf)
                    buf = ""
                    nlines = 0
                for g in pieces:
                    if _is_group_junk(g):
                        continue
                    gn = _norm_group(g)
                    if gn not in seen:
                        seen.add(gn)
                        cand.append(g)

    # text 전략 스캔: 0열 공정명 조각들을 순회하며, 조각 사이에 측정위치(P/N)
    # 행이 있으면 서로 다른 공정명, 없으면 같은 이름의 줄바꿈 조각으로 보고
    # 이어붙여 '완결 공정명' 후보를 얻는다.
    # (lattice 셀 하나에 여러 공정이 병합된 경우('장비운전원\n보통인부')를
    #  분리할 근거가 되고, '소재양산 QA'+'그룹'처럼 한 이름의 줄바꿈은
    #  사이에 P/N 행이 없어 자연히 이어진다.)
    for page in pdf.pages:
        try:
            tables = page.extract_tables(
                table_settings={"horizontal_strategy": "text"}) or []
        except Exception:
            tables = []
        for t in tables:
            cur = None
            seen_pos = False
            for row in t:
                if not row:
                    continue
                g = str(row[0]).replace("\n", "").strip() if row[0] else ""
                if g and not _is_group_junk(g):
                    if cur is None:
                        cur = g
                    elif seen_pos:
                        gn = _norm_group(cur)
                        if gn not in seen:
                            seen.add(gn)
                            cand.append(cur)
                        cur = g
                    else:
                        cur = cur + g
                    seen_pos = False
                elif _row_has_pos(row):
                    seen_pos = True
            if cur:
                gn = _norm_group(cur)
                if gn not in seen:
                    seen.add(gn)
                    cand.append(cur)

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

    # 여러 공정이 한 셀에 합쳐진 '병합 공정명'(예: '장비운전원보통인부')은
    # 다른 공정명들의 연결로 완전 분해된다 -> can_segment가 이미 제외.
    # 남은 애매한 경우: 다른 공정명으로 시작/끝나고 '나머지'도 공정명들로
    # 완전 분해될 때만 병합으로 보고 제거한다.
    # ('유도/무장직장'에서 '유도/무장직'을 뺀 나머지 '장'은 공정명이 아니므로
    #  독립 이름으로 유지, '기관학부(용접실습)'의 '(용접실습)'도 마찬가지)
    cleaned = []
    for a in atoms:
        an = _norm_group(a)
        merged = False
        others = [_norm_group(b) for b in atoms if b != a]
        for bn in others:
            if an.startswith(bn) and can_segment(an[len(bn):], others):
                merged = True
                break
            if an.endswith(bn) and can_segment(an[:-len(bn)], others):
                merged = True
                break
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


def _fragment_run_match(s, frags):
    """s가 frags(반대쪽 표의 단위명 조각들)의 '연속 조각 2개 이상'을
    경계에 맞춰 정확히 이어붙인 것인지 검사.
    (경계를 무시한 단순 부분문자열 검사는 서로 다른 단위명에 걸친
    우연한 일치를 만들므로 반드시 조각 경계에 정렬되어야 한다.)"""
    if not s or not frags:
        return False
    for i in range(len(frags)):
        if not frags[i] or not s.startswith(frags[i]):
            continue
        rest = s[len(frags[i]):]
        k = i + 1
        while rest and k < len(frags) and frags[k] and rest.startswith(frags[k]):
            rest = rest[len(frags[k]):]
            k += 1
        if not rest and k > i + 1:
            return True
    return False


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

        # 공정명 줄바꿈 보정용 정식 공정명 사전 + 진행 상태
        canonical = build_canonical_groups(pdf)
        canonical_norm = [_norm_group(c) for c in canonical]
        canon_state = {"canon": None, "matched": ""}

        # 그룹별·표별 단위작업명 조각 풀 (나-1/나-2 교차검증용)
        # 같은 단위명이라도 두 표에서 줄바꿈 위치가 달라, 반대쪽 표의 조각 연결에
        # A+B가 통째로 존재하면 A,B는 한 이름이 잘린 조각임을 검증할 수 있다.
        unit_pools = {"na1": defaultdict(list), "na2": defaultdict(list)}

        for page in pdf.pages:
            page_text = page.extract_text() or ""
            # 나-2 "결과(소음)" 페이지 식별. 나-1은 "결과(소음 제외)"이므로 제외.
            # 소음표는 '유해인자' 열이 없고 '발생형태(불규칙소음)' 열만 있으므로,
            # 이 페이지의 유해인자는 일괄 '소음'으로 처리한다(아래 f_text 강제).
            is_noise_page = ("결과(소음)" in page_text) or \
                            ("(소음)" in page_text and "소음 제외" not in page_text)

            tables = page.extract_tables(table_settings={"horizontal_strategy": "text"})
            for table in tables:
                if not table: continue

                # 1. Detect Header
                # 헤더 라벨이 여러 행에 흩어져 있고(예: '유해인자'가 별도 행),
                # 보고서 양식마다 컬럼 위치/개수가 다르다. 따라서 '실제 데이터 행'이
                # 나오기 전까지의 헤더 행 텍스트를 컬럼별로 합쳐서 각 열의 종류를
                # 판별한다. (한 행만 보면 '유해인자' 열을 놓쳐 엉뚱한 열을 읽게 됨)
                header_words = {
                    "공정명", "공정", "부서또는", "부서", "단위", "단위작업장소", "작업장소",
                    "유해인자", "근로", "근로형태및", "실제근로시간", "근로자수", "자수",
                    "측정", "측정위치", "측정치", "측정농도", "발생시간", "발생형태및",
                    "노출", "노출기준", "평가결과", "비고", "횟수", "기준", "전회", "금회",
                    "방법", "주기", "근로자명", "(근로자명)", "시작", "종료",
                }
                col_text = {}
                for row in table:
                    if not row:
                        continue
                    c0 = str(row[0]).replace("\n", "").replace(" ", "") if row[0] else ""
                    # col0에 실제 공정명이 나오면 헤더 영역 종료
                    if c0 and c0 not in header_words and "twa" not in c0.lower():
                        break
                    for idx, cell in enumerate(row):
                        if cell:
                            col_text[idx] = col_text.get(idx, "") + str(cell).replace("\n", "").replace(" ", "")

                detected = {}
                for idx, txt in col_text.items():
                    if "유해" in txt or "인자" in txt:
                        detected["factor"] = idx
                    elif "자수" in txt or "인원" in txt:
                        detected["worker"] = idx
                    elif "근로형태" in txt or "근무" in txt:
                        # '발생형태'(소음표의 불규칙소음 열)와 구분하기 위해 '근로형태'로 한정
                        detected["form"] = idx
                    elif "작업장소" in txt or "단위" in txt:
                        detected["unit"] = idx
                    elif "공정" in txt or "부서" in txt:
                        detected["group"] = idx

                # 소음표(나-2)는 '유해인자' 열이 없으므로 factor 없이도 헤더 인정
                header_found = ("group" in detected and
                                ("worker" in detected or "unit" in detected))
                if header_found:
                    # 이 표 기준으로 컬럼 매핑을 새로 설정(이전 표 값 잔류 방지)
                    g0 = detected.get("group", 0)
                    col_map = {
                        "group": g0,
                        "unit": detected.get("unit", g0 + 1),
                        "factor": detected.get("factor", 999),  # 소음표엔 유해인자 열 없음
                        "worker": detected.get("worker", g0 + 2),
                        "form": detected.get("form", g0 + 3),
                    }

                # Loop variables init
                last_group = None
                last_job = None
                factor_buf = ""          # 줄바꿈으로 잘린 유해인자명 재조립 버퍼
                factor_buf_entry = None  # 버퍼가 속한 단위작업 항목
                pending_unit_parts = []  # 공정명 행보다 먼저 나온 단위명 조각 보관
                pending_forms = set()
                carry_unit_parts = []    # 공정 확정 후 첫 단위 항목에 붙일 선행 조각
                carry_forms = set()

                for row_idx, row in enumerate(table):
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

                    # Lookahead: 이 행에 측정위치(P/N) 신호가 있고 공정명이 없는데
                    # '다음 행'에서 새 공정이 시작되면, 이 행의 단위명/근로형태는
                    # 이전 공정이 아니라 다음 공정 소속이다.
                    # (예: '토공정리/되메우기 1조1교대 N14' 행 다음에 '장비운전원' 행)
                    if not g_text and _row_has_pos(row):
                        nxt = table[row_idx + 1] if row_idx + 1 < len(table) else None
                        if nxt:
                            gi, ui = col_map["group"], col_map["unit"]
                            nxt_g = (str(nxt[gi]).replace("\n", " ").strip()
                                     if gi < len(nxt) and nxt[gi] else "")
                            nxt_u = (str(nxt[ui]).replace("\n", " ").strip()
                                     if ui < len(nxt) and nxt[ui] else "")
                            if nxt_g and not _is_group_junk(nxt_g):
                                if form_text:
                                    pending_forms.add(form_text)
                                    form_text = ""
                                if u_text and not nxt_u:
                                    pending_unit_parts.append(u_text)
                                    u_text = ""

                    # 소음표(나-2): 유해인자 열이 없고 모든 행이 소음 측정이므로 '소음'으로 처리
                    if is_noise_page:
                        f_text = "소음"

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
                    group_started = False   # 이 행에서 새 공정이 시작됐는가
                    if g_text:
                        mapped = map_group_name(g_text, canon_state, canonical, canonical_norm)
                        if mapped is None:
                            # 직전 공정명의 이어진 조각 -> 공정 전환 아님(이어붙임)
                            group_absorbed = True
                            current_group = last_group
                        else:
                            group_started = (mapped != last_group)
                            current_group = mapped
                            last_group = mapped
                    else:
                        current_group = last_group

                    if not current_group:
                        # 공정명이 아직 안 나온 행의 단위명 조각은 버리지 말고 보관
                        # (예: '손상통제학과/용' 행 다음 행에 '기관학부(용'이 나오는 배치)
                        if u_text:
                            pending_unit_parts.append(u_text)
                        if form_text:
                            pending_forms.add(form_text)
                        continue

                    # 보관해둔 선행 단위명/근로형태 조각은 '새 공정이 시작된 행'에서만
                    # 소비한다. (이전 공정이 진행 중인 행에서 소비하면 엉뚱한 공정에 붙음)
                    if group_started and (pending_unit_parts or pending_forms):
                        _pool = unit_pools["na2" if is_noise_page else "na1"][current_group]
                        for _p in pending_unit_parts:
                            _pool.append(re.sub(r"\s+", "", _p))
                        carry_unit_parts = pending_unit_parts
                        carry_forms = pending_forms
                        pending_unit_parts = []
                        pending_forms = set()

                    # 교차검증용 단위명 조각 수집 (표 종류별)
                    if u_text:
                        unit_pools["na2" if is_noise_page else "na1"][current_group].append(
                            re.sub(r"\s+", "", u_text))

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

                    # 단위작업명이 괄호 중간에서 줄바꿈된 경우
                    # (예: '신소재정비팀(' + '구 FRP2팀)') -> 새 단위가 아니라
                    # 직전 단위명의 연속이므로 병합한다.
                    if is_new_unit_row and jobs[current_group]:
                        prev_name = "".join(jobs[current_group][-1]["name_parts"])
                        if prev_name.count("(") > prev_name.count(")"):
                            is_new_unit_row = False
                            should_merge_prev = True

                    if is_new_unit_row:
                        # Prepare workers: if empty, inherit
                        use_workers = w_text
                        if not use_workers and jobs[current_group]:
                             use_workers = jobs[current_group][-1]["workers"]

                        entry = {
                            "group": current_group,
                            "name_parts": carry_unit_parts + ([u_text] if u_text else []),
                            "factors": defaultdict(set),
                            "workers": use_workers if use_workers else "",
                            "work_form": set(carry_forms),
                            "src": "na2" if is_noise_page else "na1",
                            "own_worker": bool(w_text),
                        }
                        carry_unit_parts = []
                        carry_forms = set()
                        if form_text: entry["work_form"].add(form_text)
                        # 새 단위작업 시작 -> 이전 단위의 미완성 유해인자 버퍼 확정
                        _commit_factor(factor_buf_entry, factor_buf)
                        factor_buf = ""
                        factor_buf_entry = None
                        jobs[current_group].append(entry)
                    else:
                        if not jobs[current_group]:
                             # Edge case: No start unit but data implies continuation? 
                             # Create fallback unit
                             entry = {
                                "group": current_group,
                                "name_parts": carry_unit_parts + ([u_text] if u_text else []),
                                "factors": defaultdict(set),
                                "workers": w_text if w_text else "",
                                "work_form": set(carry_forms),
                                "src": "na2" if is_noise_page else "na1",
                                "own_worker": bool(w_text),
                             }
                             carry_unit_parts = []
                             carry_forms = set()
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

                    # Extract factors: 줄바꿈으로 잘린 유해인자명 재조립
                    # (괄호 균형 + 공식 유해인자 목록 기반 _should_join_factor 판정)
                    if f_text and jobs[current_group]:
                        cur_entry = jobs[current_group][-1]
                        for sub in re.split(r'[\n]', f_text):
                            sub = sub.strip()
                            if not sub: continue
                            if factor_buf and _should_join_factor(factor_buf, sub):
                                factor_buf += sub
                                continue
                            # 이어붙일 수 없으면 이전 버퍼를 확정하고 새 버퍼 시작
                            _commit_factor(factor_buf_entry, factor_buf)
                            factor_buf = sub
                            factor_buf_entry = cur_entry

                # 표 종료 -> 남은 유해인자 버퍼 확정
                _commit_factor(factor_buf_entry, factor_buf)

    # Post-process: 단위작업명 정리 + 페이지에 걸쳐 쪼개진/중복된 단위 병합
    final_jobs = defaultdict(list)

    for grp, unit_list in jobs.items():
        if not grp: continue
        # Filter out Header Groups
        if grp == "공정" or grp == "부서" or grp == "단위작업장소": continue

        consolidated = []  # 같은 공정 내 병합된 단위 목록
        for u in unit_list:
            full_name = _join_name_parts(u["name_parts"]).strip()

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

            # 교차검증 병합: 직전 단위 A와 이번 단위 B가 같은 표에서 나왔고,
            # B가 자체 근로자수 없이 상속받았으며, A+B 연결이 '반대쪽 표'의
            # 단위명 조각 연결 속에 통째로 존재하면 -> A,B는 한 이름이 잘린 조각.
            # (같은 표의 두 표에서 줄바꿈 위치가 달라 교차검증이 가능)
            # 단, A나 B가 반대쪽 표에 독립 조각으로 그대로 존재하면 별개 단위로 본다.
            extend_prev = False
            extend_text = full_name
            if target is None and consolidated:
                prev = consolidated[-1]
                if prev.get("src") and prev.get("src") == u.get("src"):
                    opp = "na1" if u["src"] == "na2" else "na2"
                    opp_frags = unit_pools[opp].get(grp, [])
                    pk = re.sub(r"\s+", "", prev["job_content"])
                    # A+B가 반대쪽 표의 '연속 조각 2개 이상'과 경계까지 정확히
                    # 일치할 때만 병합 (경계 무시 부분문자열은 오병합 위험).
                    # ov=1은 pdfplumber가 경계 글자를 양쪽 조각에 중복 부여한
                    # 경우('영접사격장/통제'+'제실(교관)') 보정.
                    # pk(또는 nkey)가 '단독으로' 반대쪽 조각 run과 완결 일치하면
                    # 그 자체로 완성된 단위명이므로 병합하지 않는다.
                    # (예: 롯데 'ABS중합(F/CBag)1/포장' = na2의 'ABS중합(F/C'+'Bag)1/포장')
                    if (pk and nkey and nkey not in opp_frags and pk not in opp_frags
                            and not _fragment_run_match(pk, opp_frags)
                            and not _fragment_run_match(nkey, opp_frags)):
                        for ov in (0, 1):
                            if ov and (len(nkey) <= ov or pk[-1:] != nkey[:1]):
                                continue
                            combined = pk + nkey[ov:]
                            # 연속 조각 run 일치 또는 반대 표 '단일 조각'과 정확 일치
                            # (예: na1 '낙석방지망설'+'치' == na2 조각 '낙석방지망설치')
                            if (_fragment_run_match(combined, opp_frags)
                                    or combined in opp_frags):
                                target = prev
                                extend_prev = True
                                extend_text = full_name[ov:]
                                break

            if target is None:
                # 새 단위 (factors를 합치기 좋게 복사)
                new_u = {
                    "job_content": full_name,
                    "name_parts": list(u["name_parts"]),
                    "factors": defaultdict(set),
                    "workers": u["workers"],
                    "work_form": set(u["work_form"]),
                    "src": u.get("src"),
                    "own_worker": u.get("own_worker", False),
                }
                for c, s in u["factors"].items():
                    new_u["factors"][c] |= s
                consolidated.append(new_u)
            else:
                if extend_prev:
                    # 잘린 조각 병합: 이름을 이어붙임 ('및' 경계는 공백 유지)
                    target["job_content"] = _join_name_parts(
                        [target["job_content"], extend_text])
                    target["name_parts"] = [target["job_content"]]
                elif len(re.sub(r"\s+", "", full_name)) > len(re.sub(r"\s+", "", target["job_content"])):
                    # 더 긴(완전한) 이름 채택
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

import unicodedata


def _disp_width(s):
    """표시 폭 계산 (한글 등 전각 문자는 2칸)."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in s)


def _wrap_items(prefix, items, max_width=93):
    """'prefix + 항목, 항목, ...'을 A4 폭에 맞춰 물질 경계에서 줄바꿈.

    이어지는 줄은 목록 시작 위치(prefix의 표시 폭)에 맞춰 들여쓴다.
    """
    indent = " " * _disp_width(prefix)
    lines = []
    cur = prefix
    cur_w = _disp_width(prefix)
    first_in_line = True
    for i, item in enumerate(items):
        sep = "" if first_in_line else ", "
        tail = "," if i < len(items) - 1 else ""
        item_w = _disp_width(sep + item + tail)
        if not first_in_line and cur_w + item_w > max_width:
            lines.append(cur + ",")
            cur = indent + item
            cur_w = _disp_width(cur)
        else:
            cur += sep + item
            cur_w += _disp_width(sep + item)
        first_in_line = False
    lines.append(cur)
    return lines


CATEGORY_ORDER = ["물리적인자", "분진류", "금속류", "유기화합물",
                  "산 및 알칼리류", "가스상 물질류", "금속가공유",
                  "허가대상 유해물질", "기타"]
CATEGORY_DISP = {
    "물리적인자": "물리적인자 :",
    "분진류":     "분진류     :",
    "금속류":     "금속류     :",
    "유기화합물": "유기화합물 :",
    "산 및 알칼리류": "산 및 알칼리류 :",
    "가스상 물질류":  "가스상 물질    :",
    "금속가공유": "금속가공유 :",
    "허가대상 유해물질": "허가대상 유해물질 :",
    "기타":       "기타       :",
}


def convert_pdf_to_txt(pdf_path):
    company_info, jobs = extract_job_data(pdf_path)
    return render_summary(company_info, jobs)


def render_summary(company_info, jobs):
    """jobs 구조 -> 분포실태 텍스트 (PDF/엑셀 공용 출력 형식)."""
    company = company_info.get("name", "OOO회사")
    project_name = company_info.get("project", "")
    title_who = f"{company} {project_name}".strip()

    SEP = " " + "-" * 93

    lines = []
    # 표제 (회사/공사 안내)
    lines.append("-" * 93)
    lines.append(f"■ {title_who}에 대한 공정별 작업내용과")
    lines.append(f"   작업환경측정 대상 유해인자는 다음과 같습니다.")
    lines.append("-" * 93)
    lines.append("")

    # 단위작업장소(팀)별 개별 블록 출력: ◆ 직장; 팀
    for group_name, unit_list in jobs.items():
        if not group_name:
            continue
        if group_name in ("공정", "부서", "단위작업장소"):
            continue

        for u in unit_list:
            unit_name = _join_name_parts(u["name_parts"]).strip() or u.get("job_content", "")
            w_str = str(u["workers"])
            if re.search(r'\d{2}:\d{2}', w_str):
                continue  # 측정시각이 근로자수에 잘못 들어온 잡음 항목 제거

            has_factors = any(u["factors"].get(cat) for cat in CATEGORY_ORDER)
            if not unit_name and not has_factors and not w_str:
                continue

            # 블록 제목: "직장; 팀" (팀명이 없으면 직장명만)
            title = f"{group_name}; {unit_name}" if unit_name else group_name
            lines.append(SEP)
            lines.append(f" ◆ {title}")
            lines.append(SEP)

            # 유해인자 (카테고리별, A4 폭에 맞춰 물질 경계에서 줄바꿈)
            if has_factors:
                is_first = True
                for cat in CATEGORY_ORDER:
                    fset = u["factors"].get(cat)
                    if not fset:
                        continue
                    # 혼합유기화합물(Em)은 개별 물질이 아니므로 목록에서 제외
                    items = [x for x in sorted(fset)
                             if not x.replace(" ", "").startswith("혼합유기화합물")]
                    if not items:
                        continue
                    disp = CATEGORY_DISP.get(cat, f"{cat} :")
                    head = "    ◇ 유해인자 : " if is_first else "                  "
                    prefix = f"{head}* {disp} "
                    lines.extend(_wrap_items(prefix, items))
                    is_first = False
                lines.append("")

            # 근무현황: "N명, 근로형태" (실제근로시간 '480분'은 제외)
            w = u["workers"]
            forms = [x for x in sorted(u["work_form"]) if "분" not in str(x)]
            form_str = ", ".join(forms)
            info = ""
            if w:
                info = f"{w}명" if str(w).isdigit() else f"{w}"
            if form_str:
                info = f"{info}, {form_str}" if info else form_str
            lines.append(f"    ◇ 근무현황 : {info}")

    lines.append(SEP)
    return "\n".join(lines)

if __name__ == "__main__":
    # 로컬 테스트 용
    result = convert_pdf_to_txt("측정결과_동양건설(창녕12공구)_25하.pdf")
    print(result)
    with open("분포실태_결과_test.txt", "w", encoding="utf-8") as f:
        f.write(result)
