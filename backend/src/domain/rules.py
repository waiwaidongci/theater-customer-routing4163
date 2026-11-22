"""分流规则版本的解析与到件时刻匹配。

规则版本以（生效时刻， 签发序号）定位：到件时刻不早于生效时刻的版本可用，
同一生效时刻的变更按签发序号取唯一版本（序号大的生效）。
"""

from datetime import UTC, datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))  # 业务口径为北京时间


def moment(value):
    """把 ISO 字符串或 datetime 归一为 UTC 朴素时间；朴素输入视为已是 UTC。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("到件时间不能为空。")
        value = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    if not isinstance(value, datetime):
        raise ValueError("到件时间格式不正确。")
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def display(value):
    """把时刻格式化为北京时间 ISO 字符串，供结果页和下载使用。"""
    return moment(value).replace(tzinfo=UTC).astimezone(BEIJING).isoformat(timespec='seconds')


def sort_key(version):
    """版本定位键：先生效时刻，后签发序号。"""
    return (moment(version["effective_at"]), int(version["issued_seq"]))


def find_overlap(versions):
    """返回（生效时刻， 签发序号）重复的重叠键，没有重叠时返回 None。"""
    seen = {}
    for version in versions:
        key = sort_key(version)
        if key in seen and seen[key].get("version") != version.get("version"):
            return key
        seen[key] = version
    return None


def resolve(versions, arrived_at):
    """按到件时刻取当时生效的唯一规则版本；没有生效中的版本时返回 None。"""
    arrival = moment(arrived_at)
    eligible = [version for version in versions if moment(version["effective_at"]) <= arrival]
    if not eligible:
        return None
    return max(eligible, key=sort_key)
