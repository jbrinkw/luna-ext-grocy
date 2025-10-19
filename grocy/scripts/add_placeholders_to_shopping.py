#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Add placeholder items to shopping list.

Ensures that all placeholder products have at least one container in the shopping list.
This is useful for maintaining a shopping list of items you need to buy.
"""
import sys
import io

# Set stdout to UTF-8 encoding (fixes Windows console issues)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

import sys
from pathlib import Path
# Add lib directory to path
_lib_path = Path(__file__).parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from core.client import GrocyClient

def get_all_placeholder_products(client):
    """Get all products that have placeholder=True userfield.

    Returns:
        List of dicts with {id, name}
    """
    placeholders = []

    try:
        # Get all products
        all_products = client._get("/objects/products")
        if isinstance(all_products, dict) and "data" in all_products:
            all_products = all_products["data"]

        if not isinstance(all_products, list):
            print(f"Warning: Expected list of products, got {type(all_products)}")
            return []

        # Filter to placeholders only
        for product in all_products:
            try:
                pid = int(product.get("id"))
                name = product.get("name")

                # Check if it has placeholder=True userfield
                userfields = client.get_product_userfields(pid)
                placeholder_value = userfields.get("placeholder") or userfields.get("Placeholder")

                # Handle string "0", "1", True, False, None
                is_placeholder = False
                if placeholder_value is True or placeholder_value == 1 or placeholder_value == "1":
                    is_placeholder = True

                if is_placeholder and name:
                    placeholders.append({"id": pid, "name": name})
            except Exception as e:
                print(f"Warning: Error checking product {product.get('id', '?')}: {e}")
                continue

        return placeholders

    except Exception as e:
        print(f"Error fetching placeholder products: {e}")
        return []


def get_shopping_list_product_ids(client, shopping_list_id=1):
    """Get set of product IDs already in shopping list.

    Returns:
        Set of product IDs (int)
    """
    try:
        items = client.get_shopping_list_items(shopping_list_id)
        return {int(item["product_id"]) for item in items if item.get("product_id")}
    except Exception as e:
        print(f"Error fetching shopping list: {e}")
        return set()


def add_placeholder_to_shopping_list(client, product_id, product_name, shopping_list_id=1):
    """Add one container of a placeholder product to shopping list.

    Args:
        client: GrocyClient instance
        product_id: Product ID to add
        product_name: Product name (for display)
        shopping_list_id: Shopping list ID (default: 1)
    """
    try:
        client.shopping_list_add_product(
            product_id=product_id,
            amount=1.0,
            shopping_list_id=shopping_list_id
        )
        print(f"✅ Added: {product_name} (ID: {product_id})")
    except Exception as e:
        print(f"❌ Error adding {product_name} (ID: {product_id}): {e}")


def main():
    """Main entry point."""
    print("Adding placeholder items to shopping list...")
    print()

    try:
        client = GrocyClient()
        shopping_list_id = 1  # Default shopping list

        # Get all placeholder products
        print("Finding placeholder products...")
        placeholders = get_all_placeholder_products(client)

        if not placeholders:
            print("No placeholder products found.")
            return

        print(f"Found {len(placeholders)} placeholder product(s)")
        print()

        # Get current shopping list items
        print("Checking shopping list...")
        shopping_list_ids = get_shopping_list_product_ids(client, shopping_list_id)
        print(f"Shopping list currently has {len(shopping_list_ids)} product(s)")
        print()

        # Add missing placeholders
        added_count = 0
        skipped_count = 0

        for placeholder in placeholders:
            pid = placeholder["id"]
            name = placeholder["name"]

            if pid in shopping_list_ids:
                print(f"⏭️  Skipped: {name} (ID: {pid}) - already in shopping list")
                skipped_count += 1
            else:
                add_placeholder_to_shopping_list(client, pid, name, shopping_list_id)
                added_count += 1

        print()
        print("=" * 60)
        print(f"Summary:")
        print(f"  Total placeholders: {len(placeholders)}")
        print(f"  Added to shopping list: {added_count}")
        print(f"  Already in shopping list: {skipped_count}")
        print("=" * 60)

    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
