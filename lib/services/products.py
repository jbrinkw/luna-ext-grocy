"""Product management operations."""

import os
from typing import Any, Dict, List, Optional

from core.client import GrocyClient


class ProductService:
    """Handles product operations."""
    
    def __init__(self, client: GrocyClient):
        self.client = client
    
    def create_product(self, product_fields: Dict[str, Any]) -> Any:
        """Create a new product via POST /objects/products.

        The caller must provide at least the minimal Grocy-required fields, typically:
        - name (str)
        - location_id (int)
        - qu_id_purchase (int)
        - qu_id_stock (int)

        Any additional fields supported by Grocy can be included in product_fields.
        Returns the raw API response (often contains the created id).
        """
        if not isinstance(product_fields, dict) or not product_fields.get("name"):
            raise ValueError("product_fields must be a dict and include 'name'")
        return self.client._post("/objects/products", json_body=product_fields)
    
    def validate_product_required_ids(self, fields: Dict[str, Any]) -> None:
        """Validate that required foreign keys exist and values are sensible.

        Required per Grocy for products:
        - location_id (must reference /objects/locations)
        - qu_id_purchase (must reference /objects/quantity_units)
        - qu_id_stock (must reference /objects/quantity_units)

        Optional on some Grocy versions (moved to a separate conversion table):
        - qu_factor_purchase_to_stock (float > 0)

        Raises ValueError with an actionable message if invalid.
        """
        def _as_int(value: Any, key: str) -> int:
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str) and value.isdigit():
                return int(value)
            raise ValueError(
                f"Missing or invalid required field '{key}'. Provide it explicitly or set the GROCY_DEFAULT_* env vars."
            )

        location_id = _as_int(fields.get("location_id"), "location_id")
        if not self.client._object_exists("locations", location_id):
            raise ValueError(
                f"Invalid location_id={location_id}: No such location. Use GET /objects/locations to list valid ids, "
                f"then set GROCY_DEFAULT_LOCATION_ID or pass a valid 'location_id'."
            )

        qu_id_purchase = _as_int(fields.get("qu_id_purchase"), "qu_id_purchase")
        if not self.client._object_exists("quantity_units", qu_id_purchase):
            raise ValueError(
                f"Invalid qu_id_purchase={qu_id_purchase}: No such quantity unit. Use GET /objects/quantity_units to list valid ids, "
                f"then set GROCY_DEFAULT_QU_ID_PURCHASE or pass a valid 'qu_id_purchase'."
            )

        qu_id_stock = _as_int(fields.get("qu_id_stock"), "qu_id_stock")
        if not self.client._object_exists("quantity_units", qu_id_stock):
            raise ValueError(
                f"Invalid qu_id_stock={qu_id_stock}: No such quantity unit. Use GET /objects/quantity_units to list valid ids, "
                f"then set GROCY_DEFAULT_QU_ID_STOCK or pass a valid 'qu_id_stock'."
            )

        if "qu_factor_purchase_to_stock" in fields:
            raw_factor = fields.get("qu_factor_purchase_to_stock")
            try:
                factor = float(raw_factor)
            except Exception as exc:  # noqa: BLE001
                raise ValueError("'qu_factor_purchase_to_stock' must be a number") from exc
            if factor <= 0:
                raise ValueError("'qu_factor_purchase_to_stock' must be > 0")
    
    def find_product_id_by_name(self, name: str) -> Optional[int]:
        """Return the product id for the given name (case-insensitive), if present."""
        if not name:
            return None
        name_map = self.get_product_name_map()
        lowered = name.strip().lower()
        for pid, pname in name_map.items():
            if isinstance(pname, str) and pname.strip().lower() == lowered:
                return int(pid)
        return None
    
    def ensure_product_exists(self, name: str, create_fields: Optional[Dict[str, Any]] = None) -> int:
        """Ensure a product by name exists; create it if missing and return id.

        create_fields may include any Grocy product fields; minimal fields will be
        filled from environment defaults if not provided:
        - GROCY_DEFAULT_LOCATION_ID (default 1)
        - GROCY_DEFAULT_QU_ID_PURCHASE (default 1)
        - GROCY_DEFAULT_QU_ID_STOCK (default 1)
        - GROCY_DEFAULT_QU_FACTOR (default 1)
        """
        existing = self.find_product_id_by_name(name)
        if isinstance(existing, int):
            return existing

        defaults: Dict[str, Any] = {
            "name": name,
            "location_id": int(os.getenv("GROCY_DEFAULT_LOCATION_ID", "2")),
            "qu_id_purchase": int(os.getenv("GROCY_DEFAULT_QU_ID_PURCHASE", "2")),
            "qu_id_stock": int(os.getenv("GROCY_DEFAULT_QU_ID_STOCK", "2")),
        }
        payload = {**defaults, **(create_fields or {})}
        # Validate FK references and factor to provide clear errors before POST
        self.validate_product_required_ids(payload)
        resp = self.create_product(payload)
        created_id = self.client._extract_created_id_from_response(resp)
        if isinstance(created_id, int):
            return created_id
        # Fallback: re-query by name
        refreshed = self.find_product_id_by_name(name)
        if isinstance(refreshed, int):
            return refreshed
        raise RuntimeError("Product creation succeeded but new id could not be determined")
    
    def get_product_name_map(self) -> Dict[int, str]:
        """Return a map of product_id -> product_name."""
        candidate_paths = [
            "/objects/products",
            "/objects/products/",
        ]
        last_error: Optional[Exception] = None
        for path in candidate_paths:
            try:
                data = self.client._get(path)
                products: List[Dict[str, Any]]
                if isinstance(data, list):
                    products = data
                elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    products = data["data"]
                else:
                    continue
                id_to_name: Dict[int, str] = {}
                for p in products:
                    pid = p.get("id")
                    name = p.get("name")
                    if isinstance(pid, (int, float)) and isinstance(name, str):
                        id_to_name[int(pid)] = name
                return id_to_name
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
        raise ValueError("Failed to retrieve products list for name mapping")
    
    def list_all_products(self) -> List[Dict[str, Any]]:
        """Return all products with full details from /objects/products."""
        data = self.client._get("/objects/products")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        return []

