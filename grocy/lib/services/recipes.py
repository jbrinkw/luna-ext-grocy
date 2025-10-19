"""Recipe CRUD and ingredient management operations."""

import json
from typing import Any, Dict, List, Optional

from core.client import GrocyClient


class RecipeService:
    """Handles recipe and ingredient operations."""
    
    def __init__(self, client: GrocyClient):
        self.client = client
    
    # ---- Recipes CRUD ----
    def get_recipes(self) -> List[Dict[str, Any]]:
        data = self.client._get("/objects/recipes")
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    def get_recipe(self, recipe_id: int) -> Dict[str, Any]:
        rid = int(recipe_id)
        data = self.client._get(f"/objects/recipes/{rid}")
        return data if isinstance(data, dict) else {"id": rid}

    def create_recipe(self, fields: Dict[str, Any]) -> Any:
        if not isinstance(fields, dict) or not fields.get("name"):
            raise ValueError("recipe fields must include 'name'")
        return self.client._post("/objects/recipes", json_body=fields)

    def update_recipe(self, recipe_id: int, fields: Dict[str, Any]) -> Any:
        if not isinstance(fields, dict) or not fields:
            raise ValueError("update fields must be a non-empty object")
        rid = int(recipe_id)
        return self.client._put(f"/objects/recipes/{rid}", json_body=fields)

    def delete_recipe(self, recipe_id: int) -> Any:
        rid = int(recipe_id)
        return self.client._delete(f"/objects/recipes/{rid}")

    # ---- Recipe Ingredients (recipes_pos) ----
    def list_recipe_ingredients(self, recipe_id: int) -> List[Dict[str, Any]]:
        rid = int(recipe_id)
        data = self.client._get("/objects/recipes_pos")
        items: List[Dict[str, Any]]
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            items = data["data"]
        elif isinstance(data, list):
            items = data
        else:
            items = []
        result: List[Dict[str, Any]] = []
        for item in items:
            if int(item.get("recipe_id", -1)) == rid:
                result.append(item)
        return result

    def add_recipe_ingredient(self, fields: Dict[str, Any]) -> Any:
        if not isinstance(fields, dict):
            raise ValueError("ingredient fields must be an object")
        rid = fields.get("recipe_id")
        pid = fields.get("product_id")
        amount = fields.get("amount")
        if not isinstance(rid, (int, float, str)):
            raise ValueError("'recipe_id' is required")
        if not isinstance(pid, (int, float, str)):
            raise ValueError("'product_id' is required")
        if not isinstance(amount, (int, float)):
            raise ValueError("'amount' is required and must be a number")
        rid_int = int(rid)
        pid_int = int(pid)
        if not self.client._object_exists("recipes", rid_int):
            raise ValueError(f"Invalid recipe_id={rid_int}: No such recipe")
        if not self.client._object_exists("products", pid_int):
            raise ValueError(f"Invalid product_id={pid_int}: No such product")
        qu_id = fields.get("qu_id")
        if qu_id is not None:
            qu_int = int(qu_id)
            if not self.client._object_exists("quantity_units", qu_int):
                raise ValueError(f"Invalid qu_id={qu_int}: No such quantity unit")
        return self.client._post("/objects/recipes_pos", json_body=fields)

    def update_recipe_ingredient(self, ingredient_id: int, fields: Dict[str, Any]) -> Any:
        if not isinstance(fields, dict) or not fields:
            raise ValueError("update fields must be a non-empty object")
        iid = int(ingredient_id)
        return self.client._put(f"/objects/recipes_pos/{iid}", json_body=fields)

    def delete_recipe_ingredient(self, ingredient_id: int) -> Any:
        iid = int(ingredient_id)
        return self.client._delete(f"/objects/recipes_pos/{iid}")

    # ---- Recipe fulfillment (cookability checking) ----
    def get_recipe_fulfillment(
        self,
        recipe_id: int,
        desired_servings: Optional[float] = None,
        consider_shopping_list: Optional[bool] = False,
    ) -> Dict[str, Any]:
        """Return Grocy's fulfillment data for a recipe using Grocy's own logic.

        This calls the upstream endpoint used by Grocy's UI to compute the
        "Requirements fulfilled" status. Because Grocy versions may vary in
        route/parameter naming, we try a small set of sensible fallbacks.
        """
        rid = int(recipe_id)

        # Candidate endpoint paths to maximize compatibility across Grocy versions
        path_templates = [
            "/recipes/{rid}/fulfillment",
            "/recipes/{rid}/fulfilment",  # British spelling fallback
            "/recipes/{rid}/requirements",  # older/alternative naming (best effort)
        ]

        # Build parameter variants to try, from most-likely to least-likely
        param_variants: List[Dict[str, Any]] = []
        # Always try no params first (base_servings assumed by Grocy)
        param_variants.append({})

        def _bool_to_int(value: Optional[bool]) -> Optional[int]:
            if value is None:
                return None
            return 1 if bool(value) else 0

        if desired_servings is not None or consider_shopping_list is not None:
            consider_val = _bool_to_int(consider_shopping_list)
            serving_keys = ["desired_servings", "servings", "portions", "desired_portions"]
            for key in serving_keys:
                params: Dict[str, Any] = {}
                if desired_servings is not None:
                    params[key] = float(desired_servings)
                if consider_val is not None:
                    # Most common spelling
                    params["consider_shopping_list"] = consider_val
                param_variants.append(params)

        last_error: Optional[Exception] = None
        for tmpl in path_templates:
            path = tmpl.format(rid=rid)
            for params in param_variants:
                try:
                    data = self.client._get(path, params=params or None)
                    if isinstance(data, dict):
                        return data
                    # Some Grocy deployments might return JSON string
                    if isinstance(data, str):
                        try:
                            parsed = json.loads(data)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                except Exception as error:  # noqa: PERF203
                    import requests
                    if isinstance(error, requests.HTTPError):
                        status = getattr(error.response, "status_code", None)
                        # Try next variant on 404/405/400 (not found/method not allowed/bad request)
                        if status in {400, 404, 405}:
                            last_error = error
                            continue
                    raise
        if last_error:
            raise last_error
        raise ValueError(f"Failed to retrieve recipe fulfillment for recipe_id={rid}")

    @staticmethod
    def _is_recipe_fulfillment_fulfilled(fulfillment: Any) -> bool:
        """Best-effort detection whether fulfillment indicates cookable now.

        We rely on Grocy's response; different versions may expose different keys.
        This method interprets a few common shapes without re-implementing logic.
        """
        if not isinstance(fulfillment, dict):
            return False

        # Direct boolean flags used by some Grocy versions/themes
        truthy_keys = [
            "requirements_fulfilled",
            "is_fulfilled",
            "can_be_cooked",
            "fully_fulfilled",
            "all_ingredients_in_stock",
        ]
        for key in truthy_keys:
            val = fulfillment.get(key)
            if isinstance(val, bool):
                if val:
                    return True
                # if explicitly False, keep checking other indicators

        # Missing counts/lists
        missing_list_keys = ["missing_products", "missing_items", "missing"]
        for key in missing_list_keys:
            val = fulfillment.get(key)
            if isinstance(val, list) and len(val) == 0:
                return True
            if isinstance(val, list) and len(val) > 0:
                return False

        missing_count_keys = [
            "missing_products_count",
            "missing_count",
            "num_missing",
            "missing_amount",
        ]
        for key in missing_count_keys:
            val = fulfillment.get(key)
            if isinstance(val, (int, float)) and float(val) <= 0:
                return True
            if isinstance(val, (int, float)) and float(val) > 0:
                return False

        # Positive servings indicators (>= 1) imply at least one serving possible
        servings_keys = [
            "possible_servings",
            "servings_possible",
            "possible_portions",
            "possible_amount",
            "num_servings",
        ]
        for key in servings_keys:
            val = fulfillment.get(key)
            if isinstance(val, (int, float)) and float(val) >= 1:
                return True

        return False

    @staticmethod
    def _extract_possible_servings(fulfillment: Any) -> Optional[float]:
        if not isinstance(fulfillment, dict):
            return None
        for key in [
            "possible_servings",
            "servings_possible",
            "possible_portions",
            "possible_amount",
            "num_servings",
        ]:
            val = fulfillment.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        return None

    def list_cookable_recipes(
        self,
        desired_servings: Optional[float] = None,
        consider_shopping_list: Optional[bool] = False,
    ) -> List[Dict[str, Any]]:
        """Return recipes that are currently cookable according to Grocy.

        This filters by Grocy's own fulfillment calculations and returns a small
        summary suitable for UI display.
        """
        recipes = self.get_recipes()
        result: List[Dict[str, Any]] = []
        for r in recipes:
            rid = r.get("id")
            if not isinstance(rid, (int, float)):
                continue
            try:
                ful = self.get_recipe_fulfillment(
                    int(rid),
                    desired_servings=desired_servings,
                    consider_shopping_list=consider_shopping_list,
                )
            except Exception:
                # Skip recipes with fulfillment errors; best-effort list
                continue
            if self._is_recipe_fulfillment_fulfilled(ful):
                result.append(
                    {
                        "id": int(rid),
                        "name": r.get("name"),
                        "possible_servings": self._extract_possible_servings(ful),
                    }
                )
        return result

