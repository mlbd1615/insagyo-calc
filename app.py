import datetime
import json
import urllib.parse
from typing import Dict, Any, List
import streamlit as st
import streamlit.components.v1 as components
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

# LocalStorage 동기화 브릿지
components.html("""
    <script>
    const localData = localStorage.getItem('gwangju_ai_attendance');
    const urlParams = new URLSearchParams(window.location.search);
    if (localData && !urlParams.has('synced')) {
        const url = new URL(window.location.href);
        url.searchParams.set('data', encodeURIComponent(localData));
        url.searchParams.set('synced', '1');
        window.location.href = url.toString();
    }
    </script>
""", height=0)

if "daily_records" not in st.session_state:
    st.session_state.daily_records = {}
    if "data" in st.query_params:
        try:
            raw_json = urllib.parse.unquote(st.query_params["data"])
            st.session_state.daily_records = json.loads(raw_json)
        except Exception:
            pass

st.error("⚠️ **주의:** 임시공휴일 및 학원 지정 휴교일은 자동 반영되지 않습니다.")
st.title("📱 7기 출결 계산기")

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

# 당월 확정 집계 계산
cal_tardy: int = 0
cal_early: int = 0
cal_out: int = 0
cal_absent: int = 0
cal_official: int = 0

for d_str, rec in st.session_state.daily_records.items():
    if datetime.datetime.strptime(d_str, "%Y-%m-%d").date().month == selected_month:
        st_val = rec.get("status", "")
        if st_val == "🏛️ 공가(공결)": cal_official += 1
        elif st_val == "❌ 결석": cal_absent += 1
        elif st_val == "⏰ 지각": cal_tardy += 1
        elif st_val == "🏃 조퇴": cal_early += 1
        elif st_val == "🚶 외출": cal_out += 1

result: Dict[str, Any] = attendance.calculate_attendance_tool(
    month=selected_month,
    absent_days=cal_absent,
    tardy_count=cal_tardy,
    early_leave_count=cal_early,
    out_count=cal_out,
    official_leave_days=0
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

# 3. 날짜별 출결 입력 및 저장
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

def save_and_sync() -> None:
    """
    st.session_state의 출결 기록 데이터를 JSON 변환 후 LocalStorage 및 URL Query Params에 동기화합니다.
    """
    json_data: str = json.dumps(st.session_state.daily_records, ensure_ascii=False)
    encoded_data: str = urllib.parse.quote(json_data)
    st.query_params["data"] = encoded_data
    st.query_params["synced"] = "1"
    components.html(f"""
        <script>
        localStorage.setItem('gwangju_ai_attendance', '{json_data}');
        </script>
    """, height=0)

def delete_record_by_key(target_key: str) -> None:
    """
    지정된 날짜 키(YYYY-MM-DD)의 출결 기록을 session_state 및 LocalStorage에서 제거합니다.

    Args:
        target_key (str): 삭제 대상 날짜 문자열 (예: "2026-08-11")
    """
    assert isinstance(target_key, str), "target_key는 반드시 문자열 형태여야 합니다."
    assert target_key in st.session_state.daily_records, f"존재하지 않는 키입니다: {target_key}"

    st.session_state.daily_records.pop(target_key, None)
    save_and_sync()
    st.warning(f"🗑️ {target_key} 기록이 삭제되었습니다.")
    st.rerun()

col_btn1, _ = st.columns(2)

with col_btn1:
    if st.button("💾 출결 저장", type="primary", use_container_width=True, disabled=is_disabled):
        if in_status == "🏛️ 공가(공결)" and (current_used_official + 1 > max_official_limit):
            st.error(f"❌ 이번 달 최대 공가 한도({max_official_limit}일)를 초과할 수 없습니다!")
        else:
            st.session_state.daily_records[str_date] = {
                "status": in_status,
                "memo": in_memo.strip()
            }
            save_and_sync()
            st.success(f"✅ {str_date} 기록이 저장되었습니다.")
            st.rerun()

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
    out_count=out_input,
    official_leave_days=0
)

sim_converted: int = (tardy_input // 3) + (early_leave_input // 3) + (out_input // 3)
sim_net_absent: int = absent_input + sim_converted
sim_remaining: int = max(0, max_allowed_absent - sim_net_absent)

st.info(f"💡 **시뮬레이션 결과:** 출석률 **{sim_result['attendance_rate']}%** | 남은 결석 가능: **{sim_remaining}일**")

st.divider()

# 5. 선택 월 기준 목록 출력 (불릿 위치 ❌ 삭제 버튼 적용)
st.subheader(f"📜 {selected_month}월 확정 기록 목록")

monthly_records: List[tuple[str, Dict[str, Any]]] = [
    (d, r) for d, r in st.session_state.daily_records.items()
    if datetime.datetime.strptime(d, "%Y-%m-%d").date().month == selected_month
]

if monthly_records:
    for d_str, rec in sorted(monthly_records):
        assert isinstance(d_str, str), "d_str은 문자열 형태여야 합니다."
        assert isinstance(rec, dict), "rec는 딕셔너리 구조여야 합니다."

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
