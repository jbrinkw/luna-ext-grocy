#!/usr/bin/env python3
"""
Build Walmart links for all items in the Grocy shopping list:
- For regular products: generates add-to-cart URLs with quantity
- For placeholder products: generates Walmart search URLs

Regular products: reads the Walmart link userfield, extracts the Walmart
item id via regex, and formats add-to-cart URLs.

Placeholder products: generates search URLs using the product name.

Output: one URL per line and a trailing summary count line.

Optional: auto-open the links in the default browser, waiting a random
delay between 0 and MAX seconds between each open (MAX settable at top).

Reference example item link:
  https://www.walmart.com/ip/Great-Value-Whole-Vitamin-D-Milk-Gallon-Plastic-Jug-128-Fl-Oz/10450114?classType=REGULAR&athbdg=L1100&from=/search
Item id is the number segment right before the '?' (e.g., 10450114).

Reference add-to-cart format:
  https://affil.walmart.com/cart/addToCart?items=<ITEM_ID>|1

Reference search format:
  https://www.walmart.com/search?q=<PRODUCT_NAME>
"""

import os
import re
import sys
import time
import json
import math
import random
import webbrowser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import requests

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None  # type: ignore


# Auto-open toggle and max wait (seconds)
AUTO_OPEN_LINKS = 1
AUTO_OPEN_MAX_WAIT_SECONDS = 3


def _load_env() -> None:
    try:
        if load_dotenv is not None:
            load_dotenv(override=False)
            here = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(here, ".env")
            if os.path.exists(env_path):
                load_dotenv(dotenv_path=env_path, override=False)
    except Exception:
        pass


def _base_url() -> str:
    return (os.getenv("GROCY_BASE_URL") or "http://192.168.0.185/api").rstrip("/")


def _headers() -> Dict[str, str]:
    api_key = os.getenv("GROCY_API_KEY")
    if not api_key:
        raise RuntimeError("GROCY_API_KEY is required")
    return {
        "GROCY-API-KEY": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{_base_url()}{path}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=25)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return resp.text


def _list_shopping_list_items(shopping_list_id: Optional[int] = 1) -> List[Dict[str, Any]]:
    """Return shopping list items, compatible with Grocy 4.5.

    Preferred endpoint: GET /objects/shopping_list
    Fallback (older deployments): GET /stock/shoppinglist
    """
    candidates = [
        "/objects/shopping_list",
        "/objects/shopping_list/",
        "/stock/shoppinglist",
        "/stock/shoppinglist/",
    ]
    last_err: Optional[Exception] = None
    items: List[Dict[str, Any]] = []
    for path in candidates:
        try:
            data = _get(path)
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                items = data["data"]
            elif isinstance(data, list):
                items = data
            else:
                items = []
            break
        except Exception as e:
            last_err = e
            continue
    if last_err and not items:
        raise last_err

    if shopping_list_id is None:
        return items
    sid = int(shopping_list_id)
    out: List[Dict[str, Any]] = []
    for it in items:
        item_sid = it.get("shopping_list_id")
        if isinstance(item_sid, (int, float)) and int(item_sid) == sid:
            out.append(it)
    return out


def _fetch_userfield_definitions() -> List[Dict[str, Any]]:
    data = _get("/objects/userfields")
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data, list):
        return data
    return []


def _find_walmart_field_key(defs: List[Dict[str, Any]]) -> Optional[str]:
    candidates: List[Tuple[int, str]] = []
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


def _get_product_userfields(product_id: int) -> Dict[str, Any]:
    try:
        data = _get(f"/objects/products/{int(product_id)}/userfields")
        if isinstance(data, dict):
            return data
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) not in {404, 405}:
            raise
    data = _get(f"/userfields/products/{int(product_id)}")
    return data if isinstance(data, dict) else {}


def _extract_item_id_from_walmart_link(url: str) -> Optional[str]:
    # Expect pattern: .../ip/<name-with-dashes>/<digits>?...
    m = re.search(r"/ip/[^/]+/(\d+)\?", url)
    if m:
        return m.group(1)
    return None


def _build_add_to_cart(item_id: str, qty: int = 1) -> str:
    return f"https://affil.walmart.com/cart/addToCart?items={item_id}|{int(qty)}"


def _extract_amount(item: Dict[str, Any]) -> Optional[float]:
    # Try common keys seen in Grocy responses
    for key in ("amount", "quantity", "amount_aggregated", "available_amount"):
        val = item.get(key)
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except Exception:
                pass
    return None


def _get_product_name_map() -> Dict[int, str]:
    """Fetch all products and return a dict mapping product_id -> name."""
    try:
        data = _get("/objects/products")
        products = data if isinstance(data, list) else []
        name_map: Dict[int, str] = {}
        for p in products:
            if isinstance(p, dict):
                pid = p.get("id")
                name = p.get("name")
                if isinstance(pid, (int, float)) and isinstance(name, str):
                    name_map[int(pid)] = name
        return name_map
    except Exception:
        return {}


def main(argv: Optional[List[str]] = None) -> int:
    _load_env()

    # Optional: allow shopping list id via args (default 1)
    sid: Optional[int] = 1
    if argv is None:
        args = sys.argv[1:]
    else:
        args = argv
    if args:
        try:
            sid = int(args[0])
        except Exception:
            sid = 1

    try:
        defs = _fetch_userfield_definitions()
        w_key = _find_walmart_field_key(defs)
    except Exception as e:
        print(f"[error] Failed to fetch/resolve userfield definitions: {e}", file=sys.stderr)
        w_key = None

    if not isinstance(w_key, str) or not w_key:
        print("[error] Could not detect Walmart link userfield key for products", file=sys.stderr)
        return 2

    try:
        items = _list_shopping_list_items(sid)
    except Exception as e:
        print(f"[error] Failed to read shopping list: {e}", file=sys.stderr)
        return 2

    # Get product name map for placeholders
    name_map = _get_product_name_map()

    links: List[str] = []
    for it in items:
        pid = it.get("product_id")
        if not isinstance(pid, (int, float)):
            continue
        
        pid_int = int(pid)
        uf = _get_product_userfields(pid_int)
        
        # Check if product is a placeholder
        is_placeholder = bool(uf.get("placeholder", False))
        
        if is_placeholder:
            # Generate search URL for placeholder products
            product_name = name_map.get(pid_int, f"Product {pid_int}")
            search_url = f"https://www.walmart.com/search?q={quote_plus(product_name)}"
            links.append(search_url)
        else:
            # Try to build add-to-cart URL for regular products
            url = uf.get(w_key)
            if not isinstance(url, str) or not url.strip():
                continue
            item_id = _extract_item_id_from_walmart_link(url)
            if not isinstance(item_id, str):
                continue
            amt = _extract_amount(it)
            qty = int(math.ceil(float(amt))) if isinstance(amt, (int, float)) else 1
            if qty < 1:
                qty = 1
            cart_url = _build_add_to_cart(item_id, qty=qty)
            links.append(cart_url)

    for url in links:
        print(url)
    print(f"# {len(links)} total links ({sum(1 for u in links if 'search' in u)} search, {sum(1 for u in links if 'addToCart' in u)} add-to-cart)")

    if AUTO_OPEN_LINKS and links:
        for url in links:
            try:
                webbrowser.open_new_tab(url)
            except Exception:
                pass
            try:
                wait = random.random() * float(AUTO_OPEN_MAX_WAIT_SECONDS or 0)
                time.sleep(wait)
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


