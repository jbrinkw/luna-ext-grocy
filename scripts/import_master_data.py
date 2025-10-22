"""Import Grocy master data configuration from JSON files.

This script imports the structure/configuration previously exported by export_master_data.py.

WARNING: This will create new objects in Grocy. It does NOT delete existing objects.
Use with caution and make sure you have a backup.

The import order respects foreign key dependencies:
1. Locations
2. Stores
3. Quantity units
4. Product groups
5. Task categories
6. Userfields (definitions)
7. Userentities
8. Shopping lists (definitions)
9. Meal plan sections
10. Chores
11. Batteries (types)
12. Equipment (types)

Note: This does NOT import products, recipes, or actual inventory items.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add lib to path
_lib_path = Path(__file__).parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from core.client import GrocyClient


# Import order (respects foreign key dependencies)
IMPORT_ORDER = [
    "locations",
    "stores",
    "quantity_units",
    "product_groups",
    "task_categories",
    "userfields",
    "userentities",
    "shopping_lists",
    "meal_plan_sections",
    "chores",
    "batteries",
    "equipment",
]


def import_object_type(
    client: GrocyClient,
    object_type: str,
    objects: List[Dict[str, Any]],
    id_mapping: Optional[Dict[str, Dict[int, int]]] = None,
) -> Dict[int, int]:
    """Import objects of a given type.
    
    Args:
        client: GrocyClient instance
        object_type: Type of object to import
        objects: List of objects to import
        id_mapping: Mapping of old IDs to new IDs for other object types
        
    Returns:
        Dict mapping old IDs to new IDs for this object type
    """
    if not objects:
        print(f"Skipping {object_type} (no data)")
        return {}
    
    print(f"Importing {object_type}...", end=" ")
    
    old_to_new_id = {}
    success_count = 0
    error_count = 0
    
    id_mapping = id_mapping or {}
    
    for obj in objects:
        try:
            old_id = obj.get("id")
            
            # Remove system fields that shouldn't be set on creation
            import_obj = dict(obj)
            for field in ["id", "row_created_timestamp", "userfield"]:
                import_obj.pop(field, None)
            
            # Remap foreign key IDs if needed
            for key in list(import_obj.keys()):
                if key.endswith("_id") and import_obj[key] is not None:
                    # Handle specific foreign key mappings
                    if key == "location_id" and "locations" in id_mapping:
                        old_related_id = import_obj[key]
                        if old_related_id in id_mapping["locations"]:
                            import_obj[key] = id_mapping["locations"][old_related_id]
                    elif key == "store_id" and "stores" in id_mapping:
                        old_related_id = import_obj[key]
                        if old_related_id in id_mapping["stores"]:
                            import_obj[key] = id_mapping["stores"][old_related_id]
                    elif key == "product_group_id" and "product_groups" in id_mapping:
                        old_related_id = import_obj[key]
                        if old_related_id in id_mapping["product_groups"]:
                            import_obj[key] = id_mapping["product_groups"][old_related_id]
                    elif key == "shopping_list_id" and "shopping_lists" in id_mapping:
                        old_related_id = import_obj[key]
                        if old_related_id in id_mapping["shopping_lists"]:
                            import_obj[key] = id_mapping["shopping_lists"][old_related_id]
                    # Quantity unit mappings (various field names)
                    elif key in ["qu_id_purchase", "qu_id_stock", "qu_id", "qu_id_consume"]:
                        if "quantity_units" in id_mapping:
                            old_related_id = import_obj[key]
                            if old_related_id in id_mapping["quantity_units"]:
                                import_obj[key] = id_mapping["quantity_units"][old_related_id]
            
            # Create the object
            response = client._post(f"/objects/{object_type}", import_obj)
            
            # Extract new ID
            new_id = client._extract_created_id_from_response(response)
            
            if new_id and old_id:
                old_to_new_id[old_id] = new_id
            
            success_count += 1
            
        except Exception as e:
            error_count += 1
            # Uncomment to see detailed errors:
            # print(f"\n  Error importing {object_type} {old_id}: {e}")
    
    if error_count > 0:
        print(f"✓ ({success_count} created, {error_count} errors)")
    else:
        print(f"✓ ({success_count} created)")
    
    return old_to_new_id


def import_userfield_values(
    client: GrocyClient,
    object_type: str,
    userfield_data: Dict[int, Dict[str, Any]],
    id_mapping: Dict[int, int],
) -> None:
    """Import userfield values for objects.
    
    Args:
        client: GrocyClient instance
        object_type: Type of object (e.g., 'products', 'recipes')
        userfield_data: Dict mapping old object IDs to userfield values
        id_mapping: Dict mapping old IDs to new IDs
    """
    if not userfield_data:
        return
    
    print(f"Importing userfields for {object_type}...", end=" ")
    
    success_count = 0
    error_count = 0
    
    for old_id, userfields in userfield_data.items():
        try:
            # Get new ID
            new_id = id_mapping.get(old_id)
            if not new_id:
                error_count += 1
                continue
            
            # Set userfields
            for field_name, field_value in userfields.items():
                try:
                    client._put(f"/userfields/{object_type}/{new_id}/{field_name}", {"value": field_value})
                except Exception:
                    pass  # Some userfields may fail if definitions don't exist
            
            success_count += 1
            
        except Exception:
            error_count += 1
    
    if error_count > 0:
        print(f"✓ ({success_count} updated, {error_count} errors)")
    else:
        print(f"✓ ({success_count} updated)")


def main():
    """Import master data from backup directory."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python import_master_data.py <backup_directory>")
        print("\nExample:")
        print("  python import_master_data.py backups/master_data_20250101_120000")
        sys.exit(1)
    
    backup_dir = Path(sys.argv[1])
    
    if not backup_dir.exists():
        print(f"Error: Backup directory not found: {backup_dir}")
        sys.exit(1)
    
    # Load files
    data_file = backup_dir / "master_data.json"
    
    if not data_file.exists():
        print(f"Error: Master data file not found: {data_file}")
        sys.exit(1)
    
    print(f"Importing Grocy master data from: {backup_dir}\n")
    
    # Load data
    with open(data_file, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    
    # Initialize client
    client = GrocyClient()
    
    print(f"Target URL: {client.base_url}\n")
    
    # Confirm import
    print("WARNING: This will create new objects in Grocy.")
    print("Make sure you have a backup before proceeding.")
    response = input("\nContinue? (yes/no): ")
    
    if response.lower() not in ["yes", "y"]:
        print("Import cancelled.")
        sys.exit(0)
    
    print("\nStarting import...\n")
    
    # Track ID mappings
    id_mappings = {}
    
    # Import in order
    for object_type in IMPORT_ORDER:
        if object_type in all_data:
            mapping = import_object_type(client, object_type, all_data[object_type], id_mappings)
            if mapping:
                id_mappings[object_type] = mapping
    
    print("\n✓ Import complete!")
    
    # Summary
    total_created = sum(len(mapping) for mapping in id_mappings.values())
    print(f"\nTotal objects created: {total_created}")
    print(f"\nNote: Only structure/configuration was imported.")
    print(f"      Products and recipes were not included.")


if __name__ == "__main__":
    main()

