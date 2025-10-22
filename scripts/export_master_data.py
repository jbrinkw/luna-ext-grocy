"""Export Grocy master data configuration to JSON files.

This script exports the STRUCTURE/CONFIGURATION of Grocy, NOT actual items.

Exports:
- Locations
- Stores
- Quantity units
- Product groups
- Userfield definitions
- Userentities
- Shopping list definitions
- Meal plan sections
- Task categories
- Battery types
- Equipment types
- Chore definitions

Does NOT export:
- Products
- Recipes
- Recipe ingredients
- Product barcodes
- Actual inventory items

The data is saved to a timestamped directory in the backups folder.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Add lib to path
_lib_path = Path(__file__).parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from core.client import GrocyClient


# Master data object types to export (configuration/structure only, no actual items)
MASTER_DATA_TYPES = [
    "locations",
    "stores",
    "quantity_units",
    "product_groups",
    "userfields",  # Userfield definitions (not values)
    "userentities",
    "shopping_lists",  # Shopping list definitions (not items)
    "meal_plan_sections",
    "task_categories",
    "batteries",  # Battery types
    "equipment",  # Equipment types
    "chores",  # Chore definitions
]


def export_object_type(client: GrocyClient, object_type: str) -> List[Dict[str, Any]]:
    """Export all objects of a given type.
    
    Args:
        client: GrocyClient instance
        object_type: Type of object to export (e.g., 'products', 'locations')
        
    Returns:
        List of objects
    """
    try:
        print(f"Exporting {object_type}...", end=" ")
        data = client._get(f"/objects/{object_type}")
        
        if isinstance(data, list):
            print(f"✓ ({len(data)} items)")
            return data
        elif isinstance(data, dict):
            # Some endpoints return {"data": [...]}
            if "data" in data and isinstance(data["data"], list):
                print(f"✓ ({len(data['data'])} items)")
                return data["data"]
            else:
                # Single object response
                print(f"✓ (1 item)")
                return [data]
        else:
            print("✓ (0 items)")
            return []
    except Exception as e:
        print(f"✗ Error: {e}")
        return []


def export_userfield_values(client: GrocyClient, object_type: str, object_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Export userfield values for objects.
    
    Args:
        client: GrocyClient instance
        object_type: Type of object (e.g., 'products', 'recipes')
        object_ids: List of object IDs to get userfields for
        
    Returns:
        Dict mapping object_id to userfield values
    """
    try:
        print(f"Exporting userfields for {object_type}...", end=" ")
        userfield_values = {}
        
        for obj_id in object_ids:
            try:
                userfields = client._get(f"/userfields/{object_type}/{obj_id}")
                if userfields:
                    userfield_values[obj_id] = userfields
            except Exception:
                # Object may not have userfields
                pass
        
        print(f"✓ ({len(userfield_values)} items with userfields)")
        return userfield_values
    except Exception as e:
        print(f"✗ Error: {e}")
        return {}


def main():
    """Export all master data."""
    # Create backup directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(__file__).parent.parent / "backups" / f"master_data_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Exporting Grocy master data to: {backup_dir}\n")
    
    # Initialize client
    client = GrocyClient()
    
    # Export all object types
    all_data = {}
    
    for object_type in MASTER_DATA_TYPES:
        data = export_object_type(client, object_type)
        all_data[object_type] = data
    
    # Save all object data
    data_file = backup_dir / "master_data.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Export complete!")
    print(f"  - Master data: {data_file}")
    print(f"\nNote: This exports structure/configuration only (locations, units, etc.)")
    print(f"      Products, recipes, and actual items are NOT included.")
    
    # Calculate total objects
    total_objects = sum(len(data) for data in all_data.values())
    print(f"\nTotal objects exported: {total_objects}")


if __name__ == "__main__":
    main()

