from datetime import datetime, timezone
from dateutil import parser


def parse_datetime(dt):
    """Parse datetime string to timezone-aware datetime.
    
    Handles:
    - ISO 8601 strings with variable microsecond precision
    - Already parsed datetime objects
    - Missing timezone info (defaults to UTC)
    """
    if not isinstance(dt, str):
        if isinstance(dt, datetime):
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt
    
    # Normalize timezone format
    dt = dt.replace("Z", "+00:00")
    
    # Handle variable microsecond precision (Python expects 0, 3, or 6 digits)
    if '.' in dt and ('+' in dt or dt.count('-') > 2):
        parts = dt.split('.')
        if len(parts) == 2:
            date_part = parts[0]
            micro_and_tz = parts[1]
            
            if '+' in micro_and_tz:
                micro, tz = micro_and_tz.split('+')
                micro = micro.ljust(6, '0')[:6]
                dt = f"{date_part}.{micro}+{tz}"
            elif '-' in micro_and_tz and micro_and_tz.index('-') > 2:
                idx = micro_and_tz.rindex('-')
                micro = micro_and_tz[:idx]
                tz = micro_and_tz[idx+1:]
                micro = micro.ljust(6, '0')[:6]
                dt = f"{date_part}.{micro}-{tz}"
    
    parsed = parser.isoparse(dt)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
