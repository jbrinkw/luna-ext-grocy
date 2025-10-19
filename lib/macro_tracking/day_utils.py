"""
Day boundary utilities for macro tracking.

Handles custom day start time (e.g., 6 AM instead of midnight).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Tuple

from macro_tracking import macro_db


def get_day_start_hour() -> int:
    """Returns configured day start hour (default 6).
    
    Reads from DAY_START_TIME env var (format: HHMM, e.g., '0600'),
    then falls back to database config, then defaults to 6.
    """
    # Try environment variable first
    env_time = os.getenv("DAY_START_TIME")
    if env_time:
        try:
            # Parse HHMM format (e.g., "0600" -> 6)
            if len(env_time) == 4 and env_time.isdigit():
                hour = int(env_time[:2])
                if 0 <= hour <= 23:
                    return hour
        except (ValueError, TypeError):
            pass
    
    # Fall back to database config
    hour_str = macro_db.get_config("day_start_hour")
    if hour_str is None:
        return 6
    try:
        hour = int(hour_str)
        if 0 <= hour <= 23:
            return hour
        return 6
    except (ValueError, TypeError):
        return 6


def get_current_day_timestamp() -> str:
    """Returns YYYY-MM-DD for current day based on custom start hour.
    
    For example, with start_hour=6:
    - 2025-01-15 05:30 -> returns "2025-01-14" (still previous day)
    - 2025-01-15 06:00 -> returns "2025-01-15" (new day starts)
    """
    now = datetime.now()
    start_hour = get_day_start_hour()
    
    # If current hour is before start hour, we're still in the previous day
    if now.hour < start_hour:
        adjusted = now - timedelta(days=1)
        return adjusted.strftime("%Y-%m-%d")
    
    return now.strftime("%Y-%m-%d")


def get_datetime_range_for_day(day: str) -> Tuple[datetime, datetime]:
    """Convert day string to actual datetime range based on custom start hour.
    
    Args:
        day: YYYY-MM-DD format
        
    Returns:
        (start_datetime, end_datetime) tuple
        
    Example:
        day="2025-01-15", start_hour=6
        -> (2025-01-15 06:00:00, 2025-01-16 05:59:59)
    """
    start_hour = get_day_start_hour()
    
    # Parse the day string
    day_date = datetime.strptime(day, "%Y-%m-%d")
    
    # Start of custom day
    start_dt = day_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    
    # End is just before the start of the next day
    end_dt = start_dt + timedelta(days=1) - timedelta(seconds=1)
    
    return start_dt, end_dt


def is_datetime_in_day(dt: datetime, day: str) -> bool:
    """Check if a datetime falls within a custom day boundary.
    
    Args:
        dt: datetime to check
        day: YYYY-MM-DD format
        
    Returns:
        True if dt is within the day's custom boundaries
    """
    start_dt, end_dt = get_datetime_range_for_day(day)
    return start_dt <= dt <= end_dt

