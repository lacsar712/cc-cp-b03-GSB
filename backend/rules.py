"""冷链探头读数判定：摄氏温度不超过 8 为合格，否则超温。"""

# 入队后须经另一名记录员确认才可被认领：
# unconfirmed（待确认）-> pending（已确认，等待认领）-> processing -> done
STATUS_UNCONFIRMED = "unconfirmed"
STATUS_CONFIRMED = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"

# 流水动作
ACTION_CREATED = "created"
ACTION_CONFIRMED = "confirmed"


def judge_temp(temp_c: float) -> tuple[str, str]:
    if temp_c <= 8:
        return "合格", "探头温度未超过 8℃ 上限"
    return "超温", "探头温度超过 8℃ 冷链上限"


def verdict_for_display(verdict: str | None, status: str) -> str:
    if verdict:
        return verdict
    if status == STATUS_UNCONFIRMED:
        return "待确认"
    if status == STATUS_CONFIRMED:
        return "待处理"
    if status == STATUS_PROCESSING:
        return "处理中"
    return "—"
