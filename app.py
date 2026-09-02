import datetime
import json
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import pandas as pd
import requests
import streamlit as st
import attendance

HOLIDAYS_2026: List[str] = [
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02", "2026-05-05", "2026-05-24",
    "2026-06-06", "2026-08-15", "2026-09-24", "2026-09-25",
    "2026-09-26", "2026-10-03", "2026-10-09", "2026-12-25"
]

BADGE_STYLES: Dict[str, str] = {
    "🏛️ 공가(공결)": "background:#E8F0FE; color:#1A73E8; border:1px solid #1A73E8;",
    "❌ 결석": "background:#FCE8E6; color:#C5221F; border:1px solid #C5221F;",
    "⏰ 지각": "background:#FEF7E0; color:#B06000; border:1px solid #B06000;",
    "🏃 조퇴": "background:#F3E8FD; color:#7627BB; border:1px solid #7627BB;",
    "🚶 외출": "background:#E6F4EA; color:#137333; border:1px solid #137333;",
    "🟢 정상출석": "background:#F1F3F4; color:#3C4043; border:1px solid #3C4043;"
}

st.set_page_config(page_title="7기 출결 계산기", page_icon="📱", layout="centered")

GITHUB_TOKEN: str = st.secrets.get("GITHUB_TOKEN", "")
GIST_ID: str = st.secrets.get("GIST_ID", "")

def load_from_gist() -> Optional[Dict[str, Dict[str, Any]]]:
    """
    GitHub Private Gist API에서 출결 데이터를 동기화하여 가져옵니다.
    성공하면 dict(빈 Gist면 {})를 반환하고, 시크릿 미설정/네트워크 실패/비정상
    응답이면 None을 반환합니다. "진짜 비어있음"과 "가져오기 실패"를 구분해야
    저장 시 실패를 빈 데이터로 착각해 다른 사람의 기록을 덮어쓰는 사고를 막을 수 있습니다.
    """
    if not GITHUB_TOKEN or not GIST_ID:
        return None
    url: str = f"https://api.github.com/gists/{GIST_ID}"
    headers: Dict[str, str] = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            files = response.json().get("files", {})
            gist_file = files.get("attendance_data.json", {})
            content = gist_file.get("content", "{}")
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    return None

def save_to_gist(records: Dict[str, Dict[str, Any]]) -> bool:
    """
    출결 데이터 사전 객체를 GitHub Private Gist에 동기화 업데이트합니다.
    """
    assert isinstance(records, dict), "records는 반드시 Dict 구조여야 합니다."
    if not GITHUB_TOKEN or not GIST_ID:
        return False
    url: str = f"https://api.github.com/gists/{GIST_ID}"
    headers: Dict[str, str] = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    json_payload: str = json.dumps(records, ensure_ascii=False, indent=2)
    payload = {
        "files": {
            "attendance_data.json": {
                "content": json_payload
            }
        }
    }
    try:
        response = requests.patch(url, headers=headers, json=payload, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def migrate_legacy_format(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    사용자 구분이 없던 예전 버전 데이터(날짜 키 바로 아래 status/memo)를
    '미지정(기존기록)' 사용자 아래로 옮겨서 데이터 손실 없이 새 구조로 맞춥니다.
    """
    if not data:
        return data
    sample_value = next(iter(data.values()))
    if isinstance(sample_value, dict) and "status" in sample_value:
        return {"미지정(기존기록)": data}
    return data

# --- 사용자 식별: 로그인 없이, 주소창 URL(?user=이름)로 사용자를 구분 ---
# 새 컴포넌트/외부 저장소 없이 st.query_params만 사용 — 새로고침에도 유지되고,
# 이 링크를 즐겨찾기해두면 다음 방문 때도 자동으로 같은 사람의 기록이 열린다.
if "user_name" not in st.session_state:
    st.session_state.user_name = st.query_params.get("user", "").strip()

RESERVED_USER_NAMES: set = {"미지정(기존기록)"}

if not st.session_state.user_name:
    st.title("📱 7기 출결 계산기")
    st.info("👋 처음 오셨네요! 사용하실 이름(또는 닉네임)을 입력해주세요.")

    # 이미 등록된 이름과 겹치는지 확인하기 위해 현재 존재하는 이름 목록을 미리 조회
    existing_raw: Optional[Dict[str, Any]] = load_from_gist()
    existing_names: set = (
        set(migrate_legacy_format(existing_raw).keys()) | RESERVED_USER_NAMES
        if existing_raw is not None else RESERVED_USER_NAMES
    )

    name_input: str = st.text_input("이름 / 닉네임", key="name_onboarding_input")
    trimmed_name: str = name_input.strip()
    name_taken: bool = trimmed_name != "" and trimmed_name in existing_names
    if name_taken:
        st.error(f"❌ '{trimmed_name}'은(는) 이미 사용 중인 이름입니다. 다른 사람과 겹치지 않도록 학번이나 초성 등을 붙여서 다시 입력해주세요. (예: {trimmed_name}2)")

    if st.button("시작하기", type="primary", disabled=(not trimmed_name or name_taken)):
        st.session_state.user_name = trimmed_name
        st.query_params["user"] = trimmed_name
        st.rerun()
    st.stop()

if st.query_params.get("user") != st.session_state.user_name:
    st.query_params["user"] = st.session_state.user_name

# 세션 데이터 로드 (전체 사용자 데이터 -> 현재 사용자 기록만 분리)
if "all_records" not in st.session_state:
    st.session_state.all_records = migrate_legacy_format(load_from_gist() or {})
if "daily_records" not in st.session_state:
    st.session_state.daily_records = st.session_state.all_records.get(st.session_state.user_name, {})

def persist_daily_records() -> bool:
    """
    현재 사용자의 기록을 Gist에 저장합니다.
    저장 직전에 Gist의 최신 전체 데이터를 다시 읽어와서, 그 위에 "내 이름" 아래
    데이터만 새 값으로 바꾸고 다른 사람 이름 아래 데이터는 그대로 둔 채 합쳐서 씁니다.
    (페이지를 연 시점의 낡은 캐시를 그대로 덮어쓰면, 그 사이 다른 사람이 저장한
    내용이 통째로 사라질 수 있기 때문입니다.) 최신 데이터를 가져오는 것 자체가
    실패하면, 무엇을 덮어쓸지 알 수 없으므로 저장을 시도하지 않고 바로 실패 처리합니다.
    """
    latest_raw: Optional[Dict[str, Any]] = load_from_gist()
    if latest_raw is None:
        return False
    latest_all_records: Dict[str, Dict[str, Any]] = migrate_legacy_format(latest_raw)
    latest_all_records[st.session_state.user_name] = st.session_state.daily_records
    success: bool = save_to_gist(latest_all_records)
    if success:
        st.session_state.all_records = latest_all_records
    return success

st.error("⚠️ **주의:** 임시공휴일 및 학원 지정 휴교일은 자동 반영되지 않습니다.")
st.title("📱 7기 출결 계산기")

top_col1, top_col2 = st.columns([4, 1.3])
with top_col1:
    st.caption(f"👤 현재 사용자: **{st.session_state.user_name}**")
with top_col2:
    if st.button("🔄 다른 사람으로", use_container_width=True, help="이름을 지우고 다시 입력합니다."):
        del st.query_params["user"]
        del st.session_state["user_name"]
        del st.session_state["daily_records"]
        del st.session_state["all_records"]
        st.rerun()

st.caption("💡 지금 이 페이지 주소를 즐겨찾기/북마크해두면, 다음에 그 링크로 들어올 때 자동으로 본인 기록이 열립니다.")

if not GITHUB_TOKEN or not GIST_ID:
    st.warning("⚠️ 서버 저장이 설정되어 있지 않습니다 (GITHUB_TOKEN/GIST_ID 미설정). 지금 입력하는 기록은 이 화면을 벗어나면 사라집니다.")

# 1. 오늘 날짜 기준 기본 월 지정
today: datetime.date = datetime.date.today()
current_month: int = max(5, min(12, today.month))
month_options: List[int] = [5, 6, 7, 8, 9, 10, 11, 12]
default_month_idx: int = month_options.index(current_month) if current_month in month_options else 0

selected_month: int = st.selectbox(
    "📅 조회 월 선택",
    options=month_options,
    index=default_month_idx,
    format_func=lambda x: f"{x}월"
)

base_info: Dict[str, Any] = attendance.calculate_attendance_tool(month=selected_month)
max_official_limit: int = int(base_info['max_official_leave'])

# 당월 확정 집계 연산 (NumPy 벡터화)
monthly_list: List[Dict[str, Any]] = [
    rec for d_str, rec in st.session_state.daily_records.items()
    if datetime.datetime.strptime(d_str, "%Y-%m-%d").date().month == selected_month
]

df_monthly: pd.DataFrame = pd.DataFrame(monthly_list)

def count_attendance_vectorized(df_records: pd.DataFrame) -> Dict[str, int]:
    """
    DataFrame을 받아서 NumPy 1D C-Contiguous 텐서로 변환 후 브로드캐스팅 연산으로 집계합니다.
    """
    assert isinstance(df_records, pd.DataFrame), "df_records는 반드시 Pandas DataFrame이어야 합니다."

    if df_records.empty or "status" not in df_records.columns:
        return {"cal_tardy": 0, "cal_early": 0, "cal_absent": 0, "cal_official": 0, "cal_out": 0}

    status_vec: np.ndarray = df_records["status"].to_numpy()

    return {
        "cal_tardy": int(np.sum(np.equal(status_vec, "⏰ 지각"))),
        "cal_early": int(np.sum(np.equal(status_vec, "🏃 조퇴"))),
        "cal_out": int(np.sum(np.equal(status_vec, "🚶 외출"))),
        "cal_absent": int(np.sum(np.equal(status_vec, "❌ 결석"))),
        "cal_official": int(np.sum(np.equal(status_vec, "🏛️ 공가(공결)")))
    }

counts: Dict[str, int] = count_attendance_vectorized(df_monthly)
cal_tardy: int = counts["cal_tardy"]
cal_early: int = counts["cal_early"]
cal_out: int = counts["cal_out"]
cal_absent: int = counts["cal_absent"]
cal_official: int = counts["cal_official"]

result: Dict[str, Any] = attendance.calculate_attendance_tool(
    month=selected_month,
    absent_days=cal_absent,
    tardy_count=cal_tardy,
    early_leave_count=cal_early,
    out_count=cal_out
)

# 2. 📊 출결 현황판
st.divider()
st.subheader("📊 출결 현황판")

total_days: int = int(result['total_days'])
target_80_days: int = int(result['target_80_days'])
max_allowed_absent: int = total_days - target_80_days

converted_absent: int = (cal_tardy // 3) + (cal_early // 3) + (cal_out // 3)
net_total_absent: int = cal_absent + converted_absent
remaining_safe_absent: int = max(0, max_allowed_absent - net_total_absent)

m_col1, m_col2 = st.columns(2)
with m_col1:
    st.metric("🔥 남은 결석 가능 일수", f"{remaining_safe_absent}일 남음")
with m_col2:
    st.metric("현재 출석률", f"{result['attendance_rate']} %")

rem_official_days: int = max_official_limit - cal_official
st.caption(f"🏛️ **공가 사용 현황:** {cal_official}일 사용 / 총 {max_official_limit}일 가능 (남은 찬스: {rem_official_days}일)")

st.markdown("##### ⏳ 1결석 추가 차감까지 남은 찬스")
c1, c2, c3 = st.columns(3)
rem_tardy: int = 3 - (cal_tardy % 3) if (cal_tardy % 3) != 0 else 3
rem_early: int = 3 - (cal_early % 3) if (cal_early % 3) != 0 else 3
rem_out: int = 3 - (cal_out % 3) if (cal_out % 3) != 0 else 3

with c1:
    st.metric("⏰ 지각 잔여", f"{rem_tardy}회", help=f"현재 {cal_tardy}회 누적 중")
with c2:
    st.metric("🏃 조퇴 잔여", f"{rem_early}회", help=f"현재 {cal_early}회 누적 중")
with c3:
    st.metric("🚶 외출 잔여", f"{rem_out}회", help=f"현재 {cal_out}회 누적 중")

st.divider()

# 3. 날짜별 출결 입력 / 저장 / 삭제
min_date: datetime.date = datetime.date(2026, selected_month, 1)
max_date: datetime.date = datetime.date(2026, 12, 31) if selected_month == 12 else datetime.date(2026, selected_month + 1, 1) - datetime.timedelta(days=1)
default_picker_date: datetime.date = today if min_date <= today <= max_date else min_date

selected_date: datetime.date = st.date_input(
    "👇 달력에서 날짜 선택",
    value=default_picker_date,
    min_value=min_date,
    max_value=max_date,
    key=f"date_picker_{selected_month}"
)

str_date: str = selected_date.strftime("%Y-%m-%d")
is_disabled: bool = (selected_date.weekday() >= 5) or (str_date in HOLIDAYS_2026)

current_record: Dict[str, Any] = st.session_state.daily_records.get(
    str_date, 
    {"status": "🟢 정상출석", "memo": ""}
)

st.info(f"📌 **선택 날짜: {str_date} ({'공휴일/주말' if is_disabled else '수업일'})**")

status_options: List[str] = ["🟢 정상출석", "⏰ 지각", "🏃 조퇴", "🚶 외출", "❌ 결석", "🏛️ 공가(공결)"]
curr_idx: int = status_options.index(current_record["status"]) if current_record["status"] in status_options else 0

in_status: str = st.selectbox("출결 상태 선택", options=status_options, index=curr_idx, disabled=is_disabled)
in_memo: str = st.text_input("📝 메모 / 사유 입력 (최대 50자)", value=current_record.get("memo", ""), max_chars=50, disabled=is_disabled)

current_used_official: int = sum(
    1 for d_str, rec in st.session_state.daily_records.items()
    if datetime.datetime.strptime(d_str, "%Y-%m-%d").date().month == selected_month
    and rec.get("status") == "🏛️ 공가(공결)" and d_str != str_date
)

def delete_record_by_key(target_key: str) -> None:
    """
    지정된 날짜 키의 기록을 삭제하고 GitHub Private Gist에 동기화합니다.
    """
    assert isinstance(target_key, str), "target_key는 반드시 문자열 형태여야 합니다."
    if target_key in st.session_state.daily_records:
        st.session_state.daily_records.pop(target_key, None)
        if persist_daily_records():
            st.warning(f"🗑️ {target_key} 기록이 삭제되었습니다.")
        else:
            st.error("⚠️ 서버 저장에 실패했습니다. (GITHUB_TOKEN/GIST_ID 설정을 확인해주세요)")
        st.rerun()

col_btn1, col_btn2 = st.columns(2)

with col_btn1:
    if st.button("💾 출결 저장", type="primary", use_container_width=True, disabled=is_disabled):
        if in_status == "🏛️ 공가(공결)" and (current_used_official + 1 > max_official_limit):
            st.error(f"❌ 이번 달 최대 공가 한도({max_official_limit}일)를 초과할 수 없습니다!")
        else:
            st.session_state.daily_records[str_date] = {
                "status": in_status,
                "memo": in_memo.strip()
            }
            if persist_daily_records():
                st.success(f"✅ {str_date} 기록이 저장되었습니다.")
            else:
                st.error("⚠️ 서버 저장에 실패했습니다. (GITHUB_TOKEN/GIST_ID 설정을 확인해주세요) 새로고침하면 방금 입력한 내용이 사라질 수 있습니다.")
            st.rerun()

with col_btn2:
    has_record: bool = str_date in st.session_state.daily_records
    if st.button("🗑️ 선택 날짜 삭제", use_container_width=True, disabled=(is_disabled or not has_record)):
        delete_record_by_key(target_key=str_date)

st.divider()

# 4. 가상 시뮬레이터
st.subheader("✏️ 출결 시뮬레이터 (가상 테스트)")

col_in1, col_in2 = st.columns(2)
with col_in1:
    absent_input = int(st.number_input("결석 일수", min_value=0, max_value=20, value=cal_absent, step=1, format="%d"))
    tardy_input = int(st.number_input("지각 횟수", min_value=0, max_value=20, value=cal_tardy, step=1, format="%d"))

with col_in2:
    early_leave_input = int(st.number_input("조퇴 횟수", min_value=0, max_value=20, value=cal_early, step=1, format="%d"))
    out_input = int(st.number_input("외출 횟수", min_value=0, max_value=20, value=cal_out, step=1, format="%d"))

sim_result: Dict[str, Any] = attendance.calculate_attendance_tool(
    month=selected_month,
    absent_days=absent_input,
    tardy_count=tardy_input,
    early_leave_count=early_leave_input,
    out_count=out_input
)

sim_converted: int = (tardy_input // 3) + (early_leave_input // 3) + (out_input // 3)
sim_net_absent: int = absent_input + sim_converted
sim_remaining: int = max(0, max_allowed_absent - sim_net_absent)

st.info(f"💡 **시뮬레이션 결과:** 출석률 **{sim_result['attendance_rate']}%** | 남은 결석 가능: **{sim_remaining}일**")

st.divider()

# 5. 선택 월 기준 목록 출력
st.subheader(f"📜 {selected_month}월 확정 기록 목록")

monthly_records: List[Tuple[str, Dict[str, Any]]] = [
    (d, r) for d, r in st.session_state.daily_records.items()
    if datetime.datetime.strptime(d, "%Y-%m-%d").date().month == selected_month
]

if monthly_records:
    for d_str, rec in sorted(monthly_records):
        col_del, col_text = st.columns([0.8, 9.2])
        
        with col_del:
            if st.button("❌", key=f"btn_del_{d_str}", help=f"{d_str} 기록 삭제"):
                delete_record_by_key(target_key=d_str)

        st_val: str = rec.get("status", "🟢 정상출석")
        memo_val: str = rec.get("memo", "")
        
        display_memo: str = f"{memo_val[:15]}..." if len(memo_val) > 15 else memo_val
        memo_str: str = f" | <span style='color:#5F6368;'>📝 {display_memo}</span>" if memo_val else ""
        
        style: str = BADGE_STYLES.get(st_val, BADGE_STYLES["🟢 정상출석"])
        badge_html: str = f"<span style='padding:2px 8px; border-radius:12px; font-size:12px; font-weight:bold; {style}'>{st_val}</span>"
        
        with col_text:
            st.markdown(f"**{d_str}** : {badge_html}{memo_str}", unsafe_allow_html=True)
else:
    st.caption("아직 이번 달에 입력된 확정 기록이 없습니다.")
