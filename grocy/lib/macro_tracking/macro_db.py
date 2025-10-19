"""
Database module for macro tracking.

Manages Postgres database for temporary items and configuration.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Import from parent lib module
import sys
from pathlib import Path
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from db import execute_query, execute_update, init_schema


def get_config(key: str) -> Optional[str]:
    """Get configuration value by key."""
    rows = execute_query("SELECT value FROM grocy_config WHERE key = %s", (key,))
    return rows[0]["value"] if rows else None


def set_config(key: str, value: str) -> None:
    """Set configuration value."""
    execute_update(
        """INSERT INTO grocy_config (key, value) 
           VALUES (%s, %s) 
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (key, value)
    )


def create_temp_item(name: str, calories: float, carbs: float, fats: float, protein: float, day: str) -> int:
    """Create a temp item and return its ID."""
    result = execute_update(
        """INSERT INTO grocy_temp_items (name, calories, carbs, fats, protein, day) 
           VALUES (%s, %s, %s, %s, %s, %s) 
           RETURNING id""",
        (name, calories, carbs, fats, protein, day)
    )
    return result


def get_temp_items_for_day(day: str) -> List[Dict[str, Any]]:
    """Get all temp items for a specific day."""
    rows = execute_query(
        "SELECT * FROM grocy_temp_items WHERE day = %s ORDER BY created_at",
        (day,)
    )
    return rows


def delete_temp_item(item_id: int) -> bool:
    """Delete a temp item by ID. Returns True if deleted, False if not found."""
    affected = execute_update("DELETE FROM grocy_temp_items WHERE id = %s", (item_id,))
    return affected > 0


# Initialize schema on import
try:
    init_schema()
except Exception:
    pass  # Schema already initialized or will be initialized on first use
