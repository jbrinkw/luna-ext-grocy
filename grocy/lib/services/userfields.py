"""Userfield management and detection operations."""

from typing import Any, Dict, List, Optional

from core.client import GrocyClient


class UserfieldService:
    """Handles product userfields operations."""
    
    def __init__(self, client: GrocyClient):
        self.client = client
    
    def fetch_userfield_definitions(self) -> List[Dict[str, Any]]:
        """Return all userfield definitions.

        Compatible with Grocy variants that return a list or { data: [...] }.
        """
        data = self.client._get("/objects/userfields")
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    def detect_walmart_userfield_key(self) -> Optional[str]:
        """Best-effort detection of the Walmart link userfield key for products.

        Heuristic: entity/object_name == "products" and name/caption contains
        "walmart" (case-insensitive). Prefer when it also includes "link"/"url".
        """
        defs = self.fetch_userfield_definitions()
        candidates: List[tuple[int, str]] = []
        for d in defs:
            ent = (d.get("entity") or d.get("object_name") or "").lower()
            if ent != "products":
                continue
            name = d.get("name") or d.get("key")
            caption = d.get("caption") or d.get("title")
            for cand in (name, caption):
                if isinstance(cand, str) and "walmart" in cand.lower():
                    score = 1
                    low = cand.lower()
                    if "link" in low or "url" in low:
                        score = 2
                    if isinstance(name, str):
                        candidates.append((score, name))
                    break
        if candidates:
            candidates.sort(key=lambda t: (-t[0], t[1]))
            return candidates[0][1]
        return None

    def detect_price_userfield_key(self) -> Optional[str]:
        """Best-effort detection of a price userfield key for products.

        Heuristic: entity/object_name == "products" and name/caption contains
        "price" (case-insensitive). Prefer those that also include "unit" or "per".
        """
        defs = self.fetch_userfield_definitions()
        candidates: List[tuple[int, str]] = []
        for d in defs:
            ent = (d.get("entity") or d.get("object_name") or "").lower()
            if ent != "products":
                continue
            name = d.get("name") or d.get("key")
            caption = d.get("caption") or d.get("title")
            for cand in (name, caption):
                if isinstance(cand, str) and "price" in cand.lower():
                    score = 1
                    low = cand.lower()
                    if "unit" in low or "per" in low:
                        score = 2
                    if isinstance(name, str):
                        candidates.append((score, name))
                    break
        if candidates:
            candidates.sort(key=lambda t: (-t[0], t[1]))
            return candidates[0][1]
        return None

    def get_product_userfields(self, product_id: int) -> Dict[str, Any]:
        """Return userfields object for a product (supports multiple endpoints)."""
        pid = int(product_id)
        try:
            data = self.client._get(f"/objects/products/{pid}/userfields")
            if isinstance(data, dict):
                return data
        except Exception as e:
            import requests
            if isinstance(e, requests.HTTPError):
                status = getattr(e.response, "status_code", None)
                if status not in {404, 405}:
                    raise
        data = self.client._get(f"/userfields/products/{pid}")
        return data if isinstance(data, dict) else {}

    def set_product_userfields(self, product_id: int, values: Dict[str, Any]) -> Any:
        """Set userfields for a product trying several endpoint variants.

        Tries:
        1) PUT  /objects/products/{id}/userfields
        2) POST /objects/products/{id}/userfields
        3) PUT  /userfields/products/{id}
        4) POST /userfields/products/{id}
        """
        pid = int(product_id)
        body = dict(values or {})
        errors: List[str] = []
        try:
            return self.client._put(f"/objects/products/{pid}/userfields", json_body=body)
        except Exception as e:
            errors.append(f"PUT /objects/products/{{id}}/userfields -> {e}")
        try:
            return self.client._post(f"/objects/products/{pid}/userfields", json_body=body)
        except Exception as e:
            errors.append(f"POST /objects/products/{{id}}/userfields -> {e}")
        try:
            return self.client._put(f"/userfields/products/{pid}", json_body=body)
        except Exception as e:
            errors.append(f"PUT /userfields/products/{{id}} -> {e}")
        try:
            return self.client._post(f"/userfields/products/{pid}", json_body=body)
        except Exception as e:
            errors.append(f"POST /userfields/products/{{id}} -> {e}")
        raise RuntimeError("All attempts to set userfields failed:\n" + "\n".join(errors))

