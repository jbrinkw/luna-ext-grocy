"""Shopping list operations."""

from typing import Any, Dict, List, Optional

from core.client import GrocyClient


class ShoppingService:
    """Handles shopping list operations."""
    
    def __init__(self, client: GrocyClient):
        self.client = client
    
    def get_shopping_list_items(self, shopping_list_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return shopping list items.

        Tries a set of known endpoints to be robust across Grocy versions:
        - /stock/shoppinglist
        - /objects/shopping_list
        If shopping_list_id is provided, results are filtered client-side.
        """
        candidate_paths = [
            "/stock/shoppinglist",
            "/stock/shoppinglist/",
            "/objects/shopping_list",
            "/objects/shopping_list/",
        ]

        last_error: Optional[Exception] = None
        for path in candidate_paths:
            try:
                data = self.client._get(path)
                items: List[Dict[str, Any]]
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    items = data["data"]
                else:
                    continue

                if shopping_list_id is not None:
                    sid = int(shopping_list_id)
                    filtered: List[Dict[str, Any]] = []
                    for item in items:
                        item_sid = item.get("shopping_list_id")
                        if isinstance(item_sid, (int, float)):
                            if int(item_sid) == sid:
                                filtered.append(item)
                        else:
                            # Some endpoints may nest the list under a key
                            nested = item.get("shopping_list")
                            if isinstance(nested, dict) and int(nested.get("id", -1)) == sid:
                                filtered.append(item)
                    return filtered
                return items
            except Exception as error:  # noqa: BLE001
                import requests
                if isinstance(error, requests.HTTPError):
                    status = getattr(error.response, "status_code", None)
                    if status in {404, 405}:
                        last_error = error
                        continue
                raise
        if last_error:
            raise last_error
        raise ValueError("Failed to retrieve shopping list: no suitable endpoint found")

    def shopping_list_add_product(self, product_id: int, amount: float, shopping_list_id: Optional[int] = 1) -> Any:
        if amount <= 0:
            raise ValueError("amount must be > 0 to add to shopping list")
        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "amount": float(amount),
        }
        if shopping_list_id is not None:
            payload["shopping_list_id"] = int(shopping_list_id)
        return self.client._post("/stock/shoppinglist/add-product", json_body=payload)

    def shopping_list_remove_product(self, product_id: int, amount: float, shopping_list_id: Optional[int] = 1) -> Any:
        if amount <= 0:
            raise ValueError("amount must be > 0 to remove from shopping list")
        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "amount": float(amount),
        }
        if shopping_list_id is not None:
            payload["shopping_list_id"] = int(shopping_list_id)
        return self.client._post("/stock/shoppinglist/remove-product", json_body=payload)

    def shopping_list_clear(self, shopping_list_id: Optional[int] = 1) -> Any:
        payload: Dict[str, Any] = {}
        if shopping_list_id is not None:
            payload["shopping_list_id"] = int(shopping_list_id)
        return self.client._post("/stock/shoppinglist/clear", json_body=payload)

