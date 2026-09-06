"""
TAT (Turnaround Time) & SLA Service.
Calculates duration metrics for issue resolution cycles in UTC and formats for display.
"""

from datetime import datetime


def parse_timestamp(ts_val):
    """Parse SQLite timestamp string or datetime object into naive datetime."""
    if not ts_val:
        return None
    if isinstance(ts_val, datetime):
        return ts_val
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(ts_val).split(".")[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def format_duration(seconds):
    """Convert duration in seconds to human-readable string (e.g. '2d 4h 15m' or '45m')."""
    if seconds is None or seconds < 0:
        return "N/A"

    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)


def calculate_issue_tat(issue_row):
    """
    Calculate authoritative TAT metrics for an issue record.
    Returns dictionary with durations in seconds and formatted strings.
    """
    reported_at = parse_timestamp(issue_row["reported_at"])
    first_resp_at = parse_timestamp(issue_row["first_response_at"])
    res_provided_at = parse_timestamp(issue_row["resolution_provided_at"])
    res_confirmed_at = parse_timestamp(issue_row["resolved_confirmed_at"])
    reopened_at = parse_timestamp(issue_row["reopened_at"])

    # 1. First Response TAT
    first_response_sec = (first_resp_at - reported_at).total_seconds() if (first_resp_at and reported_at) else None

    # 2. Resolution Provided TAT
    resolution_sec = (res_provided_at - reported_at).total_seconds() if (res_provided_at and reported_at) else None

    # 3. User Confirmation TAT
    confirmation_sec = (res_confirmed_at - reported_at).total_seconds() if (res_confirmed_at and reported_at) else None

    # 4. Reopened Cycle TAT (if issue was reopened)
    reopen_cycle_sec = (res_confirmed_at - reopened_at).total_seconds() if (res_confirmed_at and reopened_at) else None

    return {
        "first_response_tat_str": format_duration(first_response_sec),
        "resolution_tat_str": format_duration(resolution_sec),
        "confirmation_tat_str": format_duration(confirmation_sec),
        "reopen_cycle_tat_str": format_duration(reopen_cycle_sec),
        "first_response_seconds": first_response_sec,
        "resolution_seconds": resolution_sec,
        "confirmation_seconds": confirmation_sec,
        "reopen_cycle_seconds": reopen_cycle_sec
    }

