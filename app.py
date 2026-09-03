import calendar
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

STATUS_OPTIONS: List[str] = ["🟢 정상출석", "⏰ 지각", "🏃 조퇴", "🚶 외출", "❌ 결석", "🏛️ 공가(공결)"]

# 상태별 색상 단일 소스. 뱃지/캘린더 셀/범례가 전부 이 값 하나만 참조하므로
# 색을 바꾸고 싶으면 여기 한 곳만 고치면 된다 (통일감 유지).
STATUS_COLORS: Dict[str, str] = {
    "🟢 정상출석": "#64748B",
    "⏰ 지각": "#F59E0B",
    "🏃 조퇴": "#8B5CF6",
    "🚶 외출": "#10B981",
    "❌ 결석": "#EF4444",
    "🏛️ 공가(공결)": "#3B82F6",
}

# 일반 달력 관례: 토요일 파란색, 일요일/공휴일 빨간색 (토요일이 공휴일이면 빨간색 우선)
CAL_SATURDAY_COLOR: str = "#2563EB"
CAL_SUNDAY_HOLIDAY_COLOR: str = "#DC2626"

STATUS_SHORT_NAME: Dict[str, str] = {
    "🏛️ 공가(공결)": "공가",
    "❌ 결석": "결석",
    "⏰ 지각": "지각",
    "🏃 조퇴": "조퇴",
    "🚶 외출": "외출",
    "🟢 정상출석": "정상"
}

def badge_style(status: str) -> str:
    """
    color-mix()로 카드 배경(var(--app-bg))에 상태색을 섞어서 배지 배경을
    만든다. 라이트/다크 테마를 따로 정의하지 않아도 Streamlit 테마 변수가 바뀌면
    배지 배경도 자동으로 따라간다.
    """
    color: str = STATUS_COLORS.get(status, STATUS_COLORS["🟢 정상출석"])
    return f"background: color-mix(in srgb, {color} 18%, var(--app-bg)); color:{color}; border:1px solid {color};"

st.set_page_config(page_title="인사교 7기 출결 계산기", page_icon="📱", layout="centered")

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

PIN_BUCKET_KEY: str = "__pins__"
RESERVED_USER_NAMES: set = {"미지정(기존기록)", PIN_BUCKET_KEY}

def register_new_pin(name: str, pin: str) -> bool:
    """
    새로 등록하는 이름의 4자리 비밀번호를 Gist의 __pins__ 버킷에 저장합니다.
    persist_daily_records()와 마찬가지로 저장 직전에 최신 데이터를 다시 읽어와서
    __pins__ 버킷에 이 이름의 항목만 추가하고, 다른 사람의 기록/비밀번호는 그대로 둡니다.
    """
    latest_raw: Optional[Dict[str, Any]] = load_from_gist()
    if latest_raw is None:
        return False
    latest_all_records: Dict[str, Any] = migrate_legacy_format(latest_raw)
    latest_pins: Dict[str, str] = latest_all_records.get(PIN_BUCKET_KEY, {})
    if not isinstance(latest_pins, dict):
        latest_pins = {}
    latest_pins[name] = pin
    latest_all_records[PIN_BUCKET_KEY] = latest_pins
    return save_to_gist(latest_all_records)

if not st.session_state.user_name:
    st.title("📱 인사교 7기 출결 계산기")
    st.info("👋 이름과 4자리 숫자 비밀번호를 입력해주세요. 처음 등록하는 이름이면 그 비밀번호로 새로 등록되고, 이미 있는 이름이면 그때 정한 비밀번호로 본인 확인을 합니다.")

    # 이미 등록된 이름 목록과 비밀번호를 미리 조회 (겹침 확인 + 본인 확인용)
    existing_raw: Optional[Dict[str, Any]] = load_from_gist()
    existing_data: Dict[str, Any] = migrate_legacy_format(existing_raw) if existing_raw is not None else {}
    existing_pins: Dict[str, str] = existing_data.get(PIN_BUCKET_KEY, {})
    if not isinstance(existing_pins, dict):
        existing_pins = {}
    # 기록이 아직 없어도 비밀번호만 등록된 이름은 "이미 존재하는 이름"으로 취급해야
    # 다른 사람이 그 이름을 가로채 비밀번호를 덮어쓰는 걸 막을 수 있다.
    existing_names: set = (
        ({k for k in existing_data.keys() if k != PIN_BUCKET_KEY} | set(existing_pins.keys()))
        if existing_raw is not None else set()
    )

    # 입력마다 "Press Enter to apply"가 뜨는 걸 피하려고 폼으로 묶어서 한 번에 제출받는다.
    with st.form("onboarding_form"):
        name_input: str = st.text_input("이름 / 닉네임")
        pin_input: str = st.text_input(
            "비밀번호 (4자리 숫자)",
            type="password",
            max_chars=4,
            help="처음 등록하는 이름이면 새로 쓸 비밀번호, 이미 있는 이름이면 그때 정한 비밀번호를 입력하세요.",
        )
        submitted: bool = st.form_submit_button("시작하기", type="primary")

    if submitted:
        trimmed_name: str = name_input.strip()
        trimmed_pin: str = pin_input.strip()

        is_reserved: bool = trimmed_name in RESERVED_USER_NAMES
        is_existing: bool = (not is_reserved) and trimmed_name in existing_names
        stored_pin: str = existing_pins.get(trimmed_name, "")
        is_legacy_no_pin: bool = is_existing and stored_pin == ""
        pin_valid_format: bool = trimmed_pin.isdigit() and len(trimmed_pin) == 4

        if trimmed_name == "":
            st.error("이름을 입력해주세요.")
        elif is_reserved:
            st.error(f"❌ '{trimmed_name}'은(는) 사용할 수 없는 이름입니다.")
        elif is_legacy_no_pin:
            st.session_state.user_name = trimmed_name
            st.query_params["user"] = trimmed_name
            st.rerun()
        elif is_existing:
            if not pin_valid_format:
                st.error("비밀번호는 숫자 4자리여야 합니다.")
            elif trimmed_pin != stored_pin:
                st.error("❌ 비밀번호가 틀렸습니다.")
            else:
                st.session_state.user_name = trimmed_name
                st.session_state.user_pin = trimmed_pin
                st.query_params["user"] = trimmed_name
                st.rerun()
        else:
            if not pin_valid_format:
                st.error("새 이름이면 비밀번호를 숫자 4자리로 정해주세요.")
            else:
                st.session_state.user_name = trimmed_name
                # Gist에 왕복해서 다시 읽어와야 알 수 있는 값이 아니라 방금 입력받은
                # 값을 바로 세션에 넣는다 — 비밀번호 찾기/변경 기능이 없는 앱이라
                # 로그인 직후 화면에 비밀번호를 계속 보여줘야 하는데, 저장을
                # 못 읽어오는 타이밍(서버 미설정 등)에도 안 끊기도록 하기 위함.
                st.session_state.user_pin = trimmed_pin
                st.query_params["user"] = trimmed_name
                register_new_pin(trimmed_name, trimmed_pin)
                st.rerun()
    st.stop()

if st.query_params.get("user") != st.session_state.user_name:
    st.query_params["user"] = st.session_state.user_name

# 세션 데이터 로드 (전체 사용자 데이터 -> 현재 사용자 기록만 분리)
if "all_records" not in st.session_state:
    st.session_state.all_records = migrate_legacy_format(load_from_gist() or {})
if "daily_records" not in st.session_state:
    st.session_state.daily_records = st.session_state.all_records.get(st.session_state.user_name, {})
if "user_pin" not in st.session_state:
    pins_bucket: Dict[str, str] = st.session_state.all_records.get(PIN_BUCKET_KEY, {})
    if not isinstance(pins_bucket, dict):
        pins_bucket = {}
    st.session_state.user_pin = pins_bucket.get(st.session_state.user_name)

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

def delete_user_account(name: str) -> bool:
    """
    Gist에서 해당 이름의 기록과 비밀번호를 완전히 삭제합니다. 최신 데이터를 다시
    읽어와 이 이름의 항목만 제거하고 다른 사람 데이터는 그대로 둔 채 저장합니다.
    """
    latest_raw: Optional[Dict[str, Any]] = load_from_gist()
    if latest_raw is None:
        return False
    latest_all_records: Dict[str, Any] = migrate_legacy_format(latest_raw)
    latest_all_records.pop(name, None)
    latest_pins: Dict[str, str] = latest_all_records.get(PIN_BUCKET_KEY, {})
    if isinstance(latest_pins, dict):
        latest_pins.pop(name, None)
        latest_all_records[PIN_BUCKET_KEY] = latest_pins
    return save_to_gist(latest_all_records)

def queue_toast(message: str, icon: str = "✅") -> None:
    """
    st.rerun() 직전에 호출해서 메시지를 세션에 담아두면, 리런 직후 화면 맨 위에서
    한 번 st.toast()로 띄우고 지운다. st.success/st.error를 화면에 계속 눌러앉히는
    대신 잠깐 떴다 사라지는 형태라 저장/삭제할 때마다 화면이 덜컹거리지 않는다.
    """
    st.session_state["_pending_toast"] = (message, icon)

if "_pending_toast" in st.session_state:
    _toast_message, _toast_icon = st.session_state.pop("_pending_toast")
    st.toast(_toast_message, icon=_toast_icon)

if "_cal_popover_gen" not in st.session_state:
    st.session_state._cal_popover_gen = {}

def cal_popover_key(d_str: str) -> str:
    """
    st.popover는 내부에서 발생한 리런(예: 저장 버튼 클릭)에서는 열림 상태를
    그대로 유지한다 — 저장은 되는데 팝오버가 안 닫힌 채로 남는 이유. 저장/
    삭제 직후 이 날짜의 세대(generation)를 올려 key를 바꾸면, 다음 렌더링에서
    완전히 새 위젯으로 취급돼 기본값(닫힘)으로 다시 그려진다.
    """
    gen = st.session_state._cal_popover_gen.get(d_str, 0)
    return f"cal_{d_str}_{gen}"

def bump_cal_popover_gen(d_str: str) -> None:
    st.session_state._cal_popover_gen[d_str] = st.session_state._cal_popover_gen.get(d_str, 0) + 1

def delete_record_by_key(target_key: str) -> None:
    """
    지정된 날짜 키의 기록을 삭제하고 GitHub Private Gist에 동기화합니다.
    """
    assert isinstance(target_key, str), "target_key는 반드시 문자열 형태여야 합니다."
    if target_key in st.session_state.daily_records:
        st.session_state.daily_records.pop(target_key, None)
        ok: bool = persist_daily_records()
        queue_toast(
            f"{target_key} 기록이 삭제되었습니다." if ok else "⚠️ 서버 저장에 실패했습니다.",
            "🗑️" if ok else "⚠️",
        )
        bump_cal_popover_gen(target_key)
        st.rerun()

# 반응형 + 다크모드 대응 CSS. 색상은 하드코딩된 hex 대신 Streamlit이 노출하는
# 테마 CSS 변수(--background-color, --text-color 등)를 기준으로 계산해서,
# 사용자가 라이트/다크 테마를 바꿔도 카드·배지·캘린더가 따로 안 깨지게 한다.
# key로 만든 위젯은 래퍼 요소에 "st-key-<key>" 클래스가 붙는다 — key 값 자체가
# HTML 속성으로 노출되는 게 아니므로 button[key=...] 같은 선택자는 매치되지 않는다.
st.markdown("""
<style>
/* Streamlit이 문서 전체에 --background-color/--text-color 같은 테마 CSS
   변수를 노출해줄 거라 가정하고 만들었는데, 실제로는(이 버전 기준) 그런
   변수가 어디에도 정의돼 있지 않았다 — var(--app-text)가 그냥 빈 값이라
   color-mix()가 전부 무효 처리되면서 카드 배경/테두리/게이지가 투명하게
   사라지는 등 조용히 깨져 있었다. 실제 렌더링된 색(개발자 도구로 직접
   확인: 라이트 bg #FFFFFF / 텍스트 #31333F, 다크 bg #0E1117 / 텍스트 #FAFAFA,
   보조 배경 라이트 #F0F2F6 / 다크 #262730, 기본 강조색 #FF4B4B)을 기준으로
   직접 변수를 선언하고, prefers-color-scheme으로 다크모드를 전환한다.
   (이 프로젝트엔 .streamlit/config.toml에 고정 테마 설정이 없어서 Streamlit
   자체도 시스템 설정을 그대로 따른다 — 다크 모드로 새로고침하면 실제로
   본문 배경이 저 값으로 바뀌는 것까지 확인했다.) */
:root {
    --app-bg: #FFFFFF;
    --app-secondary-bg: #F0F2F6;
    --app-text: #31333F;
    --app-primary: #FF4B4B;
}
@media (prefers-color-scheme: dark) {
    :root {
        --app-bg: #0E1117;
        --app-secondary-bg: #262730;
        --app-text: #FAFAFA;
    }
}
/* Streamlit 기본 폰트 스택("Source Sans", sans-serif)은 한글을 지원하지
   않는다. 그래서 브라우저가 한글 글자마다 시스템 대체 폰트로 폴백하는데,
   환경에 따라 그 대체 폰트가 완성형 한글 음절(받침 포함)을 제대로 그리지
   못해 획이 깨져 보이는 경우가 있었다 — 완전히 빈 <div>에 아무 커스텀
   CSS 없이 넣어봐도 동일하게 깨져서, 레이아웃이 아니라 폰트 폴백이
   원인임을 확인했다. 실제 한글 폰트를 앞순위로 명시해 해결한다. */
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] * {
    font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", "Source Sans", sans-serif !important;
}
/* 위 규칙이 아이콘 폰트(Material Symbols 리거처)까지 덮어써서 화살표 아이콘이
   "expand_more" 같은 글자 그대로 보이는 부작용이 있었다 — 아이콘 요소는
   원래 아이콘 폰트를 쓰도록 되돌린다. */
[data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
}
.metric-card {
    background: var(--app-secondary-bg);
    border: 1px solid color-mix(in srgb, var(--app-text) 15%, transparent);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    border-radius: 12px;
    padding: clamp(14px, 3vw, 20px);
    margin-bottom: 16px;
}
.metric-header {
    font-size: clamp(16px, 4vw, 18px);
    font-weight: 700;
    color: var(--app-text);
    margin-bottom: 12px;
}
.gauge-rate-label {
    font-size: clamp(30px, 8vw, 38px);
    font-weight: 800;
    line-height: 1;
}
/* 게이지 트랙 자체에 테두리를 둘러서 "여기까지가 100%"라는 전체 범위가
   항상 뚜렷하게 보이게 한다 (막대 색만으로는 어디가 끝인지 애매했다).
   50%/80% 기준선은 실선 대신 점선으로 그어 채워진 막대와 구분되면서도
   "지금 그 기준을 지났는지"를 바로 알 수 있게 한다. */
.gauge-track {
    position: relative;
    width: 100%;
    height: 14px;
    border-radius: 7px;
    background: color-mix(in srgb, var(--app-text) 8%, transparent);
    border: 2px solid color-mix(in srgb, var(--app-text) 45%, transparent);
    box-sizing: border-box;
    /* 아래 여백(46px)이 두 줄짜리 라벨("50%\n주거지원비" 등)을 다 담기엔
       부족해서, 라벨 텍스트가 이 카드 다음 요소(metric-footer)의 점선
       윗테두리와 실제로 겹쳐 보였다 — 실측: 라벨 하단이 footer 윗테두리보다
       약 12px 더 아래까지 내려와 있었다. 여유 있게 키운다. */
    margin: 12px 0 62px 0;
}
.gauge-fill {
    height: 100%;
    border-radius: 5px;
    transition: width 0.4s ease;
}
/* border-left:dashed 대신 반복 그라디언트로 점선을 직접 그린다 — 폭 0인
   요소의 좌측 테두리로 점선을 표현하는 방식이 일부 환경에서 라벨 텍스트
   쪽으로 얼룩처럼 번져 보인다는 제보가 있어, 렌더링 결과가 더 예측 가능한
   방식으로 바꿨다. 트랙 높이 안에서만 그려지고 라벨과는 확실히 떨어뜨린다. */
.gauge-marker {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background-image: repeating-linear-gradient(
        to bottom,
        color-mix(in srgb, var(--app-text) 55%, transparent) 0,
        color-mix(in srgb, var(--app-text) 55%, transparent) 3px,
        transparent 3px,
        transparent 6px
    );
}
.gauge-marker-label {
    position: absolute;
    top: 28px;
    transform: translateX(-50%);
    font-size: clamp(10px, 2.4vw, 11px);
    color: color-mix(in srgb, var(--app-text) 62%, var(--app-bg));
    white-space: nowrap;
    text-align: center;
    line-height: 1.5;
}
/* 100% 라벨은 트랙 오른쪽 끝에 붙으므로 -50% 중앙정렬 대신 오른쪽 기준으로
   앵커링한다. 트랙 테두리 자체가 100% 경계를 보여주므로 별도 눈금선은
   필요 없다. */
.gauge-end-label {
    left: 100% !important;
    transform: translateX(-100%) !important;
}
.metric-footer {
    border-top: 1px dashed color-mix(in srgb, var(--app-text) 20%, transparent);
    padding-top: 10px;
    font-size: clamp(13px, 3vw, 14px);
    color: var(--app-text);
    line-height: 1.7;
}
.legend-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 14px;
    margin: 4px 0 14px 0;
}
.legend-item {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: clamp(11px, 2.6vw, 12px);
    color: color-mix(in srgb, var(--app-text) 82%, var(--app-bg));
}
.legend-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}
/* 요일 헤더: DOM에는 정확한 글자("월" 등)가 들어있고 CSS 박스 크기도 충분한데도
   화면에는 받침이 잘린 것처럼 보이는 증상이 계속 재현됐다 — 커스텀 div든
   Streamlit 기본 <p>든 동일하게 발생해서 레이아웃 문제는 아니고, 13px 안팎의
   작은 한글 글자가 특정 PC/브라우저의 서브픽셀 힌팅에서 획이 뭉개지는, 흔히
   보고되는 종류의 문제로 보인다. 굵게(볼드)도 합성 폰트 획을 더 뭉개는 요인이라
   같이 뺐고, 가장 확실한 완화책인 폰트 크기를 눈에 띄게 키웠다.*/
.st-key-calendar_weekday_header p {
    text-align: center !important;
    font-size: 16px !important;
    font-weight: 400 !important;
    line-height: 1.6 !important;
    color: color-mix(in srgb, var(--app-text) 62%, var(--app-bg)) !important;
    margin: 0 !important;
}
.cal-off-day {
    text-align: center;
    font-size: 13px;
    line-height: 30px;
    height: 30px;
}
/* 캘린더 날짜 칸: 꽉 찬 사각 버튼 대신 작은 원형 칩으로 — 글자만 살짝 강조되게
   타이트하게 잡는다. 팝오버 트리거에 기본으로 붙는 화살표 아이콘은 좁은 칸에서
   숫자 옆에 붙어 거슬리므로 함께 숨긴다. */
[class*="st-key-cal_"] button[data-testid="stPopoverButton"] {
    padding: 0 !important;
    width: 30px !important;
    height: 30px !important;
    min-width: 30px !important;
    min-height: 30px !important;
    max-width: 30px !important;
    margin: 0 auto !important;
    font-size: 13px !important;
    border-radius: 50% !important;
    background: transparent !important;
    border: 1px solid transparent !important;
}
[class*="st-key-cal_"] button[data-testid="stPopoverButton"] > div {
    justify-content: center !important;
    gap: 0 !important;
    padding: 0 !important;
}
[class*="st-key-cal_"] button[data-testid="stPopoverButton"] div[aria-hidden="true"] {
    display: none !important;
}
/* <p>를 감싸는 stMarkdownContainer가 overflow:hidden에 높이도 22.4px로
   고정돼 있어서, 숫자를 광학 중심으로 밀면(아래 position 규칙) 그 위쪽이
   이 박스 경계에 잘려 숫자 윗부분이 사라져 보였다("8"이 "3"처럼 보이는
   증상). 미는 상태에서도 절대 안 잘리도록 이 박스의 클리핑을 풀어준다. */
[class*="st-key-cal_"] button[data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"] {
    overflow: visible !important;
    height: auto !important;
}
[class*="st-key-cal_"] button[data-testid="stPopoverButton"] p {
    margin: 0 !important;
    font-size: 13px !important;
    /* 박스 자체는 이미 정중앙인데(측정상 0.4px 이내), line-height가
       13px 글자에 비해 훨씬 커서(20.8px) 그 여백(leading)이 글자 위아래에
       똑같이 안 붙는다 — 숫자는 내려오는 획(g, y 같은 디센더)이 없어서
       육안으로는 살짝 위로 뜬 것처럼 보인다. line-height를 1로 줄여서
       그 여백 자체를 없애는 게 광학적으로 더 정확히 중앙에 맞는다. */
    line-height: 1 !important;
    /* line-height:1 이후에도 숫자 잉크 중심이 원의 기하학적 중심보다
       오른쪽 2.5px·아래 4.7px에 있는 걸 실측으로 확인했다(1,7,8,9 전부
       동일 — 숫자 모양 차이가 아니라 숨겨진 아이콘 자리 등 구조적인 치우침).
       transform으로 밀어봤더니 겉보기엔 적용됐는데(computed style 확인)
       실제 위치/측정치가 전혀 안 바뀌는 이상한 현상이 있어서, layout에
       직접 관여하는 position:relative + left/top으로 대신 민다. */
    position: relative;
    left: -2.5px;
    top: -4.7px;
}
.st-key-btn_act_switch button, .st-key-btn_act_del button {
    padding: 2px 8px !important;
    font-size: clamp(10px, 2.6vw, 12px) !important;
    min-height: 28px !important;
    height: 28px !important;
}
</style>
""", unsafe_allow_html=True)

# 제목 / 계정 정보 / 전환·삭제 버튼을 각각 별도 줄에 둔다. 한 줄에 같이 넣으면
# 좁은 화면에서 계정 정보 텍스트가 버튼 칸을 침범해 버튼에 가려지는 문제가 있었다.
st.markdown("#### 📱 인사교 7기 출결 계산기")

pin_suffix: str = f" (🔑 {st.session_state.user_pin})" if st.session_state.user_pin else ""
# st.caption(≈14px)보다 확실히 크게 보이도록 글자 크기를 직접 지정한다.
# 줄바꿈을 막지 않아야 좁은 화면에서 다음 줄로 넘어가고, 옆 요소를 침범하지 않는다.
st.markdown(
    f'<div style="font-size:17px; font-weight:600; color:var(--app-text);">'
    f'👤 {st.session_state.user_name}{pin_suffix}</div>',
    unsafe_allow_html=True,
)

# 동일 비율(1,1,6)로 나눈 컬럼은 버튼 폭과 무관하게 컬럼 자체가 넓어서, 버튼이
# 왼쪽 정렬되더라도 두 버튼 사이에 빈 여백이 크게 남아 "동떨어져" 보였다.
# 이 컨테이너 안에서만 컬럼을 내용 너비만큼만 차지하게(flex: 0 0 auto) 풀어서
# 버튼 두 개가 서로 바짝 붙게 만든다.
st.markdown("""
<style>
.st-key-account_actions [data-testid="stHorizontalBlock"] {
    gap: 8px !important;
}
.st-key-account_actions [data-testid="stColumn"] {
    min-width: 0 !important;
    width: auto !important;
    flex: 0 0 auto !important;
}
</style>
""", unsafe_allow_html=True)

with st.container(key="account_actions"):
    act_col1, act_col2 = st.columns(2, wrap=False)
    with act_col1:
        if st.button("🔄 전환", key="btn_act_switch", help="다른 사람으로 전환 (이름을 지우고 다시 입력합니다)"):
            del st.query_params["user"]
            del st.session_state["user_name"]
            del st.session_state["daily_records"]
            del st.session_state["all_records"]
            st.session_state.pop("user_pin", None)
            st.rerun()
    with act_col2:
        if st.button("🗑️ 삭제", key="btn_act_del", help="현재 계정(이름/기록/비밀번호)을 서버에서 완전히 삭제합니다."):
            st.session_state.confirm_delete_account = True
            st.rerun()

if st.session_state.get("confirm_delete_account"):
    st.warning(f"⚠️ '{st.session_state.user_name}' 계정의 기록과 비밀번호를 서버에서 영구 삭제합니다. 되돌릴 수 없습니다.")
    dc1, dc2 = st.columns(2)
    with dc1:
        if st.button("✅ 정말 삭제", type="primary", use_container_width=True):
            deleted_name: str = st.session_state.user_name
            deleted_ok: bool = delete_user_account(deleted_name)
            del st.query_params["user"]
            del st.session_state["user_name"]
            del st.session_state["daily_records"]
            del st.session_state["all_records"]
            st.session_state.pop("user_pin", None)
            st.session_state.pop("confirm_delete_account", None)
            if deleted_ok:
                st.success(f"'{deleted_name}' 계정이 삭제되었습니다.")
            else:
                st.error("삭제에 실패했습니다. 잠시 후 다시 시도해주세요.")
            st.rerun()
    with dc2:
        if st.button("취소", use_container_width=True):
            st.session_state.pop("confirm_delete_account", None)
            st.rerun()

st.caption("💡 지금 이 페이지 주소를 즐겨찾기/북마크해두면, 다음에 그 링크로 들어올 때 자동으로 본인 기록이 열립니다.")

if not GITHUB_TOKEN or not GIST_ID:
    st.warning("⚠️ 서버 저장이 설정되어 있지 않습니다 (GITHUB_TOKEN/GIST_ID 미설정). 지금 입력하는 기록은 이 화면을 벗어나면 사라집니다.")

# 1. 조회 월 상태
today: datetime.date = datetime.date.today()
CAL_YEAR: int = 2026
MONTH_OPTIONS: List[int] = [5, 6, 7, 8, 9, 10, 11, 12]

if "selected_month" not in st.session_state:
    st.session_state.selected_month = max(5, min(12, today.month))

selected_month: int = st.session_state.selected_month

base_info: Dict[str, Any] = attendance.calculate_attendance_tool(month=selected_month)
max_official_limit: int = int(base_info['max_official_leave'])

# 2. 📊 출결 현황판 (헤더는 카드 안에 포함 — 아래 st.markdown 카드 참고)
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

total_days: int = int(result['total_days'])
target_80_days: int = int(result['target_80_days'])
max_allowed_absent: int = total_days - target_80_days

converted_absent: int = (cal_tardy // 3) + (cal_early // 3) + (cal_out // 3)
net_total_absent: int = cal_absent + converted_absent
remaining_safe_absent: int = max(0, max_allowed_absent - net_total_absent)

rem_official_days: int = max_official_limit - cal_official
rem_tardy: int = 3 - (cal_tardy % 3) if (cal_tardy % 3) != 0 else 3
rem_early: int = 3 - (cal_early % 3) if (cal_early % 3) != 0 else 3
rem_out: int = 3 - (cal_out % 3) if (cal_out % 3) != 0 else 3

# 출결률 게이지: 지원금 지급 기준(식비·교통비 80%, 주거지원비 50%)을 그대로
# 눈금으로 표시한다. 숫자만 보는 것보다 "그 기준까지 얼마나 남았는지"가 바로
# 보여서, 매번 상주멘토님께 물어보지 않고도 스스로 감을 잡을 수 있다.
attendance_rate: float = float(result['attendance_rate'])
gauge_fill_pct: float = max(0.0, min(100.0, attendance_rate))
if attendance_rate < 50:
    zone_color: str = "#EF4444"
elif attendance_rate < 80:
    zone_color = "#F59E0B"
else:
    zone_color = "#10B981"

st.markdown(f"""
<div class="metric-card">
    <div class="metric-header">📊 {selected_month}월 출결 현황판</div>
    <div class="gauge-rate-label" style="color:{zone_color};">{attendance_rate}%</div>
    <div class="gauge-track">
        <div class="gauge-fill" style="width:{gauge_fill_pct}%; background:{zone_color};"></div>
        <div class="gauge-marker" style="left:50%;"></div>
        <div class="gauge-marker-label" style="left:50%;">50%<br>주거지원비</div>
        <div class="gauge-marker" style="left:80%;"></div>
        <div class="gauge-marker-label" style="left:80%;">80%<br>식비·교통비</div>
        <div class="gauge-marker-label gauge-end-label">100%</div>
    </div>
    <div class="metric-footer">
        <div>🔥 <b>남은 결석 가능:</b> {remaining_safe_absent}일</div>
        <div>🏛️ <b>공가 사용:</b> {cal_official}/{max_official_limit}일 (남은 찬스 {rem_official_days}일)</div>
        <div>⏳ <b>차감 잔여:</b> 지각 <b>{rem_tardy}회</b> · 조퇴 <b>{rem_early}회</b> · 외출 <b>{rem_out}회</b></div>
    </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# 3. 🗓️ 출결 캘린더 — 날짜 선택과 상태 입력을 한 번에 처리한다.
# 요일 칸을 눌러 나오는 팝오버 안에서 바로 상태/메모를 고르고 저장한다.
with st.popover(f"📅 {selected_month}월 조회"):
    # st.columns는 wrap=False여도 컬럼별 최소 폭이 있어 8개를 다 넣으면 옆으로
    # 퍼진다. 폭에 맞게 알아서 줄바꿈되는 st.pills로 대체 — 순서도 안 꼬인다.
    picked_month = st.pills(
        "월 선택",
        options=MONTH_OPTIONS,
        format_func=lambda m: f"{m}월",
        default=selected_month,
        label_visibility="collapsed",
    )
    if picked_month is not None and picked_month != selected_month:
        st.session_state.selected_month = picked_month
        st.rerun()

st.markdown(f"#### 🗓️ {selected_month}월 출결 캘린더")

legend_html: str = "".join(
    f'<div class="legend-item"><span class="legend-dot" style="background:{STATUS_COLORS[s]};"></span>{STATUS_SHORT_NAME[s]}</div>'
    for s in STATUS_OPTIONS
)
st.markdown(f'<div class="legend-row">{legend_html}</div>', unsafe_allow_html=True)
st.caption("👆 날짜를 눌러 그 자리에서 출결을 입력하세요. 주말/공휴일은 비활성화됩니다.")

def render_day_editor(d_str: str, month_of_day: int) -> None:
    """
    캘린더 한 칸(팝오버) 안에 들어가는 상태 선택 + 메모 + 저장/삭제 UI.
    기존에 날짜 선택(date_input)과 상태 선택이 분리돼 있던 2단계 흐름을,
    캘린더 클릭 한 번으로 합친 것.
    """
    rec: Dict[str, Any] = st.session_state.daily_records.get(d_str, {"status": "🟢 정상출석", "memo": ""})
    st.markdown(f"**{d_str}**")

    curr_idx: int = STATUS_OPTIONS.index(rec["status"]) if rec["status"] in STATUS_OPTIONS else 0
    in_status: str = st.selectbox("출결 상태", options=STATUS_OPTIONS, index=curr_idx, key=f"status_{d_str}")
    in_memo: str = st.text_input("메모 (선택, 최대 50자)", value=rec.get("memo", ""), max_chars=50, key=f"memo_{d_str}")

    month_limit: int = int(attendance.calculate_attendance_tool(month=month_of_day)['max_official_leave'])
    current_used_official: int = sum(
        1 for ds, r in st.session_state.daily_records.items()
        if ds.startswith(f"{CAL_YEAR}-{month_of_day:02d}") and r.get("status") == "🏛️ 공가(공결)" and ds != d_str
    )

    ec1, ec2 = st.columns(2)
    with ec1:
        if st.button("💾 저장", type="primary", use_container_width=True, key=f"save_{d_str}"):
            if in_status == "🏛️ 공가(공결)" and (current_used_official + 1 > month_limit):
                st.error(f"❌ 이번 달 최대 공가 한도({month_limit}일)를 초과할 수 없습니다!")
            else:
                st.session_state.daily_records[d_str] = {"status": in_status, "memo": in_memo.strip()}
                ok: bool = persist_daily_records()
                queue_toast(
                    f"{d_str} 저장되었습니다." if ok else "⚠️ 서버 저장에 실패했습니다.",
                    "✅" if ok else "⚠️",
                )
                bump_cal_popover_gen(d_str)
                st.rerun()
    with ec2:
        has_record: bool = d_str in st.session_state.daily_records
        if st.button("🗑️ 삭제", use_container_width=True, disabled=not has_record, key=f"del_{d_str}"):
            delete_record_by_key(target_key=d_str)

# 보통 달력처럼 일요일부터 시작 (Python calendar 기본값은 월요일 시작이라
# firstweekday=6(일요일)로 바꿔서 받는다). 이 순서에서는 wd_idx 0=일, 6=토.
month_weeks: List[List[int]] = calendar.Calendar(firstweekday=6).monthdayscalendar(CAL_YEAR, selected_month)
WEEKDAY_LABELS: List[str] = ["일", "월", "화", "수", "목", "금", "토"]
today_str: str = today.strftime("%Y-%m-%d")

# 날짜별 색은 매번 값이 다르므로, CSS 클래스가 아니라 날짜 키(st-key-cal_YYYY-MM-DD)를
# 겨냥한 규칙을 그때그때 만들어서 한 번에 주입한다.
day_css_rules: List[str] = []
for week in month_weeks:
    for wd_idx, day_num in enumerate(week):
        if day_num == 0:
            continue
        d_str = f"{CAL_YEAR}-{selected_month:02d}-{day_num:02d}"
        is_off: bool = (wd_idx == 0) or (wd_idx == 6) or (d_str in HOLIDAYS_2026)
        if is_off:
            continue
        rec = st.session_state.daily_records.get(d_str)
        # 아래쪽 기본 스타일 규칙(`[class*="st-key-cal_"] button[data-testid="stPopoverButton"]`)이
        # 속성 선택자를 두 개 써서 이 규칙보다 CSS 명시도가 더 높다 — 둘 다 !important라
        # 명시도가 낮은 쪽은 순서와 무관하게 진다. 같은 속성 선택자를 붙여 명시도를
        # 맞춰야 매일 바뀌는 이 색상 규칙이 실제로 적용된다.
        selector = f'.st-key-{cal_popover_key(d_str)} button[data-testid="stPopoverButton"]'
        if rec:
            # 옅은 틴트 배경 + 색 글씨 조합은 눈에 잘 안 띈다는 피드백을 받아,
            # 원래대로 원 전체를 상태색으로 채우고 글자는 흰색으로 — 작은 원이라
            # 꽉 채워도 "칸이 커 보인다"는 문제는 이제 없다 (30px 원형이라서).
            color = STATUS_COLORS.get(rec.get("status", "🟢 정상출석"), STATUS_COLORS["🟢 정상출석"])
            rule = (
                f'{selector} {{'
                f'background: {color} !important;'
                f'border: 1px solid {color} !important;'
                f'color: #FFFFFF !important;'
                f'font-weight: 700 !important;'
                f'}}'
            )
        else:
            is_past: bool = d_str < today_str
            border_style: str = "dashed" if is_past else "solid"
            rule = (
                f'{selector} {{'
                f'background: transparent !important;'
                f'border: 1px {border_style} color-mix(in srgb, var(--app-text) 30%, transparent) !important;'
                f'color: color-mix(in srgb, var(--app-text) 80%, var(--app-bg)) !important;'
                f'}}'
            )
        if d_str == today_str:
            rule += f'{selector} {{ box-shadow: 0 0 0 2px var(--app-primary) inset !important; }}'
        day_css_rules.append(rule)

st.markdown(f"<style>{''.join(day_css_rules)}</style>", unsafe_allow_html=True)

# wrap=False가 없으면 좁은 화면에서 st.columns(7)이 가로 정렬을 포기하고
# 한 칸씩 세로로 쌓여버려서 캘린더가 아니라 긴 목록이 돼버린다 (기존 월 선택
# 그리드에서 이미 겪었던 문제와 동일). wrap=False만으로는 컬럼별 기본 최소 폭
# 때문에 7칸이 화면 밖으로 밀려나므로, 이 컨테이너 안에서만 최소 폭을 0으로
# 풀어준다 (다른 곳의 2~3칸 레이아웃 비율은 건드리지 않기 위해 범위를 좁힌다).
st.markdown("""
<style>
.st-key-calendar_grid [data-testid="stColumn"] {
    min-width: 0 !important;
    flex: 1 1 0 !important;
}
.st-key-calendar_grid [data-testid="stHorizontalBlock"] {
    gap: 4px !important;
}
/* Streamlit이 각 행(stHorizontalBlock)에 자체적으로 overflow-y:auto와
   고정 높이를 준다 — 원래는 안쪽 위젯이 그 높이보다 커질 일이 거의 없어서
   안 보이던 것인데, 30px 원형 칩이 그 높이를 몇 px 넘기면서 줄마다 세로
   스크롤바가 생겼다. 행 높이를 내용에 맞춰 자동으로 늘어나게 한다. */
.st-key-calendar_grid [data-testid="stHorizontalBlock"] {
    height: auto !important;
    overflow: visible !important;
}
/* 버튼 칸(팝오버)과 일반 텍스트 칸(주말/공휴일)이 서로 다른 위젯이라 기본
   여백이 달라서 같은 줄인데 세로로 안 맞았다 — 행/칸 모두 flex 중앙 정렬로
   맞춘다(위아래·좌우 모두). */
.st-key-calendar_grid [data-testid="stHorizontalBlock"] {
    align-items: center !important;
}
.st-key-calendar_grid [data-testid="stColumn"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    text-align: center !important;
}
.st-key-calendar_grid [data-testid="stColumn"] > div {
    width: 100%;
}
/* justify-content:center는 컬럼의 바로 아래 자식(위 규칙으로 폭 100%가 된
   래퍼 div) 자체를 가운데 놓을 뿐이다 — 그 안의 버튼(팝오버 트리거, 30px
   고정폭)은 인라인 요소라 부모의 justify-content가 아니라 text-align을
   따른다. 상속되는 text-align:center를 컬럼에서 걸어야 버튼도 실제로
   가운데 온다 (숫자만 있는 주말/공휴일 텍스트 칸은 원래도 폭 100%라 이미
   중앙정렬돼 보였을 뿐, 버튼 칸만 왼쪽으로 치우쳐 있었다). */
</style>
""", unsafe_allow_html=True)

with st.container(key="calendar_grid"):
    with st.container(key="calendar_weekday_header"):
        wd_header_cols = st.columns(7, wrap=False, gap="small")
        for wd_idx, label in enumerate(WEEKDAY_LABELS):
            with wd_header_cols[wd_idx]:
                st.markdown(label)

    for week in month_weeks:
        week_cols = st.columns(7, wrap=False, gap="small")
        for wd_idx, day_num in enumerate(week):
            with week_cols[wd_idx]:
                if day_num == 0:
                    st.write("")
                    continue
                d_str = f"{CAL_YEAR}-{selected_month:02d}-{day_num:02d}"
                is_sunday = wd_idx == 0
                is_saturday = wd_idx == 6
                is_holiday = d_str in HOLIDAYS_2026
                # 공휴일이 토요일과 겹치는 경우까지 포함해 빨간색이 우선한다.
                if is_sunday or is_holiday:
                    st.markdown(
                        f'<div class="cal-off-day" style="color:{CAL_SUNDAY_HOLIDAY_COLOR};">{day_num}</div>',
                        unsafe_allow_html=True,
                    )
                    continue
                if is_saturday:
                    st.markdown(
                        f'<div class="cal-off-day" style="color:{CAL_SATURDAY_COLOR};">{day_num}</div>',
                        unsafe_allow_html=True,
                    )
                    continue
                with st.popover(str(day_num), use_container_width=True, key=cal_popover_key(d_str)):
                    render_day_editor(d_str, selected_month)

st.divider()

# 4. 가상 시뮬레이터
st.markdown("#### ✏️ 출결 시뮬레이터")

col_in1, col_in2 = st.columns(2, wrap=False)
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

# 5. 선택 월 기준 목록 출력 (상세 확인/삭제용 — 평소엔 캘린더로 충분하니 접어둔다)
monthly_records: List[Tuple[str, Dict[str, Any]]] = [
    (d, r) for d, r in st.session_state.daily_records.items()
    if datetime.datetime.strptime(d, "%Y-%m-%d").date().month == selected_month
]

with st.expander(f"📜 {selected_month}월 출결 기록 목록으로 보기 ({len(monthly_records)}건)", expanded=False):
    if monthly_records:
        sort_order: str = st.segmented_control(
            "정렬 순서",
            options=["최신순", "오래된순"],
            default="최신순",
            label_visibility="collapsed",
        ) or "최신순"

        # 유형별 인덱스(지각1, 지각2 ...)는 화면에 보여주는 정렬 순서와 상관없이
        # 항상 날짜 오름차순(오래된 것부터) 기준으로 매겨야 "1번째"라는 의미가 맞다.
        chronological_records: List[Tuple[str, Dict[str, Any]]] = sorted(monthly_records)
        status_running_count: Dict[str, int] = {}
        index_labels: Dict[str, str] = {}
        for d_str, rec in chronological_records:
            st_val: str = rec.get("status", "🟢 정상출석")
            status_running_count[st_val] = status_running_count.get(st_val, 0) + 1
            index_labels[d_str] = f"{STATUS_SHORT_NAME.get(st_val, st_val)}{status_running_count[st_val]}"

        display_records: List[Tuple[str, Dict[str, Any]]] = (
            chronological_records if sort_order == "오래된순" else list(reversed(chronological_records))
        )

        for d_str, rec in display_records:
            st_val = rec.get("status", "🟢 정상출석")
            index_label: str = index_labels[d_str]

            with st.container(border=True):
                col_idx, col_text, col_del = st.columns([1.3, 7.2, 1.5])

                with col_idx:
                    st.markdown(f"**{index_label}**")

                memo_val: str = rec.get("memo", "")
                display_memo: str = f"{memo_val[:15]}..." if len(memo_val) > 15 else memo_val
                memo_str: str = f" | <span style='opacity:0.65;'>📝 {display_memo}</span>" if memo_val else ""

                style: str = badge_style(st_val)
                badge_html: str = f"<span style='padding:2px 8px; border-radius:12px; font-size:12px; font-weight:bold; {style}'>{st_val}</span>"

                with col_text:
                    st.markdown(f"**{d_str}** : {badge_html}{memo_str}", unsafe_allow_html=True)

                with col_del:
                    if st.button("삭제", type="tertiary", key=f"btn_del_{d_str}", help=f"{d_str} 기록 삭제"):
                        delete_record_by_key(target_key=d_str)
    else:
        st.caption("아직 이번 달에 입력된 확정 기록이 없습니다.")
