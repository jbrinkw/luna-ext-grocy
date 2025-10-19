"""Inventory management operations."""

from typing import Any, Dict, List, Optional

from core.client import GrocyClient


class InventoryService:
    """Handles inventory operations."""
    
    def __init__(self, client: GrocyClient):
        self.client = client
    
    def get_inventory(self) -> List[Dict[str, Any]]:
        """Return current stock per product.

        Tries a set of known endpoints, in order, to maximize compatibility
        across Grocy versions:
        - /stock/overview
        - /stock
        - /objects/products
        - /stock/products
        """
        candidate_paths = [
            "/stock/overview",
            "/stock/overview/",
            "/stock",
            "/stock/",
            "/objects/products",
            "/objects/products/",
            "/stock/products",
            "/stock/products/",
        ]

        last_error: Optional[Exception] = None
        for path in candidate_paths:
            try:
                data = self.client._get(path)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    # Some Grocy endpoints wrap list in { data: [...] }
                    if "data" in data and isinstance(data["data"], list):
                        return data["data"]
                    # Some endpoints return a dict keyed by product id
                    if any(isinstance(v, (dict, list)) for v in data.values()):
                        # Convert map to list of records
                        return [
                            {"key": key, "value": value} for key, value in data.items()
                        ]
                # If response is text or unexpected type, continue to next candidate
            except Exception as error:  # noqa: BLE001 - simple sequential tries
                import requests
                status = getattr(getattr(error, 'response', None), "status_code", None)
                if status in {404, 405}:
                    last_error = error
                    continue
                raise
        if last_error:
            raise last_error
        raise ValueError("Failed to retrieve inventory: no suitable endpoint found")

    def add_product_quantity(self, product_id: int, quantity: float) -> Any:
        """Increase the quantity of a product by posting to Grocy.

        Uses POST /stock/products/{productId}/add with minimal payload (amount only).
        """
        if quantity <= 0:
            raise ValueError("quantity must be > 0 to add stock")
        payload = {"amount": float(quantity)}
        return self.client._post(f"/stock/products/{product_id}/add", json_body=payload)

    def add_product_quantity_with_price(self, product_id: int, quantity: float, price: float) -> Any:
        """Increase quantity at a specific price (sets last/avg price context in Grocy).

        Uses POST /stock/products/{productId}/add with payload { amount, price }.
        """
        if quantity <= 0:
            raise ValueError("quantity must be > 0 to add stock")
        payload = {"amount": float(quantity), "price": float(price)}
        return self.client._post(f"/stock/products/{product_id}/add", json_body=payload)

    def consume_product_quantity(self, product_id: int, quantity: float) -> Any:
        """Decrease the quantity of a product by posting to Grocy.

        Uses POST /stock/products/{productId}/consume with minimal payload (amount only).
        """
        if quantity <= 0:
            raise ValueError("quantity must be > 0 to consume stock")
        payload = {"amount": float(quantity)}
        return self.client._post(f"/stock/products/{product_id}/consume", json_body=payload)

    def get_product_stock_entries(self, product_id: int) -> List[Dict[str, Any]]:
        """Return stock entries for a product (used to check for price history)."""
        try:
            data = self.client._get(f"/stock/products/{int(product_id)}/entries")
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return data["data"]
            return []
        except Exception as e:
            import requests
            if isinstance(e, requests.HTTPError):
                status = getattr(e.response, "status_code", None)
                if status in {404, 405}:
                    return []
            raise

