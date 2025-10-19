"""
Placeholder matching module.

Uses GPT-4.1 to match product names against Grocy placeholder items.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

# Add lib directory to path
_lib_path = Path(__file__).parent.parent
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from core.client import GrocyClient

# Load environment
try:
    load_dotenv(override=False)
except Exception:
    pass


def match_product_name_to_placeholders(product_name: str) -> Optional[int]:
    """Use GPT-4.1 to match product name against Grocy placeholder items.
    
    Args:
        product_name: Product name from Nutritionix API
        
    Returns:
        Placeholder product_id if matched, else None
    """
    try:
        client = GrocyClient()
        
        # Get all placeholder products
        all_products = client._get("/objects/products")
        if isinstance(all_products, dict) and "data" in all_products:
            all_products = all_products["data"]
        
        # Filter to placeholders only
        placeholders = []
        for product in all_products:
            try:
                pid = int(product.get("id"))
                name = product.get("name")
                
                # Check if it has placeholder=True userfield
                userfields = client.get_product_userfields(pid)
                is_placeholder = userfields.get("placeholder") or userfields.get("Placeholder")
                
                if is_placeholder and name:
                    placeholders.append({"id": pid, "name": name})
            except Exception:
                continue
        
        # If no placeholders, return None
        if not placeholders:
            return None
        
        # Call LLM for matching
        return _call_gpt_for_match(product_name, placeholders)
        
    except Exception:
        # If anything fails, return None
        return None


def _call_gpt_for_match(product_name: str, placeholders: list) -> Optional[int]:
    """Call GPT-4.1 to match product against placeholders.
    
    Args:
        product_name: Product name to match
        placeholders: List of {id, name} dicts
        
    Returns:
        Matched product_id or None
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        
        client = OpenAI(api_key=api_key)
        
        # Build prompt
        placeholder_list = "\n".join(f"ID {p['id']}: {p['name']}" for p in placeholders)
        
        prompt = f"""Given a product name, determine if it matches one of the placeholder items.
Return the ID of the matching placeholder, or null if no match.

Product name to match: "{product_name}"

Placeholder items:
{placeholder_list}

Return ONLY a JSON object with this format:
{{"matched_product_id": <id or null>}}

Match if the product name and placeholder refer to the same product, allowing for minor variations like additional descriptors, sizes, or formatting differences. Return null only if they are genuinely different products."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that matches product names. You respond ONLY with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        
        # Parse response
        content = response.choices[0].message.content
        data = json.loads(content)
        
        matched_id = data.get("matched_product_id")
        if matched_id is None or matched_id == "null":
            return None
        
        return int(matched_id)
        
    except Exception:
        return None


def override_placeholder_with_real_data(placeholder_product_id: int, real_data: Dict[str, Any]) -> None:
    """Override placeholder product fields with real Nutritionix data.
    
    Args:
        placeholder_product_id: Grocy product id of placeholder
        real_data: Dict with keys:
            - name: str
            - calories_per_serving: float
            - carbs: float
            - fats: float
            - protein: float
            - num_servings: float
            - price: Optional[float]
    """
    try:
        client = GrocyClient()
        
        # Update product name
        client._put(f"/objects/products/{placeholder_product_id}", {
            "name": real_data["name"]
        })
        
        # Update userfields with macro data
        userfield_updates = {
            "Calories_Per_Serving": float(real_data.get("calories_per_serving", 0)),
            "Carbs": float(real_data.get("carbs", 0)),
            "Fats": float(real_data.get("fats", 0)),
            "Protein": float(real_data.get("protein", 0)),
            "num_servings": float(real_data.get("num_servings", 1)),
            "placeholder": False,  # No longer a placeholder
        }
        
        client.set_product_userfields(placeholder_product_id, userfield_updates)
        
        # Update built-in energy field
        total_cals = (
            float(real_data.get("calories_per_serving", 0)) * 
            float(real_data.get("num_servings", 1))
        )
        try:
            client._put(f"/objects/products/{placeholder_product_id}", {
                "calories": int(total_cals)
            })
        except Exception:
            # Try alternate field name
            try:
                client._put(f"/objects/products/{placeholder_product_id}", {
                    "energy": int(total_cals)
                })
            except Exception:
                pass
        
        # Set price if provided
        price = real_data.get("price")
        if price is not None and float(price) > 0:
            try:
                # Add 1 unit at specified price, then consume 1 to keep stock unchanged
                client.add_product_quantity_with_price(
                    placeholder_product_id, 
                    quantity=1.0, 
                    price=float(price)
                )
                client.consume_product_quantity(placeholder_product_id, quantity=1.0)
            except Exception:
                pass
                
    except Exception as e:
        raise RuntimeError(f"Failed to override placeholder: {e}")


if __name__ == "__main__":
    """CLI wrapper for server.js to call."""
    import sys
    
    try:
        if len(sys.argv) < 2:
            print(json.dumps({"error": "Usage: placeholder_matcher.py [match|override] ..."}), flush=True)
            sys.exit(1)
        
        command = sys.argv[1]
        
        if command == "match":
            if len(sys.argv) < 3:
                print(json.dumps({"error": "Usage: placeholder_matcher.py match <product_name>"}), flush=True)
                sys.exit(1)
            
            product_name = sys.argv[2]
            matched_id = match_product_name_to_placeholders(product_name)
            print(json.dumps({"matched_product_id": matched_id}), flush=True)
        
        elif command == "override":
            if len(sys.argv) < 4:
                print(json.dumps({"error": "Usage: placeholder_matcher.py override <product_id> <json_data>"}), flush=True)
                sys.exit(1)
            
            product_id = int(sys.argv[2])
            real_data = json.loads(sys.argv[3])
            override_placeholder_with_real_data(product_id, real_data)
            print(json.dumps({"status": "ok"}), flush=True)
        
        else:
            print(json.dumps({"error": f"Unknown command: {command}"}), flush=True)
            sys.exit(1)
    
    except Exception as e:
        print(json.dumps({"error": str(e), "matched_product_id": None}), flush=True)
        sys.exit(1)
