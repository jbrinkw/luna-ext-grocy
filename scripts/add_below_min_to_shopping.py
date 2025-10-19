#!/usr/bin/env python3
"""
Add products below minimum stock to shopping list.

This script checks all products and adds any items below their minimum stock
amount to the shopping list. The script accounts for items already in the 
shopping list and only adds enough to bring the total (current stock + 
shopping list quantity) up to the minimum value.

Env:
- GROCY_API_KEY (required)
- GROCY_BASE_URL (required; e.g., http://host/api)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv


def _base_url() -> str:
    url = (os.getenv("GROCY_BASE_URL") or "").rstrip("/")
    if not url:
        print("Error: GROCY_BASE_URL must be set", file=sys.stderr)
        sys.exit(2)
    return url


def _headers_json() -> Dict[str, str]:
    api_key = os.getenv("GROCY_API_KEY")
    if not api_key:
        print("Error: GROCY_API_KEY must be set", file=sys.stderr)
        sys.exit(2)
    return {
        "GROCY-API-KEY": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _headers_get() -> Dict[str, str]:
    api_key = os.getenv("GROCY_API_KEY")
    if not api_key:
        print("Error: GROCY_API_KEY must be set", file=sys.stderr)
        sys.exit(2)
    return {"GROCY-API-KEY": api_key, "Accept": "application/json"}


def _get(path: str) -> Any:
    url = f"{_base_url()}{path}"
    resp = requests.get(url, headers=_headers_get(), timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return resp.text


def _post(path: str, body: Dict[str, Any]) -> Any:
    url = f"{_base_url()}{path}"
    resp = requests.post(url, headers=_headers_json(), json=body, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return resp.text


def _get_all_products() -> List[Dict[str, Any]]:
    """Get all products from Grocy."""
    data = _get("/objects/products")
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data, list):
        return data
    return []


def _get_stock_info(product_id: int) -> Dict[str, Any]:
    """Get stock information for a product."""
    try:
        data = _get(f"/stock/products/{product_id}")
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _get_shopping_list_items(shopping_list_id: int = 1) -> List[Dict[str, Any]]:
    """Get all items currently in the shopping list."""
    try:
        data = _get("/objects/shopping_list")
        if isinstance(data, list):
            # Filter by shopping list ID if needed
            return [item for item in data if int(item.get("shopping_list_id", 1)) == shopping_list_id]
        return []
    except Exception:
        return []


def _add_to_shopping_list(product_id: int, amount: float, shopping_list_id: int = 1) -> None:
    """Add a product to the shopping list."""
    payload = {
        "product_id": int(product_id),
        "amount": float(amount),
        "shopping_list_id": int(shopping_list_id),
    }
    _post("/stock/shoppinglist/add-product", payload)


def main() -> int:
    try:
        load_dotenv(override=False)
    except Exception:
        pass

    print("[info] Checking products below minimum stock...")
    
    try:
        products = _get_all_products()
    except Exception as exc:
        print(f"Error: failed to load products: {exc}", file=sys.stderr)
        return 2

    if not products:
        print("[info] No products found.")
        return 0

    # Get current shopping list items
    shopping_list_items = _get_shopping_list_items()
    shopping_list_by_product: Dict[int, float] = {}
    for item in shopping_list_items:
        pid = int(item.get("product_id", 0))
        amount = float(item.get("amount", 0))
        shopping_list_by_product[pid] = shopping_list_by_product.get(pid, 0) + amount

    added_count = 0
    skipped_count = 0
    total_below_min = 0

    for product in products:
        try:
            product_id = int(product.get("id"))
            product_name = str(product.get("name") or "").strip()
            min_stock = float(product.get("min_stock_amount") or 0)

            # Skip products with no minimum stock set
            if min_stock <= 0:
                continue

            # Get current stock level
            stock_info = _get_stock_info(product_id)
            current_stock = float(stock_info.get("stock_amount") or stock_info.get("amount") or 0)

            # Get amount already in shopping list
            in_shopping_list = shopping_list_by_product.get(product_id, 0)

            # Calculate total available (current stock + what's in shopping list)
            total_available = current_stock + in_shopping_list

            # Check if below minimum
            if total_available < min_stock:
                total_below_min += 1
                amount_needed = min_stock - total_available
                
                print(
                    f"[below-min] product_id={product_id} name='{product_name}' "
                    f"current={current_stock} in_cart={in_shopping_list} "
                    f"min={min_stock} needed={amount_needed}"
                )

                try:
                    _add_to_shopping_list(product_id, amount_needed)
                    added_count += 1
                    print(f"[ok] Added {amount_needed} x '{product_name}' to shopping list")
                except Exception as exc:
                    print(f"[warn] Failed to add product {product_id} to shopping list: {exc}")
                    skipped_count += 1
            elif in_shopping_list > 0:
                print(
                    f"[ok] product_id={product_id} name='{product_name}' "
                    f"current={current_stock} in_cart={in_shopping_list} "
                    f"min={min_stock} (already has enough in cart)"
                )

        except Exception as exc:
            print(f"[warn] Error processing product {product.get('id')}: {exc}")
            skipped_count += 1
            continue

    print(
        f"[done] total_below_min={total_below_min}, added={added_count}, skipped={skipped_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

