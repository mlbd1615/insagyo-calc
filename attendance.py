import math
from typing import Dict, Union

# 월별 총 수업일수 (평일 기준)
MONTH_TOTAL_DAYS: Dict[int, int] = {
    5: 17, 6: 21, 7: 22, 8: 20, 9: 20, 10: 21, 11: 21, 12: 9
}

def calculate_attendance_tool(
    month: int,
    absent_days: int = 0,
    tardy_count: int = 0,
    early_leave_count: int = 0,
    out_count: int = 0,
    official_leave_days: int = 0
) -> Dict[str, Union[int, float]]:
    """
    7기 출결 계산 연산 모듈 (보수적 math.ceil 적용)
    """
    assert 5 <= month <= 12, "월은 5~12월 사이여야 합니다."[cite: 2]
    assert absent_days >= 0 and tardy_count >= 0 and early_leave_count >= 0 and out_count >= 0 and official_leave_days >= 0, "입력 수치는 0 이상이어야 합니다."

    total_days: int = MONTH_TOTAL_DAYS.get(month, 20)
    
    tardy_absent: int = tardy_count // 3
    early_leave_absent: int = early_leave_count // 3
    out_absent: int = out_count // 3
    
    total_converted_absent: int = tardy_absent + early_leave_absent + out_absent
    net_absent: int = absent_days + total_converted_absent
    
    raw_calculated_days: int = total_days - net_absent + official_leave_days
    calculated_days: int = min(total_days, max(0, raw_calculated_days))
    
    attendance_rate: float = round((calculated_days / total_days) * 100, 2)
    
    target_50_days: int = math.ceil(total_days * 0.5)[cite: 2]
    target_80_days: int = math.ceil(total_days * 0.8)[cite: 2]
    max_official_leave: int = math.floor(total_days * 0.2)[cite: 2]
    
    return {
        "month": month,
        "total_days": total_days,
        "calculated_days": calculated_days,
        "attendance_rate": attendance_rate,
        "target_50_days": target_50_days,
        "target_80_days": target_80_days,
        "max_official_leave": max_official_leave
    }