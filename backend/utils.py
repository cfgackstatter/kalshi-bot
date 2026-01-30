from datetime import datetime, timezone
from dateutil import parser
import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

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

def retry_on_api_error(max_retries=3, backoff_seconds=2):
    """Retry decorator for API calls with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_msg = str(e)
                    # Check if it's a retryable error
                    if any(code in error_msg for code in ['502', '503', '504', '401', '429']):
                        wait_time = backoff_seconds * (2 ** attempt)
                        logger.warning(f"API error (attempt {attempt + 1}/{max_retries}): {error_msg}. Retrying in {wait_time}s...")
                        if attempt < max_retries - 1:
                            time.sleep(wait_time)
                            continue
                    # Non-retryable error or max retries reached
                    logger.error(f"API call failed after {attempt + 1} attempts: {error_msg}")
                    raise
            return None
        return wrapper
    return decorator