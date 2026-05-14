"""
nutrition_logger/lookup.py
===========================
Food database lookup: CoFID (local) + USDA (API) + Claude-picks.

Public:
    lookup_food(query, original_food) -> dict | None
    scale_nutrients(nutrients_per_100g, quantity_g) -> dict
    to_grams(quantity, unit) -> float | None
"""

import re
import sqlite3
import logging
import requests
import anthropic

from .db import get_cofid_path
from .lookup_tables import COFID_LOOKUP

log = logging.getLogger(__name__)

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USDA_FOOD_URL   = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"

UNIT_TO_GRAMS = {
    "ml": 1.0, "millilitre": 1.0, "milliliter": 1.0,
    "l": 1000.0, "litre": 1000.0, "liter": 1000.0,
    "cup": 240.0, "tbsp": 15.0, "tablespoon": 15.0,
    "tsp": 5.0, "teaspoon": 5.0, "fl oz": 30.0,
    "oz": 28.35, "ounce": 28.35,
    "g": 1.0, "gram": 1.0, "grams": 1.0,
    "kg": 1000.0, "kilogram": 1000.0,
    "lb": 453.6, "pound": 453.6,
    "slice": 30.0, "piece": 50.0, "handful": 30.0,
    "portion": 100.0, "tin": 120.0, "can": 120.0,
}

NUTRIENT_MAP = {
    "208": "energy_kcal", "1008": "energy_kcal", "2047": "energy_kcal",
    "203": "protein_g",   "1003": "protein_g",
    "204": "fat_total_g", "1004": "fat_total_g",
    "205": "carbohydrate_g", "1005": "carbohydrate_g",
    "291": "fibre_g",     "1079": "fibre_g",
    "269": "sugars_g",    "2000": "sugars_g",
    "606": "saturated_fat_g",    "1258": "saturated_fat_g",
    "645": "monounsaturated_fat_g", "1292": "monounsaturated_fat_g",
    "646": "polyunsaturated_fat_g", "1293": "polyunsaturated_fat_g",
    "605": "trans_fat_g", "1257": "trans_fat_g",
    "619": "omega3_ala_g", "1404": "omega3_ala_g",
    "629": "omega3_epa_g", "1278": "omega3_epa_g",
    "631": "omega3_dpa_g", "1279": "omega3_dpa_g",
    "621": "omega3_dha_g", "1280": "omega3_dha_g",
    "301": "calcium_mg",  "1087": "calcium_mg",
    "303": "iron_mg",     "1089": "iron_mg",
    "304": "magnesium_mg","1090": "magnesium_mg",
    "305": "phosphorus_mg","1091": "phosphorus_mg",
    "306": "potassium_mg","1092": "potassium_mg",
    "307": "sodium_mg",   "1093": "sodium_mg",
    "309": "zinc_mg",     "1095": "zinc_mg",
    "312": "copper_mg",   "1098": "copper_mg",
    "315": "manganese_mg","1101": "manganese_mg",
    "317": "selenium_ug", "1103": "selenium_ug",
    "320": "vitamin_a_ug_rae", "1106": "vitamin_a_ug_rae",
    "401": "vitamin_c_mg","1162": "vitamin_c_mg",
    "328": "vitamin_d_ug","1114": "vitamin_d_ug",
    "323": "vitamin_e_mg","1109": "vitamin_e_mg",
    "430": "vitamin_k_ug","1185": "vitamin_k_ug",
    "404": "thiamin_mg",  "1165": "thiamin_mg",
    "405": "riboflavin_mg","1166": "riboflavin_mg",
    "406": "niacin_mg",   "1167": "niacin_mg",
    "410": "pantothenic_acid_mg","1170": "pantothenic_acid_mg",
    "415": "vitamin_b6_mg","1175": "vitamin_b6_mg",
    "417": "folate_ug",   "1177": "folate_ug",
    "418": "vitamin_b12_ug","1178": "vitamin_b12_ug",
    "421": "choline_mg",  "1180": "choline_mg",
    "501": "tryptophan_g","1210": "tryptophan_g",
    "502": "threonine_g", "1211": "threonine_g",
    "503": "isoleucine_g","1212": "isoleucine_g",
    "504": "leucine_g",   "1213": "leucine_g",
    "505": "lysine_g",    "1214": "lysine_g",
    "506": "methionine_g","1215": "methionine_g",
    "508": "phenylalanine_g","1216": "phenylalanine_g",
    "510": "valine_g",    "1217": "valine_g",
    "511": "arginine_g",  "1218": "arginine_g",
    "514": "glycine_g",   "1220": "glycine_g",
    "517": "proline_g",   "1221": "proline_g",
    "515": "glutamic_acid_g","1223": "glutamic_acid_g",
}

COFID_NUTRIENT_MAP = {
    "energy_kcal": "energy_kcal", "protein_g": "protein_g",
    "fat_total_g": "fat_total_g", "carbohydrate_g": "carbohydrate_g",
    "sugars_g": "sugars_g", "fibre_g": "fibre_g",
    "saturated_fat_g": "saturated_fat_g",
    "monounsaturated_fat_g": "monounsaturated_fat_g",
    "polyunsaturated_fat_g": "polyunsaturated_fat_g",
    "trans_fat_g": "trans_fat_g", "omega3_total_g": "omega3_ala_g",
    "sodium_mg": "sodium_mg", "potassium_mg": "potassium_mg",
    "calcium_mg": "calcium_mg", "magnesium_mg": "magnesium_mg",
    "phosphorus_mg": "phosphorus_mg", "iron_mg": "iron_mg",
    "copper_mg": "copper_mg", "zinc_mg": "zinc_mg",
    "manganese_mg": "manganese_mg", "selenium_ug": "selenium_ug",
    "iodine_ug": "iodine_ug", "vitamin_a_ug_rae": "vitamin_a_ug_rae",
    "vitamin_d_ug": "vitamin_d_ug", "vitamin_e_mg": "vitamin_e_mg",
    "vitamin_k_ug": "vitamin_k_ug", "thiamin_mg": "thiamin_mg",
    "riboflavin_mg": "riboflavin_mg", "niacin_mg": "niacin_mg",
    "vitamin_b6_mg": "vitamin_b6_mg", "vitamin_b12_ug": "vitamin_b12_ug",
    "folate_ug": "folate_ug", "pantothenic_acid_mg": "pantothenic_acid_mg",
    "vitamin_c_mg": "vitamin_c_mg",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def to_grams(quantity, unit: str):
    if quantity is None:
        return None
    factor = UNIT_TO_GRAMS.get(str(unit).lower().strip())
    return round(float(quantity) * factor, 2) if factor else None


def scale_nutrients(nutrients_per_100g: dict, quantity_g: float) -> dict:
    if not quantity_g:
        return nutrients_per_100g
    f = quantity_g / 100.0
    return {k: round(v * f, 4) for k, v in nutrients_per_100g.items() if v is not None}


def _usda_key():
    import os
    key = os.environ.get("USDA_API_KEY")
    if not key:
        try:
            import config as c; key = c.USDA_KEY
        except ImportError:
            pass
    return key


def _cofid_nutrients(row: dict) -> dict:
    return {std: row[c] for c, std in COFID_NUTRIENT_MAP.items()
            if row.get(c) is not None}

# ── USDA ──────────────────────────────────────────────────────────────────────

def _get_usda_nutrients(fdc_id: int) -> dict:
    resp = requests.get(
        USDA_FOOD_URL.format(fdc_id=fdc_id),
        params={"api_key": _usda_key()},
        timeout=10
    )
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    out = {}
    for n in resp.json().get("foodNutrients", []):
        num = str(n.get("nutrient", {}).get("number", "")) or str(n.get("nutrientId", ""))
        val = n.get("amount") if n.get("amount") is not None else n.get("value")
        if num in NUTRIENT_MAP and val is not None:
            out[NUTRIENT_MAP[num]] = val
    return out


def _search_usda(query: str, n: int = 3) -> list:
    candidates = []
    for dtype in ["SR Legacy", "Foundation"]:
        try:
            resp = requests.get(USDA_SEARCH_URL, params={
                "query": query, "api_key": _usda_key(),
                "dataType": dtype, "pageSize": n,
            }, timeout=10)
            if resp.ok:
                candidates.extend(resp.json().get("foods", [])[:n])
        except Exception as e:
            log.debug(f"USDA search error: {e}")
    return candidates

# ── CoFID ─────────────────────────────────────────────────────────────────────

def _search_cofid(query: str, n: int = 3) -> list:
    db_path = get_cofid_path()
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        words = [w for w in query.lower().split() if len(w) > 2]
        for num_words in range(len(words), 0, -1):
            subset = words[:num_words]
            conditions = " AND ".join(f"LOWER(food_name) LIKE ?" for _ in subset)
            params = [f"%{w}%" for w in subset]
            results = conn.execute(
                f"SELECT * FROM cofid WHERE {conditions} ORDER BY LENGTH(food_name) LIMIT {n}",
                params
            ).fetchall()
            if results:
                conn.close()
                return [dict(r) for r in results]
        conn.close()
    except Exception as e:
        log.debug(f"CoFID search error: {e}")
    return []

# ── Claude picks ──────────────────────────────────────────────────────────────

PICK_SYSTEM = """You are a food matching expert. Given a diary entry and candidates
from food databases, pick the single best match — same food, same cooking method.
Reply ONLY with the candidate number or NONE."""

def _claude_pick(original: str, candidates: list, client) -> dict:
    if not candidates:
        return None
    lines = [f"Diary entry: {original}", "", "Candidates:"]
    for c in candidates:
        lines.append(f"  {c['number']}. [{c['source']}] {c['name']}")
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
        system=PICK_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(lines)}]
    )
    reply = resp.content[0].text.strip().upper()
    if reply == "NONE":
        return None
    try:
        num = int(reply)
        return next((c for c in candidates if c["number"] == num), None)
    except (ValueError, StopIteration):
        return None

# ── Clean search term ─────────────────────────────────────────────────────────

CLEAN_PROMPT = """Convert a food diary entry into a 1-4 word database search term.
Keep the core food name. Keep cooking method if present.
Return ONLY the search term — no explanation.
Examples:
  "carrots, cooked from fresh" → "carrots boiled"
  "chicken breast, skinless, cooked" → "chicken breast grilled"
  "extra virgin olive oil" → "olive oil"
  "rice, white, long-grain, cooked" → "rice white cooked"
  "egg, raw" → "egg whole raw"
"""

VALIDATE_PROMPT = """Check if this search term correctly represents the diary entry.
If correct, return it unchanged. If wrong, return a corrected term.
Reply with ONLY the search term — no explanation.
Core rule: if diary says "carrots", the term must contain "carrot"."""

def clean_query(food_name: str, client) -> str:
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        system=CLEAN_PROMPT,
        messages=[{"role": "user", "content": food_name}]
    )
    term = resp.content[0].text.strip().lower()

    # Validate: core food word must appear in search term
    core_words = [w.lower() for w in food_name.replace(",", " ").split()
                  if len(w) > 3 and w.lower() not in {
                      "cooked", "fresh", "from", "plain", "drained",
                      "canned", "boiled", "baked", "fried", "grilled",
                      "steamed", "roasted", "homemade", "regular",
                      "enriched", "skinless", "boneless", "organic"
                  }][:2]
    term_words = term.split()
    if core_words and not any(
        any(cw in tw or tw in cw for tw in term_words) for cw in core_words
    ):
        resp2 = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            system=VALIDATE_PROMPT,
            messages=[{"role": "user", "content": f"Diary: {food_name}\nTerm: {term}"}]
        )
        term = resp2.content[0].text.strip().lower()
    return term

# ── Main lookup ───────────────────────────────────────────────────────────────

def lookup_food(query: str, original_food: str, client=None) -> dict:
    """
    Full pipeline:
    1. Curated CoFID lookup table (unconditional)
    2. Gather USDA + CoFID candidates
    3. Claude picks best match
    4. Fetch nutrients for winner
    """
    q = query.lower().strip()

    # 1. Curated lookup
    for length in range(len(q.split()), 0, -1):
        partial = " ".join(q.split()[:length])
        if partial in COFID_LOOKUP:
            db_path = get_cofid_path()
            if db_path:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM cofid WHERE food_code = ?",
                    (COFID_LOOKUP[partial],)
                ).fetchone()
                conn.close()
                if row:
                    row = dict(row)
                    nutrients = _cofid_nutrients(row)
                    if nutrients:
                        return {"source": "cofid", "name": row["food_name"],
                                "nutrients_100g": nutrients}

    # 2. Gather candidates
    num = 1
    candidates = []
    for food in _search_usda(query):
        candidates.append({"number": num, "source": "USDA",
                            "name": food["description"], "fdc_id": food["fdcId"],
                            "raw": food})
        num += 1
    for row in _search_cofid(query):
        candidates.append({"number": num, "source": "CoFID",
                            "name": row["food_name"], "raw": row})
        num += 1

    if not candidates:
        return None

    # 3. Claude picks
    chosen = _claude_pick(original_food, candidates, client) if client else candidates[0]
    if not chosen:
        return None

    # 4. Fetch nutrients
    if chosen["source"] == "USDA":
        nutrients = _get_usda_nutrients(chosen["fdc_id"])
        return {"source": "usda", "name": chosen["name"], "nutrients_100g": nutrients}
    else:
        nutrients = _cofid_nutrients(chosen["raw"])
        return {"source": "cofid", "name": chosen["name"], "nutrients_100g": nutrients}
