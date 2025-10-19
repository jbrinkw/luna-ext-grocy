"""Grocy extension tools for Luna.

All tools follow the Luna tool schema:
- Names: GROCY_{GET|UPDATE|ACTION}_VerbNoun
- Pydantic-validated inputs
- Return: (success: bool, content: str)
- Docstrings: summary, Example Prompt, Example Response, Example Args
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Tuple
import json
import sys
from pathlib import Path

# Add lib to path for imports
_lib_path = Path(__file__).parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

# Import from lib modules
from core.client import GrocyClient
from services.inventory import InventoryService
from services.products import ProductService  
from services.shopping import ShoppingService
from services.recipes import RecipeService
from services.meal_plan import MealPlanService
from services.userfields import UserfieldService
from integrations.macros import get_day_macros, get_recent_days, create_temp_item, delete_temp_item


SYSTEM_PROMPT = """The user has access to Grocy inventory management tools for tracking food, recipes, meal plans, and shopping lists."""


# ============================================================================
# INVENTORY TOOLS
# ============================================================================

class GROCY_GET_InventoryArgs(BaseModel):
    """Arguments for getting inventory."""
    pass


def GROCY_GET_Inventory() -> Tuple[bool, str]:
    """Get the current inventory with product names, quantities, and expiry dates.
    
    Example Prompt: show me what's in my inventory
    Example Response: [{"name": "Milk", "quantity": 2.0, "expiry": "2025-10-25"}, ...]
    Example Args: {}
    """
    try:
        client = GrocyClient()
        raw_items = client.get_inventory()
        simplified = []
        for item in raw_items:
            product = item.get("product", {})
            name = product.get("name") or item.get("name") or item.get("product_name")
            quantity = item.get("amount") or item.get("stock_amount") or item.get("quantity")
            expiry = item.get("best_before_date") or item.get("due_date")
            simplified.append({"name": name, "quantity": quantity, "expiry": expiry})
        return (True, json.dumps(simplified, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting inventory: {e}")


class GROCY_UPDATE_AddProductQuantityArgs(BaseModel):
    """Arguments for adding product quantity."""
    product_id: int = Field(..., description="Product ID to add stock to")
    quantity: float = Field(..., description="Quantity to add")


def GROCY_UPDATE_AddProductQuantity(product_id: int, quantity: float) -> Tuple[bool, str]:
    """Add (purchase) quantity to a product's inventory.
    
    Example Prompt: add 2 units of milk to inventory (milk is product 5)
    Example Response: {"status": "ok", "message": "Increased product 5 by 2.0"}
    Example Args: {"product_id": 5, "quantity": 2.0}
    """
    try:
        _ = GROCY_UPDATE_AddProductQuantityArgs(product_id=product_id, quantity=quantity)
        client = GrocyClient()
        
        # Check if placeholder
        try:
            userfields = client.get_product_userfields(product_id)
            if userfields.get("placeholder", False):
                return (False, json.dumps({"status": "error", "message": "Cannot add stock to placeholder items"}))
        except Exception:
            pass
        
        client.add_product_quantity(product_id=product_id, quantity=quantity)
        return (True, json.dumps({"status": "ok", "message": f"Increased product {product_id} by {quantity}"}))
    except Exception as e:
        return (False, f"Error adding product quantity: {e}")


class GROCY_UPDATE_ConsumeProductArgs(BaseModel):
    """Arguments for consuming product."""
    product_id: int = Field(..., description="Product ID to consume")
    quantity: float = Field(..., description="Quantity to consume")
    add_to_meal_plan: bool = Field(False, description="If true, add to today's meal plan and mark done")


def GROCY_UPDATE_ConsumeProduct(product_id: int, quantity: float, add_to_meal_plan: bool = False) -> Tuple[bool, str]:
    """Consume (remove) quantity from a product's inventory.
    
    Example Prompt: I ate 1 serving of chicken breast
    Example Response: {"status": "ok", "message": "Consumed product 12 by 1.0"}
    Example Args: {"product_id": 12, "quantity": 1.0, "add_to_meal_plan": true}
    Notes: Set add_to_meal_plan=true to track macros for consumed items.
    """
    try:
        _ = GROCY_UPDATE_ConsumeProductArgs(product_id=product_id, quantity=quantity, add_to_meal_plan=add_to_meal_plan)
        client = GrocyClient()
        
        # Check if placeholder
        try:
            userfields = client.get_product_userfields(product_id)
            if userfields.get("placeholder", False):
                return (False, json.dumps({"status": "error", "message": "Cannot consume placeholder items"}))
        except Exception:
            pass
        
        client.consume_product_quantity(product_id=product_id, quantity=quantity)
        message = f"Consumed product {product_id} by {quantity}"
        
        if add_to_meal_plan:
            try:
                from macro_tracking import day_utils
                today = day_utils.get_current_day_timestamp()
                product = client._get(f"/objects/products/{product_id}")
                qu_id = product.get("qu_id_stock") or product.get("qu_id_purchase")
                
                meal_fields = {
                    "day": today,
                    "type": "product",
                    "product_id": int(product_id),
                    "product_amount": float(quantity),
                    "product_qu_id": qu_id
                }
                client.create_meal_plan_entry(meal_fields)
                message += " and added to meal plan"
            except Exception as e:
                message += f" (meal plan error: {e})"
        
        return (True, json.dumps({"status": "ok", "message": message}))
    except Exception as e:
        return (False, f"Error consuming product: {e}")


# ============================================================================
# PRODUCT TOOLS
# ============================================================================

class GROCY_GET_ProductsArgs(BaseModel):
    """Arguments for getting products list."""
    pass


def GROCY_GET_Products() -> Tuple[bool, str]:
    """Get all products with id, name, and placeholder status.
    
    Example Prompt: list all products
    Example Response: [{"id": 1, "name": "Milk", "is_placeholder": false}, ...]
    Example Args: {}
    """
    try:
        client = GrocyClient()
        products = client.get_products()
        result = []
        for p in products:
            pid = p.get("id")
            name = p.get("name")
            is_placeholder = False
            try:
                userfields = client.get_product_userfields(pid)
                is_placeholder = bool(userfields.get("placeholder", False))
            except Exception:
                pass
            result.append({"id": pid, "name": name, "is_placeholder": is_placeholder})
        return (True, json.dumps(result, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting products: {e}")


class GROCY_ACTION_CreateProductArgs(BaseModel):
    """Arguments for creating a product."""
    name: str = Field(..., description="Product name")
    location_id: Optional[int] = Field(None, description="Location ID")
    qu_id_purchase: Optional[int] = Field(None, description="Purchase quantity unit ID")
    qu_id_stock: Optional[int] = Field(None, description="Stock quantity unit ID")


def GROCY_ACTION_CreateProduct(name: str, location_id: Optional[int] = None, 
                                qu_id_purchase: Optional[int] = None, 
                                qu_id_stock: Optional[int] = None) -> Tuple[bool, str]:
    """Create a new product in Grocy.
    
    Example Prompt: create a new product called "Organic Eggs"
    Example Response: {"status": "ok", "message": "Created product", "product_id": 42}
    Example Args: {"name": "Organic Eggs"}
    """
    try:
        _ = GROCY_ACTION_CreateProductArgs(name=name, location_id=location_id, 
                                           qu_id_purchase=qu_id_purchase, qu_id_stock=qu_id_stock)
        client = GrocyClient()
        fields = {"name": name}
        if location_id:
            fields["location_id"] = location_id
        if qu_id_purchase:
            fields["qu_id_purchase"] = qu_id_purchase
        if qu_id_stock:
            fields["qu_id_stock"] = qu_id_stock
        
        result = client.create_product(fields)
        product_id = result.get("created_object_id") or result.get("id")
        return (True, json.dumps({"status": "ok", "message": "Created product", "product_id": product_id}))
    except Exception as e:
        return (False, f"Error creating product: {e}")


class GROCY_ACTION_CreatePlaceholderArgs(BaseModel):
    """Arguments for creating a placeholder product."""
    name: str = Field(..., description="Product name")
    estimated_calories: float = Field(..., description="Estimated calories per serving")
    estimated_carbs: float = Field(..., description="Estimated carbs in grams")
    estimated_fats: float = Field(..., description="Estimated fats in grams")
    estimated_protein: float = Field(..., description="Estimated protein in grams")


def GROCY_ACTION_CreatePlaceholder(name: str, estimated_calories: float, 
                                    estimated_carbs: float, estimated_fats: float, 
                                    estimated_protein: float) -> Tuple[bool, str]:
    """Create a placeholder product for planning (not real inventory).
    
    Example Prompt: create a placeholder for "Chicken Breast" with 165 cal, 0g carbs, 3.6g fat, 31g protein
    Example Response: {"status": "ok", "product_id": 55, "message": "Created placeholder product"}
    Example Args: {"name": "Chicken Breast", "estimated_calories": 165, "estimated_carbs": 0, "estimated_fats": 3.6, "estimated_protein": 31}
    Notes: Placeholders are for recipe planning before purchasing. Cannot be added to/consumed from inventory.
    """
    try:
        _ = GROCY_ACTION_CreatePlaceholderArgs(name=name, estimated_calories=estimated_calories,
                                               estimated_carbs=estimated_carbs, estimated_fats=estimated_fats,
                                               estimated_protein=estimated_protein)
        client = GrocyClient()
        
        # Create product
        product_fields = {"name": name}
        result = client.create_product(product_fields)
        product_id = result.get("created_object_id") or result.get("id")
        
        # Set userfields
        userfield_service = UserfieldService(client)
        userfield_service.set_product_userfield(product_id, "placeholder", "1")
        userfield_service.set_product_userfield(product_id, "Calories_Per_Serving", str(estimated_calories))
        userfield_service.set_product_userfield(product_id, "Carbs", str(estimated_carbs))
        userfield_service.set_product_userfield(product_id, "Fats", str(estimated_fats))
        userfield_service.set_product_userfield(product_id, "Protein", str(estimated_protein))
        
        return (True, json.dumps({"status": "ok", "product_id": product_id, "message": "Created placeholder product"}))
    except Exception as e:
        return (False, f"Error creating placeholder: {e}")


# ============================================================================
# SHOPPING LIST TOOLS
# ============================================================================

class GROCY_GET_ShoppingListArgs(BaseModel):
    """Arguments for getting shopping list."""
    shopping_list_id: int = Field(1, description="Shopping list ID (default 1)")


def GROCY_GET_ShoppingList(shopping_list_id: int = 1) -> Tuple[bool, str]:
    """Get shopping list items with product info and quantities.
    
    Example Prompt: what's on my shopping list?
    Example Response: [{"product_id": 5, "name": "Milk", "quantity": 2.0}, ...]
    Example Args: {"shopping_list_id": 1}
    """
    try:
        _ = GROCY_GET_ShoppingListArgs(shopping_list_id=shopping_list_id)
        client = GrocyClient()
        items = client.get_shopping_list(shopping_list_id=shopping_list_id)
        result = []
        for item in items:
            product_id = item.get("product_id")
            name = item.get("product", {}).get("name") or item.get("note")
            quantity = item.get("amount")
            result.append({"product_id": product_id, "name": name, "quantity": quantity})
        return (True, json.dumps(result, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting shopping list: {e}")


class GROCY_ACTION_AddToShoppingListArgs(BaseModel):
    """Arguments for adding to shopping list."""
    product_id: int = Field(..., description="Product ID to add")
    quantity: float = Field(1.0, description="Quantity to add")
    shopping_list_id: int = Field(1, description="Shopping list ID")


def GROCY_ACTION_AddToShoppingList(product_id: int, quantity: float = 1.0, shopping_list_id: int = 1) -> Tuple[bool, str]:
    """Add a product to the shopping list.
    
    Example Prompt: add 2 milk to shopping list
    Example Response: {"status": "ok", "message": "Added product 5 to shopping list"}
    Example Args: {"product_id": 5, "quantity": 2.0}
    """
    try:
        _ = GROCY_ACTION_AddToShoppingListArgs(product_id=product_id, quantity=quantity, shopping_list_id=shopping_list_id)
        client = GrocyClient()
        shopping_service = ShoppingService(client)
        shopping_service.add_product_to_shopping_list(product_id, quantity, shopping_list_id)
        return (True, json.dumps({"status": "ok", "message": f"Added product {product_id} to shopping list"}))
    except Exception as e:
        return (False, f"Error adding to shopping list: {e}")


class GROCY_ACTION_RemoveFromShoppingListArgs(BaseModel):
    """Arguments for removing from shopping list."""
    product_id: int = Field(..., description="Product ID to remove")
    quantity: float = Field(1.0, description="Quantity to remove")
    shopping_list_id: int = Field(1, description="Shopping list ID")


def GROCY_ACTION_RemoveFromShoppingList(product_id: int, quantity: float = 1.0, shopping_list_id: int = 1) -> Tuple[bool, str]:
    """Remove a product from the shopping list.
    
    Example Prompt: remove milk from shopping list
    Example Response: {"status": "ok", "message": "Removed product 5 from shopping list"}
    Example Args: {"product_id": 5, "quantity": 1.0}
    """
    try:
        _ = GROCY_ACTION_RemoveFromShoppingListArgs(product_id=product_id, quantity=quantity, shopping_list_id=shopping_list_id)
        client = GrocyClient()
        shopping_service = ShoppingService(client)
        shopping_service.remove_product_from_shopping_list(product_id, quantity, shopping_list_id)
        return (True, json.dumps({"status": "ok", "message": f"Removed product {product_id} from shopping list"}))
    except Exception as e:
        return (False, f"Error removing from shopping list: {e}")


class GROCY_ACTION_ClearShoppingListArgs(BaseModel):
    """Arguments for clearing shopping list."""
    shopping_list_id: int = Field(1, description="Shopping list ID")


def GROCY_ACTION_ClearShoppingList(shopping_list_id: int = 1) -> Tuple[bool, str]:
    """Clear all items from the shopping list.
    
    Example Prompt: clear my shopping list
    Example Response: {"status": "ok", "message": "Cleared shopping list"}
    Example Args: {"shopping_list_id": 1}
    """
    try:
        _ = GROCY_ACTION_ClearShoppingListArgs(shopping_list_id=shopping_list_id)
        client = GrocyClient()
        shopping_service = ShoppingService(client)
        shopping_service.clear_shopping_list(shopping_list_id)
        return (True, json.dumps({"status": "ok", "message": "Cleared shopping list"}))
    except Exception as e:
        return (False, f"Error clearing shopping list: {e}")


# ============================================================================
# MEAL PLAN TOOLS
# ============================================================================

class GROCY_GET_MealPlanArgs(BaseModel):
    """Arguments for getting meal plan."""
    start: Optional[str] = Field(None, description="Start date YYYY-MM-DD")
    end: Optional[str] = Field(None, description="End date YYYY-MM-DD")


def GROCY_GET_MealPlan(start: Optional[str] = None, end: Optional[str] = None) -> Tuple[bool, str]:
    """Get meal plan entries for a date range.
    
    Example Prompt: show me my meal plan for this week
    Example Response: [{"id": 1, "day": "2025-10-20", "type": "recipe", "recipe_id": 5, ...}, ...]
    Example Args: {"start": "2025-10-20", "end": "2025-10-27"}
    """
    try:
        _ = GROCY_GET_MealPlanArgs(start=start, end=end)
        client = GrocyClient()
        entries = client.get_meal_plan(start=start, end=end)
        return (True, json.dumps(entries, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting meal plan: {e}")


class GROCY_ACTION_AddMealToPlanArgs(BaseModel):
    """Arguments for adding meal to plan."""
    day: str = Field(..., description="Day in YYYY-MM-DD format")
    type: str = Field(..., description="Type: 'recipe' or 'product'")
    recipe_id: Optional[int] = Field(None, description="Recipe ID if type=recipe")
    product_id: Optional[int] = Field(None, description="Product ID if type=product")
    recipe_servings: Optional[int] = Field(None, description="Number of servings if type=recipe")
    product_amount: Optional[float] = Field(None, description="Product amount if type=product")


def GROCY_ACTION_AddMealToPlan(day: str, type: str, recipe_id: Optional[int] = None, 
                                product_id: Optional[int] = None, recipe_servings: Optional[int] = None,
                                product_amount: Optional[float] = None) -> Tuple[bool, str]:
    """Add a meal (recipe or product) to the meal plan.
    
    Example Prompt: add my protein shake recipe to tomorrow's meal plan
    Example Response: {"status": "ok", "message": "Added meal to plan"}
    Example Args: {"day": "2025-10-21", "type": "recipe", "recipe_id": 12, "recipe_servings": 1}
    """
    try:
        _ = GROCY_ACTION_AddMealToPlanArgs(day=day, type=type, recipe_id=recipe_id, 
                                           product_id=product_id, recipe_servings=recipe_servings,
                                           product_amount=product_amount)
        client = GrocyClient()
        fields = {"day": day, "type": type}
        if recipe_id:
            fields["recipe_id"] = recipe_id
        if product_id:
            fields["product_id"] = product_id
        if recipe_servings:
            fields["recipe_servings"] = recipe_servings
        if product_amount:
            fields["product_amount"] = product_amount
        
        client.create_meal_plan_entry(fields)
        return (True, json.dumps({"status": "ok", "message": "Added meal to plan"}))
    except Exception as e:
        return (False, f"Error adding meal to plan: {e}")


class GROCY_ACTION_MarkMealDoneArgs(BaseModel):
    """Arguments for marking meal as done."""
    entry_id: int = Field(..., description="Meal plan entry ID")


def GROCY_ACTION_MarkMealDone(entry_id: int) -> Tuple[bool, str]:
    """Mark a meal plan entry as completed/consumed.
    
    Example Prompt: mark meal plan entry 15 as done
    Example Response: {"status": "ok", "message": "Marked entry 15 as done"}
    Example Args: {"entry_id": 15}
    Notes: Marking as done includes it in consumed macro totals.
    """
    try:
        _ = GROCY_ACTION_MarkMealDoneArgs(entry_id=entry_id)
        client = GrocyClient()
        client.update_meal_plan_entry(entry_id, {"done": True})
        return (True, json.dumps({"status": "ok", "message": f"Marked entry {entry_id} as done"}))
    except Exception as e:
        return (False, f"Error marking meal done: {e}")


class GROCY_ACTION_DeleteMealPlanEntryArgs(BaseModel):
    """Arguments for deleting meal plan entry."""
    entry_id: int = Field(..., description="Meal plan entry ID")


def GROCY_ACTION_DeleteMealPlanEntry(entry_id: int) -> Tuple[bool, str]:
    """Delete a meal plan entry.
    
    Example Prompt: delete meal plan entry 20
    Example Response: {"status": "ok", "message": "Deleted entry 20"}
    Example Args: {"entry_id": 20}
    """
    try:
        _ = GROCY_ACTION_DeleteMealPlanEntryArgs(entry_id=entry_id)
        client = GrocyClient()
        client.delete_meal_plan_entry(entry_id)
        return (True, json.dumps({"status": "ok", "message": f"Deleted entry {entry_id}"}))
    except Exception as e:
        return (False, f"Error deleting meal plan entry: {e}")


# ============================================================================
# RECIPE TOOLS
# ============================================================================

class GROCY_GET_RecipesArgs(BaseModel):
    """Arguments for getting recipes."""
    pass


def GROCY_GET_Recipes() -> Tuple[bool, str]:
    """Get all recipes with id, name, and base servings.
    
    Example Prompt: list all my recipes
    Example Response: [{"id": 1, "name": "Protein Shake", "base_servings": 1}, ...]
    Example Args: {}
    """
    try:
        client = GrocyClient()
        recipes = client.get_recipes()
        result = [{"id": r.get("id"), "name": r.get("name"), "base_servings": r.get("base_servings")} 
                  for r in recipes]
        return (True, json.dumps(result, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting recipes: {e}")


class GROCY_GET_RecipeArgs(BaseModel):
    """Arguments for getting a single recipe."""
    recipe_id: int = Field(..., description="Recipe ID")


def GROCY_GET_Recipe(recipe_id: int) -> Tuple[bool, str]:
    """Get detailed info for a single recipe including ingredients.
    
    Example Prompt: show me recipe 5
    Example Response: {"id": 5, "name": "Protein Shake", "base_servings": 1, "ingredients": [...]}
    Example Args: {"recipe_id": 5}
    """
    try:
        _ = GROCY_GET_RecipeArgs(recipe_id=recipe_id)
        client = GrocyClient()
        recipe = client.get_recipe(recipe_id)
        # Get ingredients
        recipe_service = RecipeService(client)
        ingredients = recipe_service.list_recipe_ingredients(recipe_id)
        recipe["ingredients"] = ingredients
        return (True, json.dumps(recipe, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting recipe: {e}")


class GROCY_ACTION_CreateRecipeArgs(BaseModel):
    """Arguments for creating a recipe."""
    name: str = Field(..., description="Recipe name")
    base_servings: int = Field(1, description="Base number of servings")
    description: Optional[str] = Field(None, description="Recipe description")


def GROCY_ACTION_CreateRecipe(name: str, base_servings: int = 1, description: Optional[str] = None) -> Tuple[bool, str]:
    """Create a new recipe.
    
    Example Prompt: create a recipe called "High Protein Oatmeal"
    Example Response: {"status": "ok", "recipe_id": 25, "message": "Created recipe"}
    Example Args: {"name": "High Protein Oatmeal", "base_servings": 1}
    """
    try:
        _ = GROCY_ACTION_CreateRecipeArgs(name=name, base_servings=base_servings, description=description)
        client = GrocyClient()
        fields = {"name": name, "base_servings": base_servings}
        if description:
            fields["description"] = description
        result = client.create_recipe(fields)
        recipe_id = result.get("created_object_id") or result.get("id")
        return (True, json.dumps({"status": "ok", "recipe_id": recipe_id, "message": "Created recipe"}))
    except Exception as e:
        return (False, f"Error creating recipe: {e}")


class GROCY_ACTION_AddRecipeIngredientArgs(BaseModel):
    """Arguments for adding ingredient to recipe."""
    recipe_id: int = Field(..., description="Recipe ID")
    product_id: int = Field(..., description="Product ID (can be placeholder)")
    amount: float = Field(..., description="Amount of product")
    note: Optional[str] = Field(None, description="Optional note")


def GROCY_ACTION_AddRecipeIngredient(recipe_id: int, product_id: int, amount: float, note: Optional[str] = None) -> Tuple[bool, str]:
    """Add an ingredient to a recipe.
    
    Example Prompt: add 1 cup of oats to recipe 25
    Example Response: {"status": "ok", "message": "Added ingredient to recipe"}
    Example Args: {"recipe_id": 25, "product_id": 8, "amount": 1.0}
    """
    try:
        _ = GROCY_ACTION_AddRecipeIngredientArgs(recipe_id=recipe_id, product_id=product_id, amount=amount, note=note)
        client = GrocyClient()
        fields = {"recipe_id": recipe_id, "product_id": product_id, "amount": amount}
        if note:
            fields["note"] = note
        recipe_service = RecipeService(client)
        recipe_service.add_recipe_ingredient(fields)
        return (True, json.dumps({"status": "ok", "message": "Added ingredient to recipe"}))
    except Exception as e:
        return (False, f"Error adding recipe ingredient: {e}")


class GROCY_GET_CookableRecipesArgs(BaseModel):
    """Arguments for getting cookable recipes."""
    pass


def GROCY_GET_CookableRecipes() -> Tuple[bool, str]:
    """Get recipes that can be cooked with current inventory.
    
    Example Prompt: what recipes can I make right now?
    Example Response: [{"id": 5, "name": "Protein Shake", "possible_servings": 2.5}, ...]
    Example Args: {}
    """
    try:
        client = GrocyClient()
        recipes = client.get_cookable_recipes()
        return (True, json.dumps(recipes, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting cookable recipes: {e}")


# ============================================================================
# MACRO TRACKING TOOLS
# ============================================================================

class GROCY_GET_DayMacrosArgs(BaseModel):
    """Arguments for getting day macros."""
    day: Optional[str] = Field(None, description="Day in YYYY-MM-DD format (default: today)")


def GROCY_GET_DayMacros(day: Optional[str] = None) -> Tuple[bool, str]:
    """Get macro totals (consumed/planned/goal) for a specific day.
    
    Example Prompt: how many macros have I consumed today?
    Example Response: {"day": "2025-10-20", "consumed": {"calories": 2100, ...}, "planned": {...}, "goal": {...}}
    Example Args: {"day": "2025-10-20"}
    Notes: Consumed = meal plan entries marked done + temp items. Planned = all meal plan entries.
    """
    try:
        _ = GROCY_GET_DayMacrosArgs(day=day)
        result = get_day_macros(day)
        return (True, json.dumps(result, ensure_ascii=False))
    except Exception as e:
        return (False, f"Error getting day macros: {e}")


class GROCY_ACTION_CreateTempItemArgs(BaseModel):
    """Arguments for creating temp macro item."""
    name: str = Field(..., description="Item name")
    calories: float = Field(..., description="Calories")
    carbs: float = Field(..., description="Carbs in grams")
    fats: float = Field(..., description="Fats in grams")
    protein: float = Field(..., description="Protein in grams")
    day: Optional[str] = Field(None, description="Day in YYYY-MM-DD format")


def GROCY_ACTION_CreateTempItem(name: str, calories: float, carbs: float, 
                                 fats: float, protein: float, day: Optional[str] = None) -> Tuple[bool, str]:
    """Log a temporary consumed item (not in Grocy inventory).
    
    Example Prompt: I ate a snack with 200 calories, 20g carbs, 5g fat, 10g protein
    Example Response: {"status": "ok", "temp_item_id": 42, "message": "Created temp item"}
    Example Args: {"name": "Snack", "calories": 200, "carbs": 20, "fats": 5, "protein": 10}
    Notes: Use for quick logging of consumed items without product records.
    """
    try:
        _ = GROCY_ACTION_CreateTempItemArgs(name=name, calories=calories, carbs=carbs, 
                                            fats=fats, protein=protein, day=day)
        item_id = create_temp_item(name, calories, carbs, fats, protein, day)
        return (True, json.dumps({"status": "ok", "temp_item_id": item_id, "message": "Created temp item"}))
    except Exception as e:
        return (False, f"Error creating temp item: {e}")


class GROCY_ACTION_DeleteTempItemArgs(BaseModel):
    """Arguments for deleting temp item."""
    temp_item_id: int = Field(..., description="Temp item ID")


def GROCY_ACTION_DeleteTempItem(temp_item_id: int) -> Tuple[bool, str]:
    """Delete a temporary macro tracking item.
    
    Example Prompt: delete temp item 42
    Example Response: {"status": "ok", "message": "Deleted temp item"}
    Example Args: {"temp_item_id": 42}
    """
    try:
        _ = GROCY_ACTION_DeleteTempItemArgs(temp_item_id=temp_item_id)
        success = delete_temp_item(temp_item_id)
        if success:
            return (True, json.dumps({"status": "ok", "message": "Deleted temp item"}))
        else:
            return (False, json.dumps({"status": "error", "message": "Temp item not found"}))
    except Exception as e:
        return (False, f"Error deleting temp item: {e}")


class GROCY_ACTION_SetProductPriceArgs(BaseModel):
    """Arguments for setting product price."""
    product_id: int = Field(..., description="Product ID")
    price: float = Field(..., description="Price per unit")


def GROCY_ACTION_SetProductPrice(product_id: int, price: float) -> Tuple[bool, str]:
    """Set or update the price for a product.
    
    Example Prompt: set the price of milk to $4.99
    Example Response: {"status": "ok", "message": "Set price for product 5"}
    Example Args: {"product_id": 5, "price": 4.99}
    """
    try:
        _ = GROCY_ACTION_SetProductPriceArgs(product_id=product_id, price=price)
        client = GrocyClient()
        # Use add/consume pattern to set price
        client.add_product_quantity(product_id=product_id, quantity=1.0, price=price)
        client.consume_product_quantity(product_id=product_id, quantity=1.0)
        return (True, json.dumps({"status": "ok", "message": f"Set price for product {product_id}"}))
    except Exception as e:
        return (False, f"Error setting product price: {e}")


# ============================================================================
# TOOLS LIST
# ============================================================================

TOOLS = [
    # Inventory
    GROCY_GET_Inventory,
    GROCY_UPDATE_AddProductQuantity,
    GROCY_UPDATE_ConsumeProduct,
    
    # Products
    GROCY_GET_Products,
    GROCY_ACTION_CreateProduct,
    GROCY_ACTION_CreatePlaceholder,
    
    # Shopping List
    GROCY_GET_ShoppingList,
    GROCY_ACTION_AddToShoppingList,
    GROCY_ACTION_RemoveFromShoppingList,
    GROCY_ACTION_ClearShoppingList,
    
    # Meal Plan
    GROCY_GET_MealPlan,
    GROCY_ACTION_AddMealToPlan,
    GROCY_ACTION_MarkMealDone,
    GROCY_ACTION_DeleteMealPlanEntry,
    
    # Recipes
    GROCY_GET_Recipes,
    GROCY_GET_Recipe,
    GROCY_ACTION_CreateRecipe,
    GROCY_ACTION_AddRecipeIngredient,
    GROCY_GET_CookableRecipes,
    
    # Macro Tracking
    GROCY_GET_DayMacros,
    GROCY_ACTION_CreateTempItem,
    GROCY_ACTION_DeleteTempItem,
    GROCY_ACTION_SetProductPrice,
]




