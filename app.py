import datetime
import json
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

st.set_page_config(page_title="7기 출결 생존 계산기", page_icon="📱", layout="centered")

st.error("⚠️ **주의:** 임시공휴일 및 학원 지정 휴교일은 자동 반영되지 않습니다.")
st.title("📱 7기 출결 생존 계산기")

if "daily_records" not in st.session_state:
    st.session_state.daily_records = {}

# 1. 월 선택
selected_month: int = st.selectbox(
    "📅 조회 월 선택",
    options=[5, 6, 7, 8, 9, 10, 11, 12],
    index=2,
    format_func=lambda x: f"{x}월"
)

base_info: Dict[str, Any] = attendance.calculate_attendance_tool(month=selected_month)
max_official_limit: int = int(base_info['max_official_leave'])

st.divider()

# 2. 날짜 선택기
min_date = datetime.date(2026, selected_month, 1)
max_date = datetime.date(2026, 12, 31) if selected_month == 12 else datetime.date(2026, selected_month + 1, 1) - datetime.timedelta(days=1)

if "selected_date" not in st.session_state or not (min_date <= st.session_state.selected_date <= max_date):
    st.session_state.selected_date = min_date

selected_date: datetime.date = st.date_input(
    "👇 달력에서 날짜 선택",
    value=st.session_state.selected_date,
    min_value=min_date,
    max_value=max_date,
    key="date_picker"
)
st.session_state.selected_date = selected_date
str_date: str = selected_date.strftime("%Y-%m-%d")

is_disabled: bool = (selected_date.weekday() >= 5) or (str_date in HOLIDAYS_2026)

# 기존 기록 있으면 자동 로드 (수정 연동)
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

# 3. 저장 및 삭제 버튼 (2컬럼 라이트 레이아웃)
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
            json_data = json.dumps(st.session_state.daily_records, ensure_ascii=False)
            components.html(
                f"<script>window.localStorage.setItem('gwangju_ai_attendance', '{json_data}');</script>",
                height=0
            )
            st.success(f"✅ {str_date} 기록이 저장(수정)되었습니다.")

with col_btn2:
    # 해당 날짜에 저장된 기록이 있을 때만 삭제 활성화
    has_record = str_date in st.session_state.daily_records
    if st.button("🗑️ 기록 삭제", use_container_width=True, disabled=(is_disabled or not has_record)):
        st.session_state.daily_records.pop(str_date, None)
        json_data = json.dumps(st.session_state.daily_records, ensure_ascii=False)
        components.html(
            f"<script>window.localStorage.setItem('gwangju_ai_attendance', '{json_data}');</script>",
            height=0
        )
        st.warning(f"🗑️ {str_date} 기록이 삭제되었습니다.")
        st.rerun()

st.divider()

# 4. 당월 확정 집계
cal_tardy, cal_early, cal_out, cal_absent, cal_official = 0, 0, 0, 0, 0

for d_str, rec in st.session_state.daily_records.items():
    if datetime.datetime.strptime(d_str, "%Y-%m-%d").date().month == selected_month:
        st_val = rec.get("status", "")
        if st_val == "🏛️ 공가(공결)": cal_official += 1
        elif st_val == "❌ 결석": cal_absent += 1
        elif st_val == "⏰ 지각": cal_tardy += 1
        elif st_val == "🏃 조퇴": cal_early += 1
        elif st_val == "🚶 외출": cal_out += 1

# 5. 가상 시뮬레이터
st.subheader("✏️ 출결 시뮬레이터 (가상 테스트)")

col_in1, col_in2 = st.columns(2)
with col_in1:
    absent_input = int(st.number_input("결석 일수", min_value=0, max_value=20, value=cal_absent, step=1, format="%d"))
    tardy_input = int(st.number_input("지각 횟수", min_value=0, max_value=20, value=cal_tardy, step=1, format="%d"))

with col_in2:
    early_leave_input = int(st.number_input("조퇴 횟수", min_value=0, max_value=20, value=cal_early, step=1, format="%d"))
    out_input = int(st.number_input("외출 횟수", min_value=0, max_value=20, value=cal_out, step=1, format="%d"))

result = attendance.calculate_attendance_tool(
    month=selected_month,
    absent_days=absent_input,
    tardy_count=tardy_input,
    early_leave_count=early_leave_input,
    out_count=out_input,
    official_leave_days=0
)

# 6. 현황판
st.divider()
st.subheader("🚨 생존 현황판")

rem_official_days = max_official_limit - cal_official
st.markdown(f"**🏛️ 공가 잔여:** {rem_official_days}일 / {max_official_limit}일")

rem_tardy = 3 - (tardy_input % 3) if (tardy_input % 3) != 0 else 3
rem_early = 3 - (early_leave_input % 3) if (early_leave_input % 3) != 0 else 3
rem_out = 3 - (out_input % 3) if (out_input % 3) != 0 else 3

st.markdown(f"**⏳ 1결석 전환까지:** 지각 {rem_tardy}회 | 조퇴 {rem_early}회 | 외출 {rem_out}회 남음")

total_days = int(result['total_days'])
target_80_days = int(result['target_80_days'])
max_allowed_absent = total_days - target_80_days

converted_absent = (tardy_input // 3) + (early_leave_input // 3) + (out_input // 3)
net_total_absent = absent_input + converted_absent
remaining_safe_absent = max(0, max_allowed_absent - net_total_absent)

st.metric("현재 출석률", f"{result['attendance_rate']} %")
st.metric("🔥 80% 방어선 남은 결석 가능 일수", f"{remaining_safe_absent}일 남음")

# 7. 선택 월 기준 목록 출력 (20자 초과 시 자동 말줄임표 ... 압축)
st.divider()
st.subheader(f"📜 {selected_month}월 확정 기록 목록")

monthly_records = [
    (d, r) for d, r in st.session_state.daily_records.items()
    if datetime.datetime.strptime(d, "%Y-%m-%d").date().month == selected_month
]

if monthly_records:
    for d_str, rec in sorted(monthly_records):
        st_val = rec.get("status", "🟢 정상출석")
        memo_val = rec.get("memo", "")
        
        # 20자 초과 시 ... 자르기
        display_memo = f"{memo_val[:20]}..." if len(memo_val) > 20 else memo_val
        memo_str = f" | <span style='color:#5F6368;'>📝 {display_memo}</span>" if memo_val else ""
        
        style = BADGE_STYLES.get(st_val, BADGE_STYLES["🟢 정상출석"])
        badge_html = f"<span style='padding:2px 8px; border-radius:12px; font-size:12px; font-weight:bold; {style}'>{st_val}</span>"
        st.markdown(f"• **{d_str}** : {badge_html}{memo_str}", unsafe_allow_html=True)
else:
    st.caption("아직 이번 달에 입력된 확정 기록이 없습니다.")