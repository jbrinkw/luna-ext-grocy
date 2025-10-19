"""API wrapper functions for Grocy operations.

All *_json functions return JSON strings validated via Pydantic models.
These functions provide a stable API for the web server and agent.
"""

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from pydantic import BaseModel

# Ensure lib directory is on sys.path for absolute imports
_lib_path = Path(__file__).resolve().parent
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

# Import from refactored modules (absolute imports)
from core.client import GrocyClient
from services.inventory import InventoryService
from services.products import ProductService  
from services.shopping import ShoppingService
from services.recipes import RecipeService
from services.meal_plan import MealPlanService
from services.userfields import UserfieldService
from integrations.macros import (
    get_day_macros, get_recent_days, create_temp_item, delete_temp_item
)


class InventoryItemOut(BaseModel):
    name: Optional[str]
    quantity: Optional[float]
    expiry: Optional[str]


class ShoppingListItemOut(BaseModel):
    product_id: Optional[int]
    name: Optional[str]
    quantity: Optional[float]
    is_placeholder: Optional[bool] = None


class ProductsListItemOut(BaseModel):
    id: int
    name: str
    is_placeholder: Optional[bool] = None


class StatusMessageOut(BaseModel):
    status: str
    message: str


class StatusProductOut(StatusMessageOut):
    product_id: Optional[int] = None


class EnsureProductExistsOut(BaseModel):
    status: str
    message: str
    product_id: int
    created: bool


class MealPlanEntryOut(BaseModel):
    id: Optional[int] = None
    day: Optional[str] = None
    type: Optional[str] = None
    recipe_id: Optional[int] = None
    product_id: Optional[int] = None
    recipe_servings: Optional[int] = None
    product_amount: Optional[float] = None
    product_qu_id: Optional[int] = None
    section_id: Optional[int] = None
    note: Optional[str] = None
    done: Optional[int] = None


class CookableRecipeOut(BaseModel):
    id: int
    name: Optional[str] = None
    possible_servings: Optional[float] = None


class RecipeOut(BaseModel):
    id: int
    name: Optional[str] = None
    base_servings: Optional[int] = None
    description: Optional[str] = None


class StatusRecipeOut(StatusMessageOut):
    recipe_id: Optional[int] = None


class IngredientOut(BaseModel):
    id: Optional[int] = None
    recipe_id: Optional[int] = None
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    amount: Optional[float] = None
    qu_id: Optional[int] = None
    note: Optional[str] = None
    is_placeholder: Optional[bool] = None
    needs_purchase: Optional[bool] = None
    calories: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    protein: Optional[float] = None


class StatusIngredientOut(StatusMessageOut):
    ingredient_id: Optional[int] = None


class MealPlanSectionOut(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    sort_number: Optional[int] = None



def is_placeholder_product(product_id: int, client: Optional[GrocyClient] = None) -> bool:
    """Check if a product is a placeholder.
    
    Args:
        product_id: Product ID to check
        client: Optional GrocyClient instance (creates new if None)
        
    Returns:
        True if product has placeholder=True userfield, False otherwise
    """
    if client is None:
        client = GrocyClient()
    try:
        userfields = client.get_product_userfields(product_id)
        return bool(userfields.get("placeholder", False))
    except Exception:
        return False


def _extract_name(item: Dict[str, Any]) -> Optional[str]:
    product = item.get("product")
    if isinstance(product, dict) and "name" in product:
        return product.get("name")
    if "name" in item:
        return item.get("name")
    if "product_name" in item:
        return item.get("product_name")
    return None


def _extract_quantity(item: Dict[str, Any]) -> Optional[float]:
    for key in [
        "amount",
        "stock_amount",
        "quantity",
        "amount_aggregated",
        "available_amount",
    ]:
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    # Sometimes nested under product
    product = item.get("product")
    if isinstance(product, dict):
        for key in ["stock_amount", "amount", "quantity"]:
            value = product.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _extract_expiry(item: Dict[str, Any]) -> Optional[str]:
    for key in [
        "best_before_date",
        "due_date",
        "next_due_date",
        "best_before",
        "expiry_date",
    ]:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None




def get_inventory_json(base_url: Optional[str] = None) -> str:
    """Return a simplified inventory JSON array with name, quantity, and expiry.

    The function reads GROCY_API_KEY from the environment. Optionally override the
    base URL by passing base_url or setting GROCY_BASE_URL.
    """
    client = GrocyClient(base_url=base_url)
    raw_items = client.get_inventory()
    simplified: List[Dict[str, Any]] = []
    for item in raw_items:
        name = _extract_name(item)
        quantity = _extract_quantity(item)
        expiry = _extract_expiry(item)
        validated = InventoryItemOut(name=name, quantity=quantity, expiry=expiry)
        simplified.append(validated.model_dump())
    return json.dumps(simplified, ensure_ascii=False)


def increase_product_quantity_json(product_id: int, quantity: float, base_url: Optional[str] = None) -> str:
    """Increase a product's quantity and return a confirmation JSON string.

    Always returns a payload with at least keys: status, message, product_id, quantity_added.
    The raw API response (if available) is included under the "response" key.
    """
    client = GrocyClient(base_url=base_url)
    
    # Check if product is a placeholder
    if is_placeholder_product(product_id, client):
        error = StatusMessageOut(
            status="error",
            message="Cannot add stock to placeholder items. Placeholders are for planning only."
        )
        return json.dumps(error.model_dump(), ensure_ascii=False)
    
    client.add_product_quantity(product_id=product_id, quantity=quantity)
    confirmation = StatusMessageOut(status="ok", message=f"Increased product {product_id} by {float(quantity)}")
    return json.dumps(confirmation.model_dump(), ensure_ascii=False)


def consume_product_quantity_json(product_id: int, quantity: float, add_to_meal_plan: bool = False, base_url: Optional[str] = None) -> str:
    """Consume (decrease) a product's quantity and optionally add to meal plan for today.
    
    Args:
        product_id: Product ID to consume
        quantity: Amount to consume
        add_to_meal_plan: If True, also add this item to today's meal plan and mark as done
        base_url: Optional Grocy base URL
        
    Returns:
        JSON string with status and message
    """
    client = GrocyClient(base_url=base_url)
    
    # Check if product is a placeholder
    if is_placeholder_product(product_id, client):
        error = StatusMessageOut(
            status="error",
            message="Cannot consume placeholder items. Scan the actual product first."
        )
        return json.dumps(error.model_dump(), ensure_ascii=False)
    
    client.consume_product_quantity(product_id=product_id, quantity=quantity)
    message = f"Consumed product {product_id} by {float(quantity)}"
    
    # Add to meal plan if requested
    if add_to_meal_plan:
        try:
            # Get current date respecting custom day boundaries
            from macro_tracking import day_utils
            today = day_utils.get_current_day_timestamp()
            
            # Get product details to find quantity unit
            product = client._get(f"/objects/products/{product_id}")
            qu_id = product.get("qu_id_stock") or product.get("qu_id_purchase")
            
            # Add meal plan entry
            meal_fields = {
                "day": today,
                "type": "product",
                "product_id": int(product_id),
                "product_amount": float(quantity),
                "product_qu_id": qu_id
            }
            client.create_meal_plan_entry(meal_fields)
            
            # Get the meal plan entry we just created to mark it as done
            # We need to find it in today's meal plan
            try:
                meal_plan = client.get_meal_plan(start=today, end=today)
                # Find the entry we just created (should be the most recent one for this product)
                matching_entries = [
                    e for e in meal_plan 
                    if e.get("product_id") == product_id and e.get("day") == today
                ]
                if matching_entries:
                    # Get the most recent entry (last in list)
                    entry_id = matching_entries[-1].get("id")
                    if entry_id:
                        # Mark as done
                        for done_field in ["done", "is_done", "completed"]:
                            try:
                                client.update_meal_plan_entry(int(entry_id), {done_field: True})
                                message += f" and added to meal plan (marked done)"
                                break
                            except Exception:
                                continue
                        else:
                            message += f" and added to meal plan (could not mark done)"
                    else:
                        message += f" and added to meal plan"
                else:
                    message += f" and added to meal plan"
            except Exception as e:
                message += f" and added to meal plan (done status unclear: {str(e)})"
                
        except Exception as e:
            message += f" (meal plan add failed: {str(e)})"
    
    confirmation = StatusMessageOut(status="ok", message=message)
    return json.dumps(confirmation.model_dump(), ensure_ascii=False)


def get_shopping_list_json(shopping_list_id: Optional[int] = 1, base_url: Optional[str] = None) -> str:
    """Return shopping list items simplified to product_id, name, quantity."""
    client = GrocyClient(base_url=base_url)
    items = client.get_shopping_list_items(shopping_list_id=shopping_list_id)
    name_map: Dict[int, str] = {}
    try:
        name_map = client.get_product_name_map()
    except Exception:
        name_map = {}
    simplified: List[Dict[str, Any]] = []
    for item in items:
        pid_raw = item.get("product_id")
        quantity_raw = item.get("amount")
        pid = int(pid_raw) if isinstance(pid_raw, (int, float, str)) and str(pid_raw).isdigit() else None
        quantity = float(quantity_raw) if isinstance(quantity_raw, (int, float)) else None
        name = name_map.get(pid) if isinstance(pid, int) else None
        
        # Note: placeholder check removed for performance (was causing freezes with many API calls)
        # Use GetShoppingListCartLinks tool if you need placeholder information
        
        validated = ShoppingListItemOut(product_id=pid, name=name, quantity=quantity, is_placeholder=None)
        simplified.append(validated.model_dump())
    return json.dumps(simplified, ensure_ascii=False)


def build_products_system_prompt(base_url: Optional[str] = None, title: str = "Known Grocy Products") -> str:
    """Return a concise system prompt string listing all known products (id → name).

    Example output:
    "You know these products (id → name): 1: Milk; 2: Eggs; 3: Bread"
    """
    client = GrocyClient(base_url=base_url)
    name_map = client.get_product_name_map()
    if not name_map:
        return f"{title}: (no products found)"
    parts = [f"{pid}: {pname}" for pid, pname in sorted(name_map.items(), key=lambda kv: kv[0])]
    joined = "; ".join(parts)
    return f"{title}: {joined}"


def get_products_json(base_url: Optional[str] = None) -> str:
    """Return all known products as JSON array of {id, name}, sorted by id."""
    client = GrocyClient(base_url=base_url)
    id_to_name = client.get_product_name_map()
    products: List[Dict[str, Any]] = []
    for pid, name in sorted(id_to_name.items(), key=lambda kv: kv[0]):
        try:
            # Note: placeholder check removed for performance (was causing freezes with many API calls)
            # Use GetShoppingListCartLinks or other tools if you need placeholder information
            
            validated = ProductsListItemOut(id=int(pid), name=str(name), is_placeholder=None)
            products.append(validated.model_dump())
        except Exception:
            continue
    return json.dumps(products, ensure_ascii=False)


def create_product_json(product_fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    """Create a new product with the provided Grocy fields and return JSON.

    Expects at least 'name' in product_fields. If minimal required fields are
    not provided, set them via GROCY_DEFAULT_* environment vars or defaults.
    
    Supports 'ready_to_eat' field which will be set as a userfield.
    
    Returns: { status, message, product_id }
    """
    client = GrocyClient(base_url=base_url)
    fields: Dict[str, Any] = dict(product_fields or {})
    if not fields.get("name"):
        raise ValueError("'name' is required to create a product")

    # Extract userfield-specific fields
    ready_to_eat = fields.pop("ready_to_eat", None)
    placeholder = fields.pop("placeholder", None)
    calories_per_serving = fields.pop("Calories_Per_Serving", None)
    carbs = fields.pop("Carbs", None)
    fats = fields.pop("Fats", None)
    protein = fields.pop("Protein", None)
    num_servings = fields.pop("num_servings", None)

    # Fill minimal fields if missing
    fields.setdefault("location_id", int(os.getenv("GROCY_DEFAULT_LOCATION_ID", "2")))
    fields.setdefault("qu_id_purchase", int(os.getenv("GROCY_DEFAULT_QU_ID_PURCHASE", "2")))
    fields.setdefault("qu_id_stock", int(os.getenv("GROCY_DEFAULT_QU_ID_STOCK", "2")))
    # qu_factor_purchase_to_stock is optional depending on Grocy version; only send if provided

    # Validate keys prior to POST so we can surface precise guidance
    client.validate_product_required_ids(fields)
    resp = client.create_product(fields)
    pid = client._extract_created_id_from_response(resp)
    if not isinstance(pid, int):
        # Fallback: try to find it by name
        pid = client.find_product_id_by_name(fields["name"]) or None
    
    # Set userfields if provided
    if isinstance(pid, int):
        userfield_updates: Dict[str, Any] = {}
        if ready_to_eat is not None:
            userfield_updates["ready_to_eat"] = bool(ready_to_eat)
        if placeholder is not None:
            userfield_updates["placeholder"] = bool(placeholder)
        if calories_per_serving is not None:
            userfield_updates["Calories_Per_Serving"] = float(calories_per_serving)
        if carbs is not None:
            userfield_updates["Carbs"] = float(carbs)
        if fats is not None:
            userfield_updates["Fats"] = float(fats)
        if protein is not None:
            userfield_updates["Protein"] = float(protein)
        if num_servings is not None:
            userfield_updates["num_servings"] = float(num_servings)
        
        if userfield_updates:
            try:
                client.set_product_userfields(pid, userfield_updates)
            except Exception:
                pass  # Don't fail product creation if userfield set fails
    
    result = StatusProductOut(status="ok", message=f"Created product '{fields['name']}'", product_id=int(pid) if isinstance(pid, int) else None)
    return json.dumps(result.model_dump(), ensure_ascii=False)


def ensure_product_exists_json(name: str, create_fields: Optional[Dict[str, Any]] = None, base_url: Optional[str] = None) -> str:
    """Ensure a product by name exists; create if missing and return id.

    Returns: { status, message, product_id, created }
    """
    client = GrocyClient(base_url=base_url)
    existing = client.find_product_id_by_name(name)
    if isinstance(existing, int):
        out = EnsureProductExistsOut(status="ok", message=f"Product '{name}' already exists", product_id=int(existing), created=False)
        return json.dumps(out.model_dump(), ensure_ascii=False)
    new_id = client.ensure_product_exists(name=name, create_fields=create_fields)
    out = EnsureProductExistsOut(status="ok", message=f"Created product '{name}'", product_id=int(new_id), created=True)
    return json.dumps(out.model_dump(), ensure_ascii=False)


def shopping_list_add_product_json(
    product_id: int,
    amount: float,
    shopping_list_id: Optional[int] = 1,
    base_url: Optional[str] = None,
) -> str:
    client = GrocyClient(base_url=base_url)
    client.shopping_list_add_product(product_id=product_id, amount=amount, shopping_list_id=shopping_list_id)
    out = StatusMessageOut(status="ok", message=f"Added product {int(product_id)} x {float(amount)} to shopping list")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def shopping_list_remove_product_json(
    product_id: int,
    amount: float,
    shopping_list_id: Optional[int] = 1,
    base_url: Optional[str] = None,
) -> str:
    client = GrocyClient(base_url=base_url)
    client.shopping_list_remove_product(product_id=product_id, amount=amount, shopping_list_id=shopping_list_id)
    out = StatusMessageOut(status="ok", message=f"Removed product {int(product_id)} x {float(amount)} from shopping list")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def shopping_list_clear_json(shopping_list_id: Optional[int] = 1, base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.shopping_list_clear(shopping_list_id=shopping_list_id)
    out = StatusMessageOut(status="ok", message=f"Cleared shopping list {int(shopping_list_id) if shopping_list_id is not None else ''}")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def get_meal_plan_json(start: Optional[str] = None, end: Optional[str] = None, base_url: Optional[str] = None) -> str:
    """Return meal plan entries, optionally filtered by [start, end] date inclusive.

    Dates are strings in YYYY-MM-DD; lexical comparison works for filtering.
    """
    client = GrocyClient(base_url=base_url)
    items = client.list_meal_plan()

    def _in_range(day: Optional[str]) -> bool:
        if not isinstance(day, str) or not day:
            return False if (start or end) else True
        if start and day < start:
            return False
        if end and day > end:
            return False
        return True

    simplified: List[Dict[str, Any]] = []
    for it in items:
        if _in_range(it.get("day")):
            validated = MealPlanEntryOut(
                id=it.get("id"),
                day=it.get("day"),
                type=it.get("type"),
                recipe_id=it.get("recipe_id"),
                product_id=it.get("product_id"),
                recipe_servings=it.get("recipe_servings"),
                product_amount=it.get("product_amount"),
                product_qu_id=it.get("product_qu_id"),
                section_id=it.get("section_id"),
                note=it.get("note"),
                done=it.get("done"),
            )
            simplified.append(validated.model_dump())
    return json.dumps(simplified, ensure_ascii=False)


def add_meal_to_plan_json(fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.create_meal_plan_entry(dict(fields or {}))
    out = StatusMessageOut(status="ok", message="Meal plan entry created")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def update_meal_plan_entry_json(entry_id: int, fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.update_meal_plan_entry(entry_id=int(entry_id), fields=dict(fields or {}))
    out = StatusMessageOut(status="ok", message=f"Meal plan entry {int(entry_id)} updated")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def delete_meal_plan_entry_json(entry_id: int, base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.delete_meal_plan_entry(int(entry_id))
    out = StatusMessageOut(status="ok", message=f"Meal plan entry {int(entry_id)} deleted")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def get_meal_plan_sections_json(base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    raw = client.list_meal_plan_sections()
    out: List[Dict[str, Any]] = []
    for it in raw:
        try:
            out.append(
                MealPlanSectionOut(
                    id=(int(it.get("id")) if isinstance(it.get("id"), (int, float)) else None),
                    name=(str(it.get("name")) if isinstance(it.get("name"), str) else None),
                    sort_number=(int(it.get("sort_number")) if isinstance(it.get("sort_number"), (int, float)) else None),
                ).model_dump()
            )
        except Exception:
            continue
    return json.dumps(out, ensure_ascii=False)


def get_cookable_recipes_json(
    desired_servings: Optional[float] = None,
    consider_shopping_list: bool = False,
    base_url: Optional[str] = None,
) -> str:
    """Return recipes that can be made now using Grocy's fulfillment logic.

    Optional filters:
    - desired_servings: target servings (fallback to recipe base servings if None)
    - consider_shopping_list: if True, consider shopping list items as available
    """
    client = GrocyClient(base_url=base_url)
    items = client.list_cookable_recipes(
        desired_servings=desired_servings,
        consider_shopping_list=consider_shopping_list,
    )
    out: List[Dict[str, Any]] = []
    for it in items:
        try:
            out.append(
                CookableRecipeOut(
                    id=int(it.get("id")),
                    name=it.get("name"),
                    possible_servings=(
                        float(it.get("possible_servings"))
                        if isinstance(it.get("possible_servings"), (int, float))
                        else None
                    ),
                ).model_dump()
            )
        except Exception:
            continue
    return json.dumps(out, ensure_ascii=False)


# ---- Walmart link helpers ----
class UploadWalmartLinkItem(BaseModel):
    product_id: int
    walmart_link: str
    price: Optional[float] = None


class UploadWalmartLinksResult(BaseModel):
    status: str
    message: str
    updated: List[int]
    skipped: List[int]


class MissingWalmartLinkItem(BaseModel):
    product_id: int
    product_name: str
    walmart_search_url: str
    missing_link: bool = False
    missing_price: bool = False


class MissingWalmartLinksResult(BaseModel):
    status: str
    message: str
    items: List[MissingWalmartLinkItem]
    total_missing: int


class ShoppingListCartLinkItem(BaseModel):
    product_id: int
    product_name: str
    quantity: float
    walmart_url: str
    is_placeholder: bool
    link_type: str  # "add_to_cart" or "search"


class ShoppingListCartLinksResult(BaseModel):
    status: str
    message: str
    items: List[ShoppingListCartLinkItem]
    total_items: int


def upload_walmart_links_json(items: List[Dict[str, Any]], base_url: Optional[str] = None) -> str:
    """Bulk upload Walmart links into product userfields.

    Input: items = [{ "product_id": int, "walmart_link": str }, ...]
    Behavior:
      - Detect Walmart userfield key for products via heuristic.
      - For each item, if link is non-empty and different from existing value,
        set it; else skip.
    Returns JSON: { status, message, updated: [ids], skipped: [ids] }
    """
    client = GrocyClient(base_url=base_url)
    # Validate input and coerce types via Pydantic
    validated: List[UploadWalmartLinkItem] = []
    for it in items or []:
        try:
            # Model validation handles types/coercion
            model = UploadWalmartLinkItem(
                product_id=int(it.get("product_id")),
                walmart_link=str(it.get("walmart_link")),
                price=(float(it.get("price")) if it.get("price") is not None else None),
            )
            if not model.walmart_link or not model.walmart_link.strip():
                continue
            validated.append(model)
        except Exception:
            continue
    if not validated:
        out = UploadWalmartLinksResult(status="ok", message="No valid items to update", updated=[], skipped=[])
        return json.dumps(out.model_dump(), ensure_ascii=False)

    walmart_key = client.detect_walmart_userfield_key()
    price_key = client.detect_price_userfield_key()
    if not isinstance(walmart_key, str) or not walmart_key:
        # We still allow updating price-only if price_key exists and items included price
        if not (isinstance(price_key, str) and price_key and any(v.price is not None for v in validated)):
            out = UploadWalmartLinksResult(status="error", message="Could not detect Walmart userfield key for products", updated=[], skipped=[int(v.product_id) for v in validated])
            return json.dumps(out.model_dump(), ensure_ascii=False)

    updated_ids: List[int] = []
    skipped_ids: List[int] = []
    for v in validated:
        pid = int(v.product_id)
        # First handle walmart link via userfields
        link_updated = False
        if isinstance(walmart_key, str) and walmart_key and v.walmart_link and v.walmart_link.strip():
            try:
                uf = client.get_product_userfields(pid)
            except Exception:
                uf = {}
            existing_link = uf.get(walmart_key)
            new_link = v.walmart_link.strip()
            if not (isinstance(existing_link, str) and existing_link.strip() == new_link):
                try:
                    client.set_product_userfields(pid, {walmart_key: new_link})
                    link_updated = True
                except Exception:
                    pass

        # Then handle price via stock booking add+consume to persist in recipe calc
        price_updated = False
        if v.price is not None:
            try:
                client.add_product_quantity_with_price(pid, quantity=1.0, price=float(v.price))
                # Consume same amount to keep stock unchanged
                client.consume_product_quantity(pid, quantity=1.0)
                price_updated = True
            except Exception:
                pass

        if link_updated or price_updated:
            updated_ids.append(pid)
        else:
            skipped_ids.append(pid)

    out = UploadWalmartLinksResult(
        status="ok",
        message=f"Updated {len(updated_ids)} products; skipped {len(skipped_ids)}",
        updated=updated_ids,
        skipped=skipped_ids,
    )
    return json.dumps(out.model_dump(), ensure_ascii=False)


def get_missing_walmart_links_json(base_url: Optional[str] = None, max_results: int = 5) -> str:
    """Return up to max_results products missing Walmart links and/or prices.
    
    Returns JSON with structure:
    {
      "status": "ok",
      "message": "Found N products missing links/prices",
      "items": [
        {
          "product_id": int,
          "product_name": str,
          "walmart_search_url": str,
          "missing_link": bool,
          "missing_price": bool
        },
        ...
      ],
      "total_missing": int
    }
    """
    from urllib.parse import quote_plus
    
    client = GrocyClient(base_url=base_url)
    
    # Detect the Walmart link userfield key
    walmart_key = client.detect_walmart_userfield_key()
    
    # Get all products
    try:
        products = client.list_all_products()
    except Exception as e:
        out = MissingWalmartLinksResult(
            status="error",
            message=f"Failed to list products: {e}",
            items=[],
            total_missing=0
        )
        return json.dumps(out.model_dump(), ensure_ascii=False)
    
    results: List[MissingWalmartLinkItem] = []
    
    for product in products:
        if not isinstance(product, dict):
            continue
        
        # Check if this is a root product (no parent_product_id)
        parent_id = product.get("parent_product_id")
        if parent_id is not None:
            try:
                if isinstance(parent_id, (int, float)) and int(parent_id) != 0:
                    continue  # Skip child products
                if isinstance(parent_id, str) and parent_id.strip() and int(parent_id.strip()) != 0:
                    continue  # Skip child products
            except (ValueError, TypeError):
                pass  # Treat as root if we can't parse
        
        # Get product ID and name
        product_id = product.get("id")
        product_name = product.get("name")
        
        if not isinstance(product_id, (int, float)) or not isinstance(product_name, str) or not product_name.strip():
            continue
        
        product_id = int(product_id)
        product_name = product_name.strip()
        
        # Check if Walmart link is missing
        missing_link = True
        if isinstance(walmart_key, str) and walmart_key:
            try:
                userfields = client.get_product_userfields(product_id)
                link_value = userfields.get(walmart_key)
                if isinstance(link_value, str) and link_value.strip():
                    missing_link = False
            except Exception:
                pass  # Treat as missing if we can't check
        
        # Check if price is missing (no stock entries with price > 0)
        missing_price = True
        try:
            stock_entries = client.get_product_stock_entries(product_id)
            if stock_entries:
                for entry in stock_entries:
                    price = entry.get("price")
                    if price is not None:
                        try:
                            if float(price) > 0:
                                missing_price = False
                                break
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass  # Treat as missing if we can't check
        
        # If either link or price is missing, add to results
        if missing_link or missing_price:
            walmart_search_url = f"https://www.walmart.com/search?q={quote_plus(product_name)}"
            results.append(
                MissingWalmartLinkItem(
                    product_id=product_id,
                    product_name=product_name,
                    walmart_search_url=walmart_search_url,
                    missing_link=missing_link,
                    missing_price=missing_price
                )
            )
            
            # Stop if we've reached max_results
            if len(results) >= max_results:
                break
    
    total_missing = len(results)
    out = MissingWalmartLinksResult(
        status="ok",
        message=f"Found {total_missing} products missing links/prices (showing up to {max_results})",
        items=[item.model_dump() for item in results],
        total_missing=total_missing
    )
    return json.dumps(out.model_dump(), ensure_ascii=False)


def get_shopping_list_cart_links_json(shopping_list_id: Optional[int] = 1, base_url: Optional[str] = None) -> str:
    """Build Walmart links for all shopping list items.
    
    For regular products with Walmart links: generates add-to-cart URLs.
    For placeholder products: generates Walmart search URLs.
    
    Returns simple NAME: LINK format, one per line:
    Product Name: https://...
    Another Product: https://...
    """
    import re
    import math
    from urllib.parse import quote_plus
    
    client = GrocyClient(base_url=base_url)
    
    # Detect the Walmart link userfield key
    walmart_key = client.detect_walmart_userfield_key()
    
    # Get shopping list items
    try:
        items = client.get_shopping_list_items(shopping_list_id=shopping_list_id)
    except Exception as e:
        return f"Error: Failed to get shopping list: {e}"
    
    # Get product name map
    try:
        name_map = client.get_product_name_map()
    except Exception:
        name_map = {}
    
    results: List[ShoppingListCartLinkItem] = []
    
    for item in items:
        product_id = item.get("product_id")
        if not isinstance(product_id, (int, float)):
            continue
        
        product_id = int(product_id)
        product_name = name_map.get(product_id)
        if not isinstance(product_name, str):
            product_name = f"Product {product_id}"
        
        # Extract quantity
        quantity = None
        for key in ("amount", "quantity", "amount_aggregated", "available_amount"):
            val = item.get(key)
            if isinstance(val, (int, float)):
                quantity = float(val)
                break
            if isinstance(val, str):
                try:
                    quantity = float(val)
                    break
                except Exception:
                    pass
        if quantity is None:
            quantity = 1.0
        
        # Get userfields once to check both placeholder status and Walmart link
        is_placeholder = False
        walmart_url = None
        link_type = "add_to_cart"
        
        try:
            userfields = client.get_product_userfields(product_id)
            # Check if product is a placeholder
            is_placeholder = bool(userfields.get("placeholder", False))
            
            # Try to get Walmart link and build add-to-cart URL (regardless of placeholder status)
            if isinstance(walmart_key, str) and walmart_key:
                product_url = userfields.get(walmart_key)
                
                if isinstance(product_url, str) and product_url.strip():
                    # Extract Walmart item ID from URL
                    # Pattern: .../ip/<name>/<item_id> (with optional query params)
                    m = re.search(r"/ip/[^/]+/(\d+)", product_url)
                    if m:
                        item_id = m.group(1)
                        # Calculate quantity (round up)
                        qty = int(math.ceil(quantity))
                        if qty < 1:
                            qty = 1
                        walmart_url = f"https://affil.walmart.com/cart/addToCart?items={item_id}|{qty}"
        except Exception:
            pass
        
        # Fallback to search URL if no Walmart link found
        if not walmart_url:
            walmart_url = f"https://www.walmart.com/search?q={quote_plus(product_name)}"
            link_type = "search"
        
        results.append(
            ShoppingListCartLinkItem(
                product_id=product_id,
                product_name=product_name,
                quantity=quantity,
                walmart_url=walmart_url,
                is_placeholder=is_placeholder,
                link_type=link_type
            )
        )
    
    # Return simple NAME: LINK format
    output_lines = []
    for item in results:
        output_lines.append(f"{item.product_name}: {item.walmart_url}")
    
    return "\n".join(output_lines) if output_lines else "No items in shopping list"


# ---- Recipe JSON wrappers (Pydantic-validated) ----
def get_recipes_json(base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    items = client.get_recipes()
    out: List[Dict[str, Any]] = []
    for it in items:
        try:
            out.append(
                RecipeOut(
                    id=int(it.get("id")) if isinstance(it.get("id"), (int, float)) else 0,
                    name=it.get("name") if isinstance(it.get("name"), str) else None,
                    base_servings=(int(it.get("base_servings")) if isinstance(it.get("base_servings"), (int, float)) else None),
                    description=(str(it.get("description")) if isinstance(it.get("description"), str) else None),
                ).model_dump()
            )
        except Exception:
            continue
    return json.dumps(out, ensure_ascii=False)


def get_recipe_protein_densities_json(base_url: Optional[str] = None) -> str:
    """Get all recipes with their protein per 100 cal values, sorted by protein density.
    
    This is used to calculate percentile thresholds for the protein filter slider.
    
    Returns:
        JSON string with list of recipes sorted by protein_per_100cal (descending)
    """
    client = GrocyClient(base_url=base_url)
    all_recipes = client.get_recipes()
    
    # Filter out meal plan entries
    import re
    date_pattern = re.compile(r'^\d{4}-\d{1,2}')
    recipe_densities = []
    
    for r in all_recipes:
        # Skip meal plan entries
        rid = r.get('id')
        if isinstance(rid, (int, float)) and int(rid) < 0:
            continue
        rtype = r.get('type', '')
        if isinstance(rtype, str) and 'mealplan' in rtype.lower():
            continue
        rname = r.get('name', '')
        if isinstance(rname, str) and date_pattern.match(rname):
            continue
        
        # Get userfields for macros
        if not isinstance(rid, (int, float)):
            continue
        rid = int(rid)
        
        try:
            userfields = client._get(f"/userfields/recipes/{rid}")
            if not isinstance(userfields, dict):
                userfields = {}
        except Exception:
            userfields = {}
        
        # Calculate protein per 100 cal
        cals = float(userfields.get('recipe_calories', 0) or 0)
        protein = float(userfields.get('recipe_proteins', 0) or 0)
        
        if cals > 0:
            protein_per_100 = (protein / cals) * 100
            recipe_densities.append({
                'recipe_id': rid,
                'name': r.get('name', 'Unnamed Recipe'),
                'protein_per_100cal': round(protein_per_100, 2)
            })
    
    # Sort by protein density descending
    recipe_densities.sort(key=lambda x: x['protein_per_100cal'], reverse=True)
    
    return json.dumps({'recipes': recipe_densities}, ensure_ascii=False)


def get_recipe_carbs_densities_json(base_url: Optional[str] = None) -> str:
    """Get all recipes with their carbs per 100 cal values, sorted by carbs density.
    
    This is used to calculate percentile thresholds for the carbs filter slider.
    
    Returns:
        JSON string with list of recipes sorted by carbs_per_100cal (descending)
    """
    client = GrocyClient(base_url=base_url)
    all_recipes = client.get_recipes()
    
    # Filter out meal plan entries
    import re
    date_pattern = re.compile(r'^\d{4}-\d{1,2}')
    recipe_densities = []
    
    for r in all_recipes:
        # Skip meal plan entries
        rid = r.get('id')
        if isinstance(rid, (int, float)) and int(rid) < 0:
            continue
        rtype = r.get('type', '')
        if isinstance(rtype, str) and 'mealplan' in rtype.lower():
            continue
        rname = r.get('name', '')
        if isinstance(rname, str) and date_pattern.match(rname):
            continue
        
        # Get userfields for macros
        if not isinstance(rid, (int, float)):
            continue
        rid = int(rid)
        
        try:
            userfields = client._get(f"/userfields/recipes/{rid}")
            if not isinstance(userfields, dict):
                userfields = {}
        except Exception:
            userfields = {}
        
        # Calculate carbs per 100 cal
        cals = float(userfields.get('recipe_calories', 0) or 0)
        carbs = float(userfields.get('recipe_carbs', 0) or 0)
        
        if cals > 0:
            carbs_per_100 = (carbs / cals) * 100
            recipe_densities.append({
                'recipe_id': rid,
                'name': r.get('name', 'Unnamed Recipe'),
                'carbs_per_100cal': round(carbs_per_100, 2)
            })
    
    # Sort by carbs density descending
    recipe_densities.sort(key=lambda x: x['carbs_per_100cal'], reverse=True)
    
    return json.dumps({'recipes': recipe_densities}, ensure_ascii=False)


def get_recipe_protein_max_json(base_url: Optional[str] = None) -> str:
    """Get the 4th highest protein per 100 cal value from all recipes.
    
    This is used to set the max value for the protein filter slider.
    
    Returns:
        JSON string with the max protein per 100 cal value
    """
    client = GrocyClient(base_url=base_url)
    all_recipes = client.get_recipes()
    
    # Filter out meal plan entries
    import re
    date_pattern = re.compile(r'^\d{4}-\d{1,2}')
    protein_values = []
    
    for r in all_recipes:
        # Skip meal plan entries
        rid = r.get('id')
        if isinstance(rid, (int, float)) and int(rid) < 0:
            continue
        rtype = r.get('type', '')
        if isinstance(rtype, str) and 'mealplan' in rtype.lower():
            continue
        rname = r.get('name', '')
        if isinstance(rname, str) and date_pattern.match(rname):
            continue
        
        # Get userfields for macros
        if not isinstance(rid, (int, float)):
            continue
        rid = int(rid)
        
        try:
            userfields = client._get(f"/userfields/recipes/{rid}")
            if not isinstance(userfields, dict):
                userfields = {}
        except Exception:
            userfields = {}
        
        # Calculate protein per 100 cal
        cals = float(userfields.get('recipe_calories', 0) or 0)
        protein = float(userfields.get('recipe_proteins', 0) or 0)
        
        if cals > 0:
            protein_per_100 = (protein / cals) * 100
            protein_values.append(protein_per_100)
    
    # Sort descending and get 4th highest (or max if less than 4 recipes)
    protein_values.sort(reverse=True)
    
    if len(protein_values) >= 4:
        max_protein = protein_values[3]  # 4th highest (0-indexed)
    elif len(protein_values) > 0:
        max_protein = protein_values[-1]  # Lowest if less than 4 recipes
    else:
        max_protein = 10  # Default fallback
    
    # Round up to nearest 0.5
    import math
    max_protein = math.ceil(max_protein * 2) / 2
    
    return json.dumps({"max_protein_per_100cal": max_protein}, ensure_ascii=False)


def get_filtered_recipes_json(
    can_be_made: Optional[bool] = None,
    min_carbs_per_100cal: Optional[float] = None,
    max_carbs_per_100cal: Optional[float] = None,
    min_fats_per_100cal: Optional[float] = None,
    max_fats_per_100cal: Optional[float] = None,
    min_protein_per_100cal: Optional[float] = None,
    max_protein_per_100cal: Optional[float] = None,
    min_active_time: Optional[int] = None,
    max_active_time: Optional[int] = None,
    min_total_time: Optional[int] = None,
    max_total_time: Optional[int] = None,
    base_url: Optional[str] = None
) -> str:
    """Get filtered recipes based on various criteria.
    
    Args:
        can_be_made: Filter by recipes that can be made with current inventory
        min_carbs_per_100cal: Minimum carbs per 100 calories
        max_carbs_per_100cal: Maximum carbs per 100 calories
        min_fats_per_100cal: Minimum fats per 100 calories
        max_fats_per_100cal: Maximum fats per 100 calories
        min_protein_per_100cal: Minimum protein per 100 calories
        max_protein_per_100cal: Maximum protein per 100 calories
        min_active_time: Minimum active cook time in minutes
        max_active_time: Maximum active cook time in minutes
        min_total_time: Minimum total cook time in minutes
        max_total_time: Maximum total cook time in minutes
        base_url: Grocy API base URL
    
    Returns:
        JSON string with filtered recipes including macro information
    """
    client = GrocyClient(base_url=base_url)
    all_recipes = client.get_recipes()
    
    # Get cookable recipe IDs if can_be_made filter is enabled
    cookable_recipe_ids = None
    if can_be_made:
        try:
            cookable_recipes = client.list_cookable_recipes()
            cookable_recipe_ids = {int(r.get('id')) for r in cookable_recipes if r.get('id') is not None}
        except Exception:
            # If we can't get cookable recipes, return empty list
            cookable_recipe_ids = set()
    
    # Filter out meal plan entries
    import re
    date_pattern = re.compile(r'^\d{4}-\d{1,2}')
    filtered_recipes = []
    
    for r in all_recipes:
        # Skip meal plan entries
        rid = r.get('id')
        if isinstance(rid, (int, float)) and int(rid) < 0:
            continue
        rtype = r.get('type', '')
        if isinstance(rtype, str) and 'mealplan' in rtype.lower():
            continue
        rname = r.get('name', '')
        if isinstance(rname, str) and date_pattern.match(rname):
            continue
        
        # Get userfields for macros
        if not isinstance(rid, (int, float)):
            continue
        rid = int(rid)
        
        # Apply can_be_made filter
        if cookable_recipe_ids is not None and rid not in cookable_recipe_ids:
            continue
        
        try:
            userfields = client._get(f"/userfields/recipes/{rid}")
            if not isinstance(userfields, dict):
                userfields = {}
        except Exception:
            userfields = {}
        
        # Get macros
        calories = float(userfields.get('recipe_calories', 0) or 0)
        carbs = float(userfields.get('recipe_carbs', 0) or 0)
        fats = float(userfields.get('recipe_fats', 0) or 0)
        protein = float(userfields.get('recipe_proteins', 0) or 0)
        
        # Calculate per 100 cal
        carbs_per_100 = (carbs / calories * 100) if calories > 0 else 0
        fats_per_100 = (fats / calories * 100) if calories > 0 else 0
        protein_per_100 = (protein / calories * 100) if calories > 0 else 0
        
        # Get times from recipe fields
        active_time = r.get('desired_servings', 0)  # Using desired_servings as active_time placeholder
        total_time = r.get('not_check_shoppinglist', 0)  # Using not_check_shoppinglist as total_time placeholder
        
        # Apply filters - skip recipes that don't meet criteria
        if min_carbs_per_100cal is not None and carbs_per_100 < min_carbs_per_100cal:
            continue
        if max_carbs_per_100cal is not None and carbs_per_100 > max_carbs_per_100cal:
            continue
        if min_fats_per_100cal is not None and fats_per_100 < min_fats_per_100cal:
            continue
        if max_fats_per_100cal is not None and fats_per_100 > max_fats_per_100cal:
            continue
        if min_protein_per_100cal is not None:
            if protein_per_100 < min_protein_per_100cal:
                continue
        if max_protein_per_100cal is not None and protein_per_100 > max_protein_per_100cal:
            continue
        if min_active_time is not None and active_time < min_active_time:
            continue
        if max_active_time is not None and active_time > max_active_time:
            continue
        if min_total_time is not None and total_time < min_total_time:
            continue
        if max_total_time is not None and total_time > max_total_time:
            continue
        
        # Count how many times this recipe is in today's meal plan
        meal_plan_count = 0
        try:
            meal_plan_entries = client._get("/objects/meal_plan")
            if isinstance(meal_plan_entries, list):
                for entry in meal_plan_entries:
                    if entry.get('recipe_id') == rid and entry.get('type') == 'recipe':
                        meal_plan_count += 1
        except Exception:
            pass
        
        # Build result
        filtered_recipes.append({
            'id': rid,
            'name': r.get('name', 'Unnamed Recipe'),
            'description': r.get('description', ''),
            'base_servings': r.get('base_servings', 1),
            'calories': int(calories),
            'carbs': round(carbs, 1),
            'fats': round(fats, 1),
            'protein': round(protein, 1),
            'active_time': int(active_time) if active_time else None,
            'total_time': int(total_time) if total_time else None,
            'meal_plan_count': meal_plan_count
        })
    
    return json.dumps(filtered_recipes, ensure_ascii=False)


def get_recipe_json(recipe_id: int, base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    raw = client.get_recipe(int(recipe_id))
    try:
        validated = RecipeOut(
            id=int(raw.get("id")) if isinstance(raw.get("id"), (int, float)) else int(recipe_id),
            name=raw.get("name") if isinstance(raw.get("name"), str) else None,
            base_servings=(int(raw.get("base_servings")) if isinstance(raw.get("base_servings"), (int, float)) else None),
            description=(str(raw.get("description")) if isinstance(raw.get("description"), str) else None),
        )
        return json.dumps(validated.model_dump(), ensure_ascii=False)
    except Exception:
        fallback = RecipeOut(id=int(recipe_id))
        return json.dumps(fallback.model_dump(), ensure_ascii=False)


def create_recipe_json(fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    payload = dict(fields or {})
    if not payload.get("name"):
        raise ValueError("'name' is required to create a recipe")
    resp = client.create_recipe(payload)
    rid = client._extract_created_id_from_response(resp)
    if not isinstance(rid, int):
        # Some Grocy deployments may return the full object or string id
        try:
            rid = int(resp.get("id")) if isinstance(resp, dict) and isinstance(resp.get("id"), (int, float)) else None
        except Exception:
            rid = None
    out = StatusRecipeOut(status="ok", message=f"Created recipe '{payload['name']}'", recipe_id=int(rid) if isinstance(rid, int) else None)
    return json.dumps(out.model_dump(), ensure_ascii=False)


def update_recipe_json(recipe_id: int, fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.update_recipe(int(recipe_id), dict(fields or {}))
    out = StatusRecipeOut(status="ok", message=f"Recipe {int(recipe_id)} updated", recipe_id=int(recipe_id))
    return json.dumps(out.model_dump(), ensure_ascii=False)


def delete_recipe_json(recipe_id: int, base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.delete_recipe(int(recipe_id))
    out = StatusMessageOut(status="ok", message=f"Recipe {int(recipe_id)} deleted")
    return json.dumps(out.model_dump(), ensure_ascii=False)


def list_recipe_ingredients_json(recipe_id: int, base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    items = client.list_recipe_ingredients(int(recipe_id))
    
    # Fetch product name map
    name_map: Dict[int, str] = {}
    try:
        name_map = client.get_product_name_map()
    except Exception:
        name_map = {}
    
    # Fetch inventory to check stock status
    inventory_map: Dict[str, float] = {}
    try:
        inventory = client.get_inventory()
        for inv_item in inventory:
            item_name = _extract_name(inv_item)
            item_qty = _extract_quantity(inv_item)
            if item_name and isinstance(item_qty, (int, float)):
                inventory_map[item_name] = float(item_qty)
    except Exception:
        inventory_map = {}
    
    out: List[Dict[str, Any]] = []
    for it in items:
        try:
            product_id = int(it.get("product_id")) if isinstance(it.get("product_id"), (int, float)) else None
            product_name = name_map.get(product_id) if product_id else None
            
            # Check placeholder status and get macro userfields
            is_placeholder = False
            calories = None
            carbs = None
            fats = None
            protein = None
            needs_purchase = False
            
            if product_id:
                try:
                    userfields = client.get_product_userfields(product_id)
                    is_placeholder = bool(userfields.get("placeholder", False))
                    
                    # Get macro fields from userfields
                    calories_raw = userfields.get("Calories_Per_Serving")
                    if isinstance(calories_raw, (int, float)):
                        calories = float(calories_raw)
                    
                    carbs_raw = userfields.get("Carbs")
                    if isinstance(carbs_raw, (int, float)):
                        carbs = float(carbs_raw)
                    
                    fats_raw = userfields.get("Fats")
                    if isinstance(fats_raw, (int, float)):
                        fats = float(fats_raw)
                    
                    protein_raw = userfields.get("Protein")
                    if isinstance(protein_raw, (int, float)):
                        protein = float(protein_raw)
                    
                    # Check if needs purchase (placeholder AND not in stock)
                    if is_placeholder and product_name:
                        stock_qty = inventory_map.get(product_name, 0)
                        needs_purchase = stock_qty <= 0
                except Exception:
                    pass
            
            out.append(
                IngredientOut(
                    id=(int(it.get("id")) if isinstance(it.get("id"), (int, float)) else None),
                    recipe_id=(int(it.get("recipe_id")) if isinstance(it.get("recipe_id"), (int, float)) else None),
                    product_id=product_id,
                    product_name=product_name,
                    amount=(float(it.get("amount")) if isinstance(it.get("amount"), (int, float)) else None),
                    qu_id=(int(it.get("qu_id")) if isinstance(it.get("qu_id"), (int, float)) else None),
                    note=(str(it.get("note")) if isinstance(it.get("note"), str) else None),
                    is_placeholder=is_placeholder,
                    needs_purchase=needs_purchase,
                    calories=calories,
                    carbs=carbs,
                    fats=fats,
                    protein=protein,
                ).model_dump()
            )
        except Exception:
            continue
    return json.dumps(out, ensure_ascii=False)


def add_recipe_ingredient_json(fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    resp = client.add_recipe_ingredient(dict(fields or {}))
    iid = client._extract_created_id_from_response(resp)
    out = StatusIngredientOut(status="ok", message="Ingredient added to recipe", ingredient_id=int(iid) if isinstance(iid, int) else None)
    return json.dumps(out.model_dump(), ensure_ascii=False)


def update_recipe_ingredient_json(ingredient_id: int, fields: Dict[str, Any], base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.update_recipe_ingredient(int(ingredient_id), dict(fields or {}))
    out = StatusIngredientOut(status="ok", message=f"Ingredient {int(ingredient_id)} updated", ingredient_id=int(ingredient_id))
    return json.dumps(out.model_dump(), ensure_ascii=False)


def delete_recipe_ingredient_json(ingredient_id: int, base_url: Optional[str] = None) -> str:
    client = GrocyClient(base_url=base_url)
    client.delete_recipe_ingredient(int(ingredient_id))
    out = StatusMessageOut(status="ok", message=f"Ingredient {int(ingredient_id)} deleted")
    return json.dumps(out.model_dump(), ensure_ascii=False)


# ---- Macro Tracking Tools ----
def set_product_price_json(product_id: int, price: float, base_url: Optional[str] = None) -> str:
    """Set product price via stock booking (add 1 at price, then consume 1).
    
    Args:
        product_id: int
        price: float (unit price)
        
    Returns:
        JSON str {status, message, product_id, price}
    """
    try:
        client = GrocyClient(base_url=base_url)
        # Add 1 unit at specified price
        client.add_product_quantity_with_price(product_id, quantity=1.0, price=float(price))
        # Consume 1 to keep stock unchanged
        client.consume_product_quantity(product_id, quantity=1.0)
        
        return json.dumps({
            "status": "ok",
            "message": f"Set price for product {product_id} to ${price}",
            "product_id": product_id,
            "price": float(price)
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def import_shopping_list_json(shopping_list_id: Optional[int] = 1, base_url: Optional[str] = None) -> str:
    """Import (purchase) all non-placeholder items from the shopping list.
    
    Purchases one container per shopping list entry for each non-placeholder item,
    using the last known price for accurate stock value tracking. Items are then
    removed from the shopping list.
    
    Args:
        shopping_list_id: Shopping list ID (default 1)
        base_url: Optional Grocy base URL
        
    Returns:
        JSON str {status, message, purchased_count, skipped_count, removed_count, errors}
    """
    try:
        client = GrocyClient(base_url=base_url)
        
        # Get shopping list items
        shopping_list = client._get(f"/objects/shopping_list?query%5B%5D=shopping_list_id%3D{shopping_list_id}")
        if isinstance(shopping_list, dict) and "data" in shopping_list:
            shopping_list = shopping_list["data"]
        
        if not isinstance(shopping_list, list):
            return json.dumps({
                "status": "error",
                "message": f"Expected list of shopping list items, got {type(shopping_list)}"
            }, ensure_ascii=False)
        
        purchased_count = 0
        skipped_count = 0
        removed_count = 0
        errors = []
        items_to_remove = []  # Track (product_id, amount) for items to remove from list
        
        for item in shopping_list:
            try:
                product_id = item.get("product_id")
                if not product_id:
                    continue
                    
                pid = int(product_id)
                amount = float(item.get("amount", 1))
                
                # Get product info
                product = client._get(f"/objects/products/{pid}")
                name = product.get("name", f"product_{pid}")
                
                # Check if it's a placeholder
                try:
                    userfields = client.get_product_userfields(pid)
                    placeholder_value = userfields.get("placeholder") or userfields.get("Placeholder")
                    is_placeholder = placeholder_value is True or placeholder_value == 1 or placeholder_value == "1"
                    
                    if is_placeholder:
                        skipped_count += 1
                        continue
                except Exception:
                    # If we can't check userfields, assume not a placeholder
                    pass
                
                # Get the last price for this product
                last_price = None
                try:
                    stock_details = client._get(f"/stock/products/{pid}")
                    last_price = stock_details.get("last_price") or stock_details.get("current_price")
                    if last_price is not None:
                        last_price = float(last_price)
                        if last_price <= 0:
                            last_price = None
                except Exception:
                    last_price = None
                
                # Purchase the amount specified in shopping list (in containers)
                # Use price if available to maintain stock value accuracy
                if last_price is not None and last_price > 0:
                    client.add_product_quantity_with_price(pid, quantity=amount, price=last_price)
                else:
                    client.add_product_quantity(pid, quantity=amount)
                purchased_count += 1
                
                # Track for removal from shopping list
                items_to_remove.append((pid, amount))
                
            except Exception as e:
                errors.append(f"Product {item.get('product_id', '?')}: {str(e)}")
                continue
        
        # Remove successfully purchased items from shopping list
        for pid, amount in items_to_remove:
            try:
                client.shopping_list_remove_product(product_id=pid, amount=amount, shopping_list_id=shopping_list_id)
                removed_count += 1
            except Exception as e:
                errors.append(f"Failed to remove product {pid} from shopping list: {str(e)}")
        
        return json.dumps({
            "status": "ok",
            "message": f"Imported {purchased_count} items, skipped {skipped_count} placeholders, removed {removed_count} from list",
            "purchased_count": purchased_count,
            "skipped_count": skipped_count,
            "removed_count": removed_count,
            "errors": errors
        }, ensure_ascii=False)
        
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": str(exc)
        }, ensure_ascii=False)


def create_temp_item_json(name: str, calories: float, carbs: float, fats: float, protein: float, day: Optional[str] = None) -> str:
    """Create temporary macro tracking item.
    
    Args:
        name: Item name
        calories: Total calories (not per-serving)
        carbs: Carbs in grams
        fats: Fats in grams
        protein: Protein in grams
        day: YYYY-MM-DD format (defaults to current day)
        
    Returns:
        JSON {status, message, temp_item_id}
    """
    try:
        import sys
        from pathlib import Path
        # Add parent to path for macro_tracking
        _parent = Path(__file__).parent.parent
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        
        from macro_tracking import macro_db, day_utils
        
        if day is None:
            day = day_utils.get_current_day_timestamp()
        
        item_id = macro_db.create_temp_item(
            name=name,
            calories=float(calories),
            carbs=float(carbs),
            fats=float(fats),
            protein=float(protein),
            day=day
        )
        
        return json.dumps({
            "status": "ok",
            "message": f"Created temp item '{name}'",
            "temp_item_id": item_id
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def delete_temp_item_json(temp_item_id: int) -> str:
    """Delete temporary item.
    
    Args:
        temp_item_id: ID of temp item to delete
        
    Returns:
        JSON {status, message}
    """
    try:
        import sys
        from pathlib import Path
        _parent = Path(__file__).parent.parent
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        
        from macro_tracking import macro_db
        
        success = macro_db.delete_temp_item(temp_item_id)
        if success:
            return json.dumps({
                "status": "ok",
                "message": f"Deleted temp item {temp_item_id}"
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "status": "error",
                "message": f"Temp item {temp_item_id} not found"
            }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def get_day_macros_json(day: Optional[str] = None) -> str:
    """Get consumed/planned macros for a day.
    
    Args:
        day: YYYY-MM-DD format (defaults to current day)
        
    Returns:
        JSON from macro_aggregator.get_day_summary()
    """
    try:
        import sys
        from pathlib import Path
        _parent = Path(__file__).parent.parent
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        
        from macro_tracking import macro_aggregator, day_utils
        
        if day is None:
            day = day_utils.get_current_day_timestamp()
        
        summary = macro_aggregator.get_day_summary(day)
        return json.dumps(summary, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def get_recent_days_json(page: int = 0, limit: int = 4) -> str:
    """Get recent days with macro activity (paginated).
    
    Gets ALL days with either meal plan entries or temp items,
    then returns a paginated subset.
    
    Args:
        page: Page number (0-indexed)
        limit: Items per page
        
    Returns:
        JSON with days list, summaries, and pagination info
    """
    try:
        import sys
        from pathlib import Path
        _parent = Path(__file__).parent.parent
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        
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
        
        return json.dumps({
            "days": days_data,
            "total_pages": total_pages,
            "current_page": page,
            "total_days": total_days
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def mark_meal_plan_done_json(entry_id: int, base_url: Optional[str] = None) -> str:
    """Mark a meal plan entry as consumed/done.
    
    Args:
        entry_id: Meal plan entry ID
        
    Returns:
        JSON {status, message}
    """
    try:
        client = GrocyClient(base_url=base_url)
        
        # Update meal plan entry to mark as done
        # Grocy uses different field names - try the common ones
        for done_field in ["done", "is_done", "completed"]:
            try:
                client.update_meal_plan_entry(entry_id, {done_field: True})
                return json.dumps({
                    "status": "ok",
                    "message": f"Marked meal plan entry {entry_id} as done"
                }, ensure_ascii=False)
            except Exception:
                continue
        
        # If all fail, raise error
        raise RuntimeError("Could not mark meal plan entry as done - unknown field name")
        
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def create_placeholder_product_json(name: str, estimated_calories: float, estimated_carbs: float, 
                                   estimated_fats: float, estimated_protein: float, 
                                   estimated_price: Optional[float] = None, base_url: Optional[str] = None) -> str:
    """Create placeholder product in Grocy with estimated values.
    
    Args:
        name: Product name
        estimated_calories: Estimated calories per serving
        estimated_carbs: Estimated carbs per serving
        estimated_fats: Estimated fats per serving
        estimated_protein: Estimated protein per serving
        estimated_price: Optional estimated price
        
    Returns:
        JSON {status, message, product_id}
    """
    try:
        client = GrocyClient(base_url=base_url)
        
        # Create product with default location/units
        product_fields = {
            "name": name,
            "location_id": int(os.getenv("GROCY_DEFAULT_LOCATION_ID", "2")),
            "qu_id_purchase": int(os.getenv("GROCY_DEFAULT_QU_ID_PURCHASE", "2")),
            "qu_id_stock": int(os.getenv("GROCY_DEFAULT_QU_ID_STOCK", "2")),
        }
        
        resp = client.create_product(product_fields)
        product_id = client._extract_created_id_from_response(resp)
        
        if not isinstance(product_id, int):
            product_id = client.find_product_id_by_name(name)
        
        if not isinstance(product_id, int):
            raise RuntimeError("Could not determine created product ID")
        
        # Set userfields with placeholder flag and estimated macros
        userfield_updates = {
            "placeholder": True,
            "Calories_Per_Serving": float(estimated_calories),
            "Carbs": float(estimated_carbs),
            "Fats": float(estimated_fats),
            "Protein": float(estimated_protein),
            "num_servings": 1.0,  # Default to 1 serving
        }
        
        client.set_product_userfields(product_id, userfield_updates)
        
        # Set price if provided
        if estimated_price is not None and float(estimated_price) > 0:
            try:
                client.add_product_quantity_with_price(product_id, 1.0, float(estimated_price))
                client.consume_product_quantity(product_id, 1.0)
            except Exception:
                pass
        
        return json.dumps({
            "status": "ok",
            "message": f"Created placeholder product '{name}'",
            "product_id": product_id
        }, ensure_ascii=False)
        
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)




__all__ = [
    "GrocyClient",
    "get_inventory_json",
    "increase_product_quantity_json",
    "consume_product_quantity_json",
    "get_shopping_list_json",
    "create_product_json",
    "ensure_product_exists_json",
    "shopping_list_add_product_json",
    "shopping_list_remove_product_json",
    "shopping_list_clear_json",
    "get_meal_plan_json",
    "add_meal_to_plan_json",
    "update_meal_plan_entry_json",
    "delete_meal_plan_entry_json",
    "get_meal_plan_sections_json",
    "get_cookable_recipes_json",
    "get_recipes_json",
    "get_recipe_json",
    "create_recipe_json",
    "update_recipe_json",
    "delete_recipe_json",
    "list_recipe_ingredients_json",
    "add_recipe_ingredient_json",
    "update_recipe_ingredient_json",
    "delete_recipe_ingredient_json",
    "upload_walmart_links_json",
    "get_missing_walmart_links_json",
    "get_shopping_list_cart_links_json",
    # Macro tracking tools
    "set_product_price_json",
    "create_temp_item_json",
    "delete_temp_item_json",
    "get_day_macros_json",
    "mark_meal_plan_done_json",
    "create_placeholder_product_json",
]
