"""Walmart operations - link and price management.

This module provides helpers for Walmart link/price management.
The actual scraping is done by separate scripts (scrape_walmart_*.py).
"""

from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from core.client import GrocyClient
from services.userfields import UserfieldService
from services.inventory import InventoryService
from services.products import ProductService


def get_missing_walmart_links(
    client: GrocyClient, 
    max_results: int = 5
) -> List[Dict[str, Any]]:
    """Return products missing Walmart links and/or prices.
    
    Args:
        client: GrocyClient instance
        max_results: Maximum number of results to return
        
    Returns:
        List of dicts with product_id, product_name, walmart_search_url, 
        missing_link, missing_price flags
    """
    product_service = ProductService(client)
    userfield_service = UserfieldService(client)
    inventory_service = InventoryService(client)
    
    # Detect the Walmart link userfield key
    walmart_key = userfield_service.detect_walmart_userfield_key()
    
    # Get all products
    try:
        products = product_service.list_all_products()
    except Exception as e:
        raise RuntimeError(f"Failed to list products: {e}")
    
    results: List[Dict[str, Any]] = []
    
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
                userfields = userfield_service.get_product_userfields(product_id)
                link_value = userfields.get(walmart_key)
                if isinstance(link_value, str) and link_value.strip():
                    missing_link = False
            except Exception:
                pass  # Treat as missing if we can't check
        
        # Check if price is missing (no stock entries with price > 0)
        missing_price = True
        try:
            stock_entries = inventory_service.get_product_stock_entries(product_id)
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
            results.append({
                "product_id": product_id,
                "product_name": product_name,
                "walmart_search_url": walmart_search_url,
                "missing_link": missing_link,
                "missing_price": missing_price
            })
            
            # Stop if we've reached max_results
            if len(results) >= max_results:
                break
    
    return results


def upload_walmart_links(
    client: GrocyClient,
    items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Bulk upload Walmart links and prices.
    
    Args:
        client: GrocyClient instance
        items: List of dicts with product_id, walmart_link, price (optional)
        
    Returns:
        Dict with status, message, updated list, skipped list
    """
    userfield_service = UserfieldService(client)
    inventory_service = InventoryService(client)
    
    walmart_key = userfield_service.detect_walmart_userfield_key()
    
    if not isinstance(walmart_key, str) or not walmart_key:
        return {
            "status": "error",
            "message": "Could not detect Walmart userfield key for products",
            "updated": [],
            "skipped": [int(item.get("product_id", 0)) for item in items if item.get("product_id")]
        }
    
    updated_ids: List[int] = []
    skipped_ids: List[int] = []
    
    for item in items:
        try:
            product_id = int(item.get("product_id", 0))
            walmart_link = str(item.get("walmart_link", "")).strip()
            price = item.get("price")
            
            if not product_id or not walmart_link:
                skipped_ids.append(product_id)
                continue
            
            # Update walmart link via userfields
            link_updated = False
            try:
                uf = userfield_service.get_product_userfields(product_id)
                existing_link = uf.get(walmart_key)
                if not (isinstance(existing_link, str) and existing_link.strip() == walmart_link):
                    userfield_service.set_product_userfields(product_id, {walmart_key: walmart_link})
                    link_updated = True
            except Exception:
                pass
            
            # Update price via stock booking
            price_updated = False
            if price is not None:
                try:
                    inventory_service.add_product_quantity_with_price(product_id, 1.0, float(price))
                    inventory_service.consume_product_quantity(product_id, 1.0)
                    price_updated = True
                except Exception:
                    pass
            
            if link_updated or price_updated:
                updated_ids.append(product_id)
            else:
                skipped_ids.append(product_id)
                
        except Exception:
            skipped_ids.append(product_id)
    
    return {
        "status": "ok",
        "message": f"Updated {len(updated_ids)} products; skipped {len(skipped_ids)}",
        "updated": updated_ids,
        "skipped": skipped_ids
    }

