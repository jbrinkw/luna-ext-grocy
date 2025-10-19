"""Base Grocy HTTP client with CRUD operations.

The GrocyClient class provides a complete interface to Grocy by composing
service classes for different domains (inventory, products, shopping, etc).
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class GrocyClient:
    """Minimal client for the Grocy REST API.

    Reads configuration from environment variables by default:
    - GROCY_API_KEY: required API key
    - GROCY_BASE_URL: optional base URL, defaults to http://192.168.0.185/api
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        request_timeout_seconds: float = 15.0,
    ) -> None:
        # Load environment variables from a .env file if present
        load_dotenv(override=False)
        configured_base_url = base_url or os.getenv("GROCY_BASE_URL") or "http://192.168.0.185/api"
        normalized_base_url = configured_base_url.rstrip("/")

        configured_api_key = api_key or os.getenv("GROCY_API_KEY")
        if not configured_api_key:
            raise RuntimeError("GROCY_API_KEY environment variable is required but not set")

        self.base_url: str = normalized_base_url
        self.request_timeout_seconds: float = request_timeout_seconds

        self._session = requests.Session()
        self._session.headers.update(
            {
                "GROCY-API-KEY": configured_api_key,
                "Accept": "application/json",
            }
        )
        
        # Initialize services (lazy-loaded to avoid circular imports)
        self._inventory_service = None
        self._product_service = None
        self._shopping_service = None
        self._recipe_service = None
        self._meal_plan_service = None
        self._userfield_service = None

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self._session.get(
            url,
            params=params,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return response.json()
        return response.text

    def _post(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self._session.post(
            url,
            json=json_body or {},
            timeout=self.request_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:  # Surface Grocy error details to the caller
            try:
                details = response.json()
            except Exception:
                try:
                    details = response.text
                except Exception:
                    details = None
            # Re-raise with response details appended for easier diagnosis (e.g., validation errors)
            raise requests.HTTPError(f"{error} - {details}") from error
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return response.json()
        return response.text

    def _put(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self._session.put(
            url,
            json=json_body or {},
            timeout=self.request_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            try:
                details = response.json()
            except Exception:
                try:
                    details = response.text
                except Exception:
                    details = None
            raise requests.HTTPError(f"{error} - {details}") from error
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return response.json()
        return response.text

    def _delete(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        response = self._session.delete(
            url,
            timeout=self.request_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            try:
                details = response.json()
            except Exception:
                try:
                    details = response.text
                except Exception:
                    details = None
            raise requests.HTTPError(f"{error} - {details}") from error
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return response.json()
        return response.text

    def _object_exists(self, object_name: str, object_id: int) -> bool:
        """Return True iff /objects/{object_name}/{id} exists.

        This helps catch bad foreign key references (e.g., unknown location_id or unit id)
        before attempting creation, yielding clearer actionable errors.
        """
        try:
            data = self._get(f"/objects/{object_name}/{int(object_id)}")
            return isinstance(data, (dict, list)) or bool(data)
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            if status == 404:
                return False
            raise

    def _extract_created_id_from_response(self, response: Any) -> Optional[int]:
        """Best-effort extraction of a created object id from Grocy responses.

        Grocy may return different shapes depending on version/config, e.g.:
        - {"created_object_id": "123"}
        - {"id": 123}
        - "123" (plain text)
        If none match, returns None.
        """
        try:
            if isinstance(response, dict):
                for key in ["created_object_id", "id", "last_inserted_id", "last_inserted_row_id", "rowid", "row_id"]:
                    if key in response:
                        raw = response.get(key)
                        if isinstance(raw, (int, float)):
                            return int(raw)
                        if isinstance(raw, str) and raw.isdigit():
                            return int(raw)
            if isinstance(response, (int, float)):
                return int(response)
            if isinstance(response, str) and response.isdigit():
                return int(response)
        except Exception:
            return None
        return None
    
    # ---- Service composition: delegate to service classes ----
    
    @property
    def _inventory(self):
        if self._inventory_service is None:
            from services.inventory import InventoryService
            self._inventory_service = InventoryService(self)
        return self._inventory_service
    
    @property
    def _products(self):
        if self._product_service is None:
            from services.products import ProductService
            self._product_service = ProductService(self)
        return self._product_service
    
    @property
    def _shopping(self):
        if self._shopping_service is None:
            from services.shopping import ShoppingService
            self._shopping_service = ShoppingService(self)
        return self._shopping_service
    
    @property
    def _recipes(self):
        if self._recipe_service is None:
            from services.recipes import RecipeService
            self._recipe_service = RecipeService(self)
        return self._recipe_service
    
    @property
    def _meal_plans(self):
        if self._meal_plan_service is None:
            from services.meal_plan import MealPlanService
            self._meal_plan_service = MealPlanService(self)
        return self._meal_plan_service
    
    @property
    def _userfields(self):
        if self._userfield_service is None:
            from services.userfields import UserfieldService
            self._userfield_service = UserfieldService(self)
        return self._userfield_service
    
    # ---- Inventory operations (delegate to service) ----
    def get_inventory(self) -> List[Dict[str, Any]]:
        return self._inventory.get_inventory()
    
    def add_product_quantity(self, product_id: int, quantity: float) -> Any:
        return self._inventory.add_product_quantity(product_id, quantity)
    
    def add_product_quantity_with_price(self, product_id: int, quantity: float, price: float) -> Any:
        return self._inventory.add_product_quantity_with_price(product_id, quantity, price)
    
    def consume_product_quantity(self, product_id: int, quantity: float) -> Any:
        return self._inventory.consume_product_quantity(product_id, quantity)
    
    def get_product_stock_entries(self, product_id: int) -> List[Dict[str, Any]]:
        return self._inventory.get_product_stock_entries(product_id)
    
    # ---- Product operations (delegate to service) ----
    def create_product(self, product_fields: Dict[str, Any]) -> Any:
        return self._products.create_product(product_fields)
    
    def validate_product_required_ids(self, fields: Dict[str, Any]) -> None:
        return self._products.validate_product_required_ids(fields)
    
    def find_product_id_by_name(self, name: str) -> Optional[int]:
        return self._products.find_product_id_by_name(name)
    
    def ensure_product_exists(self, name: str, create_fields: Optional[Dict[str, Any]] = None) -> int:
        return self._products.ensure_product_exists(name, create_fields)
    
    def get_product_name_map(self) -> Dict[int, str]:
        return self._products.get_product_name_map()
    
    def list_all_products(self) -> List[Dict[str, Any]]:
        return self._products.list_all_products()
    
    # ---- Shopping list operations (delegate to service) ----
    def get_shopping_list_items(self, shopping_list_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._shopping.get_shopping_list_items(shopping_list_id)
    
    def shopping_list_add_product(self, product_id: int, amount: float, shopping_list_id: Optional[int] = 1) -> Any:
        return self._shopping.shopping_list_add_product(product_id, amount, shopping_list_id)
    
    def shopping_list_remove_product(self, product_id: int, amount: float, shopping_list_id: Optional[int] = 1) -> Any:
        return self._shopping.shopping_list_remove_product(product_id, amount, shopping_list_id)
    
    def shopping_list_clear(self, shopping_list_id: Optional[int] = 1) -> Any:
        return self._shopping.shopping_list_clear(shopping_list_id)
    
    # ---- Recipe operations (delegate to service) ----
    def get_recipes(self) -> List[Dict[str, Any]]:
        return self._recipes.get_recipes()
    
    def get_recipe(self, recipe_id: int) -> Dict[str, Any]:
        return self._recipes.get_recipe(recipe_id)
    
    def create_recipe(self, fields: Dict[str, Any]) -> Any:
        return self._recipes.create_recipe(fields)
    
    def update_recipe(self, recipe_id: int, fields: Dict[str, Any]) -> Any:
        return self._recipes.update_recipe(recipe_id, fields)
    
    def delete_recipe(self, recipe_id: int) -> Any:
        return self._recipes.delete_recipe(recipe_id)
    
    def list_recipe_ingredients(self, recipe_id: int) -> List[Dict[str, Any]]:
        return self._recipes.list_recipe_ingredients(recipe_id)
    
    def add_recipe_ingredient(self, fields: Dict[str, Any]) -> Any:
        return self._recipes.add_recipe_ingredient(fields)
    
    def update_recipe_ingredient(self, ingredient_id: int, fields: Dict[str, Any]) -> Any:
        return self._recipes.update_recipe_ingredient(ingredient_id, fields)
    
    def delete_recipe_ingredient(self, ingredient_id: int) -> Any:
        return self._recipes.delete_recipe_ingredient(ingredient_id)
    
    def get_recipe_fulfillment(self, recipe_id: int, desired_servings: Optional[float] = None, consider_shopping_list: Optional[bool] = False) -> Dict[str, Any]:
        return self._recipes.get_recipe_fulfillment(recipe_id, desired_servings, consider_shopping_list)
    
    def list_cookable_recipes(self, desired_servings: Optional[float] = None, consider_shopping_list: Optional[bool] = False) -> List[Dict[str, Any]]:
        return self._recipes.list_cookable_recipes(desired_servings, consider_shopping_list)
    
    # ---- Meal plan operations (delegate to service) ----
    def list_meal_plan(self) -> List[Dict[str, Any]]:
        return self._meal_plans.list_meal_plan()
    
    def create_meal_plan_entry(self, fields: Dict[str, Any]) -> Any:
        return self._meal_plans.create_meal_plan_entry(fields)
    
    def update_meal_plan_entry(self, entry_id: int, fields: Dict[str, Any]) -> Any:
        return self._meal_plans.update_meal_plan_entry(entry_id, fields)
    
    def delete_meal_plan_entry(self, entry_id: int) -> Any:
        return self._meal_plans.delete_meal_plan_entry(entry_id)
    
    def list_meal_plan_sections(self) -> List[Dict[str, Any]]:
        return self._meal_plans.list_meal_plan_sections()
    
    def get_meal_plan(self, start: str, end: str) -> List[Dict[str, Any]]:
        return self._meal_plans.get_meal_plan(start, end)
    
    # ---- Userfield operations (delegate to service) ----
    def fetch_userfield_definitions(self) -> List[Dict[str, Any]]:
        return self._userfields.fetch_userfield_definitions()
    
    def detect_walmart_userfield_key(self) -> Optional[str]:
        return self._userfields.detect_walmart_userfield_key()
    
    def detect_price_userfield_key(self) -> Optional[str]:
        return self._userfields.detect_price_userfield_key()
    
    def get_product_userfields(self, product_id: int) -> Dict[str, Any]:
        return self._userfields.get_product_userfields(product_id)
    
    def set_product_userfields(self, product_id: int, values: Dict[str, Any]) -> Any:
        return self._userfields.set_product_userfields(product_id, values)

