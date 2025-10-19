"""Macro tracking integration - bridges to macro_tracking module."""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add lib directory to path for macro_tracking imports
_lib_path = Path(__file__).parent.parent
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))


def get_day_macros(day: Optional[str] = None) -> Dict[str, Any]:
    """Get consumed/planned macros for a day.
    
    Args:
        day: YYYY-MM-DD format (defaults to current day)
        
    Returns:
        Dict from macro_aggregator.get_day_summary()
    """
    try:
        from macro_tracking import macro_aggregator, day_utils
        
        if day is None:
            day = day_utils.get_current_day_timestamp()
        
        summary = macro_aggregator.get_day_summary(day)
        return summary
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def get_recent_days(page: int = 0, limit: int = 4) -> Dict[str, Any]:
    """Get recent days with macro activity (paginated).
    
    Args:
        page: Page number (0-indexed)
        limit: Items per page
        
    Returns:
        Dict with days list, summaries, and pagination info
    """
    try:
        from macro_tracking import macro_aggregator
        
        # Get ALL days with activity (no limit)
        all_days = macro_aggregator.get_recent_days_with_activity(limit=None)
        
        # Calculate pagination
        total_days = len(all_days)
        total_pages = max(1, (total_days + limit - 1) // limit)
        page = max(0, min(page, total_pages - 1))
        
        # Get days for this page
        start_idx = page * limit
        end_idx = start_idx + limit
        page_days = all_days[start_idx:end_idx]
        
        # Get summaries for each day
        days_data = []
        for day in page_days:
            try:
                summary = macro_aggregator.get_day_summary(day)
                days_data.append(summary)
            except Exception:
                # Skip days that error
                continue
        
        return {
            "days": days_data,
            "total_pages": total_pages,
            "current_page": page,
            "total_days": total_days
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def create_temp_item(
    name: str, 
    calories: float, 
    carbs: float, 
    fats: float, 
    protein: float, 
    day: Optional[str] = None
) -> int:
    """Create temporary macro tracking item.
    
    Args:
        name: Item name
        calories: Total calories
        carbs: Carbs in grams
        fats: Fats in grams
        protein: Protein in grams
        day: YYYY-MM-DD format (defaults to current day)
        
    Returns:
        Created item ID
    """
    from macro_tracking import macro_db, day_utils
    
    if day is None:
        day = day_utils.get_current_day_timestamp()
    
    return macro_db.create_temp_item(name, calories, carbs, fats, protein, day)


def delete_temp_item(temp_item_id: int) -> bool:
    """Delete temporary item.
    
    Args:
        temp_item_id: ID of temp item to delete
        
    Returns:
        True if deleted, False if not found
    """
    from macro_tracking import macro_db
    return macro_db.delete_temp_item(temp_item_id)

