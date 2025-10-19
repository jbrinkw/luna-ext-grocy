"""
Macro aggregation module.

Combines Grocy meal plan data with temp items for daily totals.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

import sys
from pathlib import Path

# Add lib directory to path
_lib_path = Path(__file__).parent.parent
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from . import day_utils, macro_db
from core.client import GrocyClient


# Load environment at module level
try:
    load_dotenv(override=False)
except Exception:
    pass


def get_grocy_consumed_for_day(day: str) -> List[Dict[str, Any]]:
    """Fetch consumed items from Grocy meal plan marked as done for a specific day.
    
    Args:
        day: YYYY-MM-DD format
        
    Returns:
        List of consumed entries with type, id, name, servings, and macros
    """
    try:
        client = GrocyClient()
        
        # Get all meal plan entries
        all_entries = client.list_meal_plan()
        
        # Filter to entries for this day that are marked as done
        consumed = []
        for entry in all_entries:
            entry_day = entry.get("day")
            if entry_day != day:
                continue
            
            # Check if marked as done (Grocy may use different fields)
            # Common field names: done, is_done, completed, consumed
            is_done = entry.get("done") or entry.get("is_done") or entry.get("completed")
            if not is_done:
                continue
            
            # Determine type and get macros
            recipe_id = entry.get("recipe_id")
            product_id = entry.get("product_id")
            
            if recipe_id:
                # Recipe entry
                try:
                    recipe = client.get_recipe(int(recipe_id))
                    userfields = _get_recipe_userfields(client, int(recipe_id))
                    
                    servings = float(entry.get("servings", 1.0))
                    
                    consumed.append({
                        "type": "recipe",
                        "id": int(recipe_id),
                        "name": recipe.get("name", f"Recipe {recipe_id}"),
                        "servings": servings,
                        "calories": int(_get_float(userfields, "recipe_calories", 0) * servings),
                        "carbs": float(_get_float(userfields, "recipe_carbs", 0) * servings),
                        "fats": float(_get_float(userfields, "recipe_fats", 0) * servings),
                        "protein": float(_get_float(userfields, "recipe_proteins", 0) * servings),
                    })
                except Exception:
                    continue
                    
            elif product_id:
                # Product entry
                try:
                    product = client._get(f"/objects/products/{int(product_id)}")
                    userfields = client.get_product_userfields(int(product_id))
                    
                    amount = float(entry.get("amount", 1.0))
                    
                    # Get per-serving macros
                    cals_per_serv = _get_float(userfields, "Calories_Per_Serving", 0)
                    carbs_per_serv = _get_float(userfields, "Carbs", 0)
                    fats_per_serv = _get_float(userfields, "Fats", 0)
                    protein_per_serv = _get_float(userfields, "Protein", 0)
                    
                    consumed.append({
                        "type": "product",
                        "id": int(product_id),
                        "name": product.get("name", f"Product {product_id}"),
                        "servings": amount,
                        "calories": int(cals_per_serv * amount),
                        "carbs": float(carbs_per_serv * amount),
                        "fats": float(fats_per_serv * amount),
                        "protein": float(protein_per_serv * amount),
                    })
                except Exception:
                    continue
        
        return consumed
        
    except Exception:
        # If Grocy unavailable or error, return empty
        return []


def get_temp_consumed_for_day(day: str) -> List[Dict[str, Any]]:
    """Fetch consumed temp items for day from temp_items table.
    
    Args:
        day: YYYY-MM-DD format
        
    Returns:
        List of temp item entries with type, id, name, and macros
    """
    try:
        items = macro_db.get_temp_items_for_day(day)
        
        result = []
        for item in items:
            result.append({
                "type": "temp",
                "id": item["id"],
                "name": item["name"],
                "calories": int(item.get("calories", 0)),
                "carbs": float(item.get("carbs", 0)),
                "fats": float(item.get("fats", 0)),
                "protein": float(item.get("protein", 0)),
            })
        
        return result
        
    except Exception:
        return []


def get_grocy_planned_for_day(day: str) -> Dict[str, Any]:
    """Fetch planned macros from Grocy meal plan (includes both done and not done).
    
    Args:
        day: YYYY-MM-DD format
        
    Returns:
        Dict with total planned calories and macros (goal for the day)
    """
    try:
        client = GrocyClient()
        
        # Get all meal plan entries
        all_entries = client.list_meal_plan()
        
        # Filter to entries for this day (include ALL - both done and not done)
        # Planned should encompass the entire goal for the day
        total_cals = 0
        total_carbs = 0.0
        total_fats = 0.0
        total_protein = 0.0
        
        for entry in all_entries:
            entry_day = entry.get("day")
            if entry_day != day:
                continue
            
            # Include ALL meal plan entries (both done and not done)
            # Planned = total goal for the day
            
            # Get macros for this planned entry
            recipe_id = entry.get("recipe_id")
            product_id = entry.get("product_id")
            
            if recipe_id:
                try:
                    userfields = _get_recipe_userfields(client, int(recipe_id))
                    servings = float(entry.get("servings", 1.0))
                    
                    total_cals += int(_get_float(userfields, "recipe_calories", 0) * servings)
                    total_carbs += float(_get_float(userfields, "recipe_carbs", 0) * servings)
                    total_fats += float(_get_float(userfields, "recipe_fats", 0) * servings)
                    total_protein += float(_get_float(userfields, "recipe_proteins", 0) * servings)
                except Exception:
                    continue
                    
            elif product_id:
                try:
                    userfields = client.get_product_userfields(int(product_id))
                    amount = float(entry.get("amount", 1.0))
                    
                    cals_per_serv = _get_float(userfields, "Calories_Per_Serving", 0)
                    carbs_per_serv = _get_float(userfields, "Carbs", 0)
                    fats_per_serv = _get_float(userfields, "Fats", 0)
                    protein_per_serv = _get_float(userfields, "Protein", 0)
                    
                    total_cals += int(cals_per_serv * amount)
                    total_carbs += float(carbs_per_serv * amount)
                    total_fats += float(fats_per_serv * amount)
                    total_protein += float(protein_per_serv * amount)
                except Exception:
                    continue
        
        return {
            "calories": total_cals,
            "carbs": round(total_carbs, 2),
            "fats": round(total_fats, 2),
            "protein": round(total_protein, 2),
        }
        
    except Exception:
        return {
            "calories": 0,
            "carbs": 0.0,
            "fats": 0.0,
            "protein": 0.0,
        }


def get_goal_macros() -> Dict[str, Any]:
    """Get goal macros from config (can be overridden by environment variables).
    
    Returns:
        Dict with goal calories and macros
    """
    import os
    
    # Try environment variables first, fallback to database config
    goal_cals = int(os.getenv("MACRO_GOAL_CALORIES") or macro_db.get_config("goal_calories") or "3500")
    goal_carbs = float(os.getenv("MACRO_GOAL_CARBS") or macro_db.get_config("goal_carbs") or "350")
    goal_fats = float(os.getenv("MACRO_GOAL_FATS") or macro_db.get_config("goal_fats") or "100")
    goal_protein = float(os.getenv("MACRO_GOAL_PROTEIN") or macro_db.get_config("goal_protein") or "250")
    
    return {
        "calories": goal_cals,
        "carbs": round(goal_carbs, 2),
        "fats": round(goal_fats, 2),
        "protein": round(goal_protein, 2),
    }


def get_day_summary(day: str) -> Dict[str, Any]:
    """Aggregate all data for a day.
    
    Args:
        day: YYYY-MM-DD format
        
    Returns:
        Dict with day, consumed, planned, and goal totals
    """
    # Get all consumed entries
    grocy_consumed = get_grocy_consumed_for_day(day)
    temp_consumed = get_temp_consumed_for_day(day)
    all_entries = grocy_consumed + temp_consumed
    
    # Calculate consumed totals
    consumed_cals = sum(e.get("calories", 0) for e in all_entries)
    consumed_carbs = sum(e.get("carbs", 0) for e in all_entries)
    consumed_fats = sum(e.get("fats", 0) for e in all_entries)
    consumed_protein = sum(e.get("protein", 0) for e in all_entries)
    
    # Get planned totals
    planned = get_grocy_planned_for_day(day)
    
    # Get goal totals
    goal = get_goal_macros()
    
    return {
        "day": day,
        "consumed": {
            "calories": int(consumed_cals),
            "carbs": round(consumed_carbs, 2),
            "fats": round(consumed_fats, 2),
            "protein": round(consumed_protein, 2),
            "entries": all_entries,
        },
        "planned": planned,
        "goal": goal,
    }


def _get_float(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Safely extract float value from dict."""
    try:
        val = data.get(key)
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def get_recent_days_with_activity(limit: int = None) -> List[str]:
    """Get recent days that have any macro activity (consumed items or meal plan).
    
    Args:
        limit: Maximum number of days to return (None = all days)
        
    Returns:
        List of day strings (YYYY-MM-DD) in descending order (most recent first)
    """
    days_set = set()
    
    # Get ALL days from temp items (no limit)
    try:
        rows = macro_db.execute_query("SELECT DISTINCT day FROM temp_items ORDER BY day DESC")
        for row in rows:
            if row["day"]:
                days_set.add(row["day"])
    except Exception:
        pass
    
    # Get ALL days from Grocy meal plan
    try:
        client = GrocyClient()
        all_entries = client.list_meal_plan()
        
        for entry in all_entries:
            day = entry.get("day")
            if day:
                days_set.add(day)
    except Exception:
        pass
    
    # Sort in descending order (most recent first)
    days_list = sorted(list(days_set), reverse=True)
    
    # Apply limit only if specified
    if limit is not None and limit > 0:
        return days_list[:limit]
    return days_list


def _get_recipe_userfields(client: GrocyClient, recipe_id: int) -> Dict[str, Any]:
    """Get userfields for a recipe."""
    try:
        # Try standard endpoint
        data = client._get(f"/objects/recipes/{recipe_id}/userfields")
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    
    try:
        # Try alternate endpoint
        data = client._get(f"/userfields/recipes/{recipe_id}")
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    
    return {}

