"""Meal plan operations."""

from typing import Any, Dict, List

from core.client import GrocyClient


class MealPlanService:
    """Handles meal planning operations."""
    
    def __init__(self, client: GrocyClient):
        self.client = client
    
    def list_meal_plan(self) -> List[Dict[str, Any]]:
        data = self.client._get("/objects/meal_plan")
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    def create_meal_plan_entry(self, fields: Dict[str, Any]) -> Any:
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
        day = fields.get("day")
        if not isinstance(day, str) or not day.strip():
            raise ValueError("'day' (YYYY-MM-DD) is required")
        # Require at least one content field: recipe, product, or note
        if not (fields.get("recipe_id") or fields.get("product_id") or fields.get("note")):
            raise ValueError("Provide one of 'recipe_id', 'product_id', or 'note'")
        if fields.get("recipe_id") is not None:
            rid = int(fields["recipe_id"])
            if not self.client._object_exists("recipes", rid):
                raise ValueError(f"Invalid recipe_id={rid}: No such recipe")
        if fields.get("product_id") is not None:
            pid = int(fields["product_id"])
            if not self.client._object_exists("products", pid):
                raise ValueError(f"Invalid product_id={pid}: No such product")
        if fields.get("qu_id") is not None:
            qid = int(fields["qu_id"])
            if not self.client._object_exists("quantity_units", qid):
                raise ValueError(f"Invalid qu_id={qid}: No such quantity unit")
        if fields.get("meal_plan_section_id") is not None:
            sid = int(fields["meal_plan_section_id"])
            if not self.client._object_exists("meal_plan_sections", sid):
                raise ValueError(f"Invalid meal_plan_section_id={sid}: No such section")
        return self.client._post("/objects/meal_plan", json_body=fields)

    def update_meal_plan_entry(self, entry_id: int, fields: Dict[str, Any]) -> Any:
        if not isinstance(fields, dict) or not fields:
            raise ValueError("update fields must be a non-empty object")
        eid = int(entry_id)
        return self.client._put(f"/objects/meal_plan/{eid}", json_body=fields)

    def delete_meal_plan_entry(self, entry_id: int) -> Any:
        eid = int(entry_id)
        return self.client._delete(f"/objects/meal_plan/{eid}")

    def list_meal_plan_sections(self) -> List[Dict[str, Any]]:
        data = self.client._get("/objects/meal_plan_sections")
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            return data["data"]
        if isinstance(data, list):
            return data
        return []
    
    def get_meal_plan(self, start: str, end: str) -> List[Dict[str, Any]]:
        """Get meal plan entries between start and end dates (YYYY-MM-DD)."""
        all_entries = self.list_meal_plan()
        filtered = []
        for entry in all_entries:
            day = entry.get("day")
            if isinstance(day, str) and start <= day <= end:
                filtered.append(entry)
        return filtered

