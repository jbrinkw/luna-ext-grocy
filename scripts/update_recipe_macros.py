#!/usr/bin/env python3
"""
Update recipe userfields (per-serving) from ingredient product userfields for all recipes.

Assumptions (per user):
- Product userfields (exact keys, per serving):
  - Calories_Per_Serving, Carbs, Fats, Protein
- Product userfields (container metadata):
  - num_servings  (servings per container)
- Ignore Serving_Weight
- Each product has global quantity units: "Container" and "Serving"
  - If an ingredient amount is in Container, multiply per-serving macros by (amount * num_servings)
  - If an ingredient amount is in Serving, multiply per-serving macros by amount
- For each recipe, divide total across ingredients by recipe.base_servings to get per-serving values
- Update recipe userfields (exact keys): recipe_calories (int), recipe_carbs, recipe_fats, recipe_proteins (floats)
- If data is missing at any step, log a warning and continue.

Env:
- GROCY_API_KEY (required)
- GROCY_BASE_URL (required; e.g., http://host/api)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


# Populated at runtime for debug logs
PRODUCT_NAME_MAP: Dict[int, str] = {}


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


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{_base_url()}{path}"
    resp = requests.get(url, headers=_headers_get(), params=params, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return resp.text


def _put(path: str, body: Dict[str, Any]) -> Any:
    url = f"{_base_url()}{path}"
    resp = requests.put(url, headers=_headers_json(), json=body, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return resp.text


def _list_recipes() -> List[Dict[str, Any]]:
    data = _get("/objects/recipes")
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data, list):
        return data
    return []


def _list_recipe_ingredients(recipe_id: int) -> List[Dict[str, Any]]:
    data = _get("/objects/recipes_pos")
    rows: List[Dict[str, Any]]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        rows = data["data"]
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    out: List[Dict[str, Any]] = []
    for it in rows:
        try:
            if int(it.get("recipe_id", -1)) == int(recipe_id):
                out.append(it)
        except Exception:
            continue
    return out


def _get_product_userfields(product_id: int) -> Dict[str, Any]:
    # Try primary path; fallback to alternate per Grocy versions
    try:
        data = _get(f"/objects/products/{int(product_id)}/userfields")
        if isinstance(data, dict):
            return data
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) not in {404, 405}:
            raise
    # Fallback
    data = _get(f"/userfields/products/{int(product_id)}")
    return data if isinstance(data, dict) else {}


def _get_units_map() -> Dict[int, str]:
    """Return map: qu_id -> unit name."""
    data = _get("/objects/quantity_units")
    items = (
        data.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), list)
        else (data if isinstance(data, list) else [])
    )
    out: Dict[int, str] = {}
    for it in items:
        try:
            qid = int(it.get("id"))
            name = str(it.get("name") or "").strip()
            out[qid] = name
        except Exception:
            continue
    return out


def _norm_unit_key(name: str) -> str:
    s = (name or "").strip().lower()
    if s.endswith("s"):
        s = s[:-1]
    return s


def _get_product_name_map() -> Dict[int, str]:
    data = _get("/objects/products")
    items = (
        data.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), list)
        else (data if isinstance(data, list) else [])
    )
    out: Dict[int, str] = {}
    for it in items:
        try:
            pid = int(it.get("id"))
            name = str(it.get("name") or "").strip()
            if name:
                out[pid] = name
        except Exception:
            continue
    return out


def _compute_recipe_per_serving(
    recipe: Dict[str, Any],
    ingredients: List[Dict[str, Any]],
    unit_name_by_id: Dict[int, str],
    product_userfields_cache: Dict[int, Dict[str, Any]],
) -> Optional[Tuple[int, float, float, float]]:
    rid = int(recipe.get("id"))
    base_servings_raw = recipe.get("base_servings")
    try:
        base_servings = (
            float(base_servings_raw)
            if isinstance(base_servings_raw, (int, float))
            else float(str(base_servings_raw))
        )
    except Exception:
        base_servings = 0.0
    if not base_servings or base_servings <= 0:
        print(f"[warn] recipe {rid}: missing/invalid base_servings -> skip")
        return None

    total_cals = 0.0
    total_carbs = 0.0
    total_fats = 0.0
    total_proteins = 0.0

    for ing in ingredients:
        pid = ing.get("product_id")
        amt = ing.get("amount")
        qid = ing.get("qu_id")
        try:
            pid_i = int(pid) if isinstance(pid, (int, float, str)) else None
            amt_f = float(amt) if isinstance(amt, (int, float)) else None
            qid_i = int(qid) if isinstance(qid, (int, float, str)) else None
        except Exception:
            pid_i, amt_f, qid_i = None, None, None

        if not isinstance(pid_i, int) or not isinstance(amt_f, float) or amt_f <= 0:
            print(
                f"[warn] recipe {rid}: ingredient missing product/amount -> skip ingredient {ing.get('id')}"
            )
            continue
        if not isinstance(qid_i, int) or qid_i not in unit_name_by_id:
            print(
                f"[warn] recipe {rid}: ingredient product {pid_i} missing/unknown qu_id -> skip ingredient"
            )
            continue

        unit_name = unit_name_by_id.get(qid_i) or ""
        unit_key = _norm_unit_key(unit_name)
        if unit_key not in {"container", "serving"}:
            print(
                f"[warn] recipe {rid}: ingredient product {pid_i} unit '{unit_name}' not supported -> skip ingredient"
            )
            continue

        # Fetch product userfields (cached)
        if pid_i not in product_userfields_cache:
            product_userfields_cache[pid_i] = _get_product_userfields(pid_i)
        uf = product_userfields_cache.get(pid_i) or {}

        try:
            per_cal = float(uf.get("Calories_Per_Serving"))
            per_carbs = float(uf.get("Carbs"))
            per_fats = float(uf.get("Fats"))
            per_protein = float(uf.get("Protein"))
        except Exception:
            print(
                f"[warn] recipe {rid}: product {pid_i} missing one of per-serving macros -> skip ingredient"
            )
            continue

        # num_servings only needed for container unit
        if unit_key == "serving":
            # Heuristic: Some recipes save amount as a fraction of a container but mark unit as Serving.
            # If amount < 1 and amount * num_servings is near an integer, treat it as that many servings.
            nserv = None
            servings_multiplier = amt_f
            try:
                maybe_nserv = float(uf.get("num_servings"))
            except Exception:
                maybe_nserv = None
            if (
                isinstance(maybe_nserv, float)
                and maybe_nserv > 0
                and amt_f < 1.0
            ):
                candidate = amt_f * maybe_nserv
                rounded = round(candidate)
                if abs(rounded - candidate) <= 0.02:  # tolerant to 0.1667 * 6 = 1.0002
                    nserv = maybe_nserv
                    servings_multiplier = float(rounded)
        else:  # container
            try:
                nserv = float(uf.get("num_servings"))
            except Exception:
                print(
                    f"[warn] recipe {rid}: product {pid_i} missing num_servings for container unit -> skip ingredient"
                )
                continue
            servings_multiplier = amt_f * nserv

        # Debug: per-ingredient contribution
        try:
            pname = PRODUCT_NAME_MAP.get(pid_i) if isinstance(pid_i, int) else None
        except Exception:
            pname = None
        contrib_cals = per_cal * servings_multiplier
        contrib_carbs = per_carbs * servings_multiplier
        contrib_fats = per_fats * servings_multiplier
        contrib_proteins = per_protein * servings_multiplier
        ns_str = ("N/A" if nserv is None else str(nserv))
        print(
            f"[ingredient] recipe {rid} '{recipe.get('name')}' -> product {pid_i} '{pname or ''}', unit='{unit_name}', amount={amt_f}, "
            f"per_serv(macros)={{cal:{per_cal}, carbs:{per_carbs}, fats:{per_fats}, protein:{per_protein}}}, num_servings={ns_str}, "
            f"multiplier={servings_multiplier} -> contributes={{cal:{contrib_cals}, carbs:{contrib_carbs}, fats:{contrib_fats}, protein:{contrib_proteins}}}"
        )

        total_cals += contrib_cals
        total_carbs += contrib_carbs
        total_fats += contrib_fats
        total_proteins += contrib_proteins

    if total_cals == 0 and total_carbs == 0 and total_fats == 0 and total_proteins == 0:
        print(f"[warn] recipe {rid}: no computable ingredients -> skip")
        return None

    # Totals before division
    print(
        f"[recipe-totals] id={rid} name='{recipe.get('name')}' base_servings={base_servings} "
        f"sum_before_div={{cal:{total_cals}, carbs:{total_carbs}, fats:{total_fats}, protein:{total_proteins}}}"
    )

    # Per-serving for the recipe
    cals_per_serv = round(total_cals / base_servings)
    carbs_per_serv = round(total_carbs / base_servings, 2)
    fats_per_serv = round(total_fats / base_servings, 2)
    proteins_per_serv = round(total_proteins / base_servings, 2)

    return int(cals_per_serv), carbs_per_serv, fats_per_serv, proteins_per_serv


def _update_recipe_userfields(recipe_id: int, values: Dict[str, Any]) -> None:
    # Try standard endpoint; if 404/405, fall back
    try:
        _put(f"/objects/recipes/{int(recipe_id)}/userfields", values)
        return
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) not in {404, 405}:
            raise
    _put(f"/userfields/recipes/{int(recipe_id)}", values)


def main() -> int:
    try:
        load_dotenv(override=False)
    except Exception:
        pass

    try:
        unit_name_by_id = _get_units_map()
    except Exception as exc:
        print(f"Error: failed to load quantity units: {exc}", file=sys.stderr)
        return 2

    recipes = _list_recipes()
    if not recipes:
        print("[info] No recipes found.")
        return 0

    product_userfields_cache: Dict[int, Dict[str, Any]] = {}
    # Build product name map once for debug logs
    global PRODUCT_NAME_MAP
    try:
        PRODUCT_NAME_MAP = _get_product_name_map()
    except Exception:
        PRODUCT_NAME_MAP = {}
    updated_count = 0
    skipped_count = 0

    for r in recipes:
        rid = r.get("id")
        name = r.get("name")
        try:
            rid_i = int(rid)
        except Exception:
            print(f"[warn] recipe with invalid id {rid} -> skip")
            skipped_count += 1
            continue

        try:
            ings = _list_recipe_ingredients(rid_i)
        except Exception as exc:
            print(f"[warn] recipe {rid_i}: failed to list ingredients: {exc} -> skip")
            skipped_count += 1
            continue

        print(f"[recipe] id={rid_i} name='{name}' base_servings={r.get('base_servings')} ingredients={len(ings)}")
        result = _compute_recipe_per_serving(r, ings, unit_name_by_id, product_userfields_cache)
        if result is None:
            skipped_count += 1
            continue

        cals_i, carbs_f, fats_f, proteins_f = result
        payload = {
            "recipe_calories": int(cals_i),
            "recipe_carbs": float(carbs_f),
            "recipe_fats": float(fats_f),
            "recipe_proteins": float(proteins_f),
        }

        try:
            _update_recipe_userfields(rid_i, payload)
            updated_count += 1
            print(
                f"[ok] recipe {rid_i} '{name}': cal={payload['recipe_calories']}, carbs={payload['recipe_carbs']}, "
                f"fats={payload['recipe_fats']}, proteins={payload['recipe_proteins']}"
            )
        except Exception as exc:
            print(f"[warn] recipe {rid_i}: failed to update userfields: {exc}")
            skipped_count += 1

    print(f"[done] updated={updated_count}, skipped={skipped_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


