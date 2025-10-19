"""Service modules for Grocy domain operations."""

# Import all service classes/functions for easy access
from .products import ProductService
from .inventory import InventoryService
from .shopping import ShoppingService
from .recipes import RecipeService
from .meal_plan import MealPlanService
from .userfields import UserfieldService

__all__ = [
    "ProductService",
    "InventoryService",
    "ShoppingService",
    "RecipeService",
    "MealPlanService",
    "UserfieldService",
]

