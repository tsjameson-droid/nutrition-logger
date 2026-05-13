"""
nutrition_logger.py
====================
Diet log parser and nutritional database interface.

Pipeline:
  1. Parse a natural-language diet log with Claude → structured food entries
  2. Match each entry to USDA FoodData Central API → pull nutrient data
  3. Scale nutrients to the actual quantity consumed
  4. Store to a local SQLite database with timestamps
  5. Query the log with natural-language prompts via Claude

Requirements:
    pip install anthropic requests

API keys needed:
    - ANTHROPIC_API_KEY  : https://console.anthropic.com
    - USDA_API_KEY       : https://fdc.nal.usda.gov/api-key-signup.html (free)

Usage:
    logger = NutritionLogger(
        anthropic_key="sk-ant-...",
        usda_key="your-usda-key",
        db_path="nutrition_log.db"   # SQLite file; created automatically
    )

    # Log a day's diet
    logger.log_diet_entry(
        raw_text=\"\"\"
            8am - porridge made with 80g oats and 250ml whole milk, black coffee
            1pm - tin of sardines in olive oil (120g drained), rye bread 2 slices (~60g each),
                  handful of cherry tomatoes (~100g)
            4pm - 30g dark chocolate (85%), green tea
            7pm - 200g salmon fillet pan-fried in olive oil (1 tbsp), steamed broccoli 150g,
                  brown rice 180g cooked
        \"\"\",
        log_date="2025-05-08"   # ISO format; defaults to today if omitted
    )

    # Retrieve data
    result = logger.query("What was my total protein intake today?")
    print(result)

    result = logger.query("Which meal had the most omega-3?")
    print(result)
"""

import json
import sqlite3
import datetime
import requests
import anthropic
from pathlib import Path


# ---------------------------------------------------------------------------
# Handwriting transcription via Claude vision
# ---------------------------------------------------------------------------

TRANSCRIBE_PROMPT = """
You are reading a handwritten food diary. Extract every food and drink item
you can see, preserving times and quantities exactly as written.
Format your output as plain text, one item per line, exactly as if someone
had typed up the handwritten notes. Do not interpret or analyse — just
transcribe what is written. If you cannot read something clearly, write
[illegible] in its place.
"""

def transcribe_image_bytes(image_bytes: bytes, media_type: str,
                            client) -> str:
    """Send an image to Claude vision and return transcribed text."""
    import base64
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": TRANSCRIBE_PROMPT
                }
            ],
        }]
    )
    return response.content[0].text.strip()


def transcribe_image_file(path: str, client) -> str:
    """Transcribe handwriting from a JPG, PNG, or WEBP image file."""
    ext = path.lower().split(".")[-1]
    media_types = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "webp": "image/webp",
        "gif": "image/gif"
    }
    media_type = media_types.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        image_bytes = f.read()
    return transcribe_image_bytes(image_bytes, media_type, client)


def transcribe_handwritten_pdf(path: str, client) -> str:
    """Convert each page of a PDF to an image and transcribe handwriting."""
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    all_text = []
    print(f"  PDF has {len(doc)} page(s)")
    for i, page in enumerate(doc):
        print(f"  Transcribing page {i+1}...")
        # Render page at 2x zoom for better legibility
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        image_bytes = pix.tobytes("png")
        text = transcribe_image_bytes(image_bytes, "image/png", client)
        all_text.append("[Page " + str(i+1) + "] " + text)
    doc.close()
    return "\n\n".join(all_text)


def is_scanned_pdf(path: str) -> bool:
    """Return True if PDF appears to be a scan (no embedded text)."""
    from pypdf import PdfReader
    reader = PdfReader(path)
    total_text = ""
    for page in reader.pages:
        total_text += page.extract_text() or ""
    return len(total_text.strip()) < 50


# ---------------------------------------------------------------------------
# CoFID (McCance & Widdowson) local database search
# ---------------------------------------------------------------------------

# Map CoFID column names to our standard nutrient column names
COFID_NUTRIENT_MAP = {
    "energy_kcal":          "energy_kcal",
    "protein_g":            "protein_g",
    "fat_total_g":          "fat_total_g",
    "carbohydrate_g":       "carbohydrate_g",
    "sugars_g":             "sugars_g",
    "fibre_g":              "fibre_g",
    "saturated_fat_g":      "saturated_fat_g",
    "monounsaturated_fat_g":"monounsaturated_fat_g",
    "polyunsaturated_fat_g":"polyunsaturated_fat_g",
    "trans_fat_g":          "trans_fat_g",
    "omega3_total_g":       "omega3_ala_g",
    "sodium_mg":            "sodium_mg",
    "potassium_mg":         "potassium_mg",
    "calcium_mg":           "calcium_mg",
    "magnesium_mg":         "magnesium_mg",
    "phosphorus_mg":        "phosphorus_mg",
    "iron_mg":              "iron_mg",
    "copper_mg":            "copper_mg",
    "zinc_mg":              "zinc_mg",
    "manganese_mg":         "manganese_mg",
    "selenium_ug":          "selenium_ug",
    "vitamin_a_ug_rae":     "vitamin_a_ug_rae",
    "vitamin_d_ug":         "vitamin_d_ug",
    "vitamin_e_mg":         "vitamin_e_mg",
    "vitamin_k_ug":         "vitamin_k_ug",
    "thiamin_mg":           "thiamin_mg",
    "riboflavin_mg":        "riboflavin_mg",
    "niacin_mg":            "niacin_mg",
    "vitamin_b6_mg":        "vitamin_b6_mg",
    "vitamin_b12_ug":       "vitamin_b12_ug",
    "folate_ug":            "folate_ug",
    "pantothenic_acid_mg":  "pantothenic_acid_mg",
    "vitamin_c_mg":         "vitamin_c_mg",
}

COFID_DB_PATH = None  # Set automatically when found

def find_cofid_db():
    """Find cofid.db in the same folder as this script."""
    import os
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "cofid.db"),
        "cofid.db",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def search_cofid(query: str) -> object:
    """
    Search CoFID database for a food using keyword matching.
    Returns a dict with food info and nutrients per 100g, or None.
    """
    db_path = find_cofid_db()
    if not db_path:
        return None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Try progressively looser matches
    words = [w for w in query.lower().split() if len(w) > 2]
    for num_words in range(len(words), 0, -1):
        combo = " ".join(words[:num_words])
        pattern = "%" + combo.replace(" ", "%") + "%"
        results = conn.execute(
            "SELECT * FROM cofid WHERE LOWER(food_name) LIKE ? LIMIT 5",
            (pattern,)
        ).fetchall()
        if results:
            conn.close()
            row = dict(results[0])
            return row

    conn.close()
    return None

def cofid_to_nutrients(row: dict) -> dict:
    """Convert a CoFID row to our standard nutrient dict."""
    nutrients = {}
    for cofid_col, standard_col in COFID_NUTRIENT_MAP.items():
        val = row.get(cofid_col)
        if val is not None:
            nutrients[standard_col] = val
    return nutrients


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USDA_FOOD_URL   = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"

# Nutrients to capture from USDA (nutrient number → friendly name)
# Extend this list freely — USDA carries 150+ nutrient IDs
NUTRIENT_MAP = {
    # ── New FDC numbering (Foundation, Branded) ──
    "1008": "energy_kcal",
    "2047": "energy_kcal",
    "1003": "protein_g",
    "1004": "fat_total_g",
    "1005": "carbohydrate_g",
    "1079": "fibre_g",
    "2000": "sugars_g",
    "1258": "saturated_fat_g",
    "1292": "monounsaturated_fat_g",
    "1293": "polyunsaturated_fat_g",
    "1087": "calcium_mg",
    "1089": "iron_mg",
    "1090": "magnesium_mg",
    "1091": "phosphorus_mg",
    "1092": "potassium_mg",
    "1093": "sodium_mg",
    "1095": "zinc_mg",
    "1098": "copper_mg",
    "1101": "manganese_mg",
    "1103": "selenium_ug",
    "1106": "vitamin_a_ug_rae",
    "1162": "vitamin_c_mg",
    "1114": "vitamin_d_ug",
    "1109": "vitamin_e_mg",
    "1185": "vitamin_k_ug",
    "1165": "thiamin_mg",
    "1166": "riboflavin_mg",
    "1167": "niacin_mg",
    "1170": "pantothenic_acid_mg",
    "1175": "vitamin_b6_mg",
    "1177": "folate_ug",
    "1178": "vitamin_b12_ug",
    "1180": "choline_mg",
    "1278": "omega3_epa_g",
    "1279": "omega3_dpa_g",
    "1280": "omega3_dha_g",
    "1404": "omega3_ala_g",
    "1257": "trans_fat_g",
    "1210": "tryptophan_g",
    "1211": "threonine_g",
    "1212": "isoleucine_g",
    "1213": "leucine_g",
    "1214": "lysine_g",
    "1215": "methionine_g",
    "1216": "phenylalanine_g",
    "1217": "valine_g",
    "1218": "arginine_g",
    "1220": "glycine_g",
    "1221": "proline_g",
    "1223": "glutamic_acid_g",
    # ── Old SR Legacy numbering ──
    "208": "energy_kcal",
    "203": "protein_g",
    "204": "fat_total_g",
    "205": "carbohydrate_g",
    "291": "fibre_g",
    "269": "sugars_g",
    "606": "saturated_fat_g",
    "645": "monounsaturated_fat_g",
    "646": "polyunsaturated_fat_g",
    "301": "calcium_mg",
    "303": "iron_mg",
    "304": "magnesium_mg",
    "305": "phosphorus_mg",
    "306": "potassium_mg",
    "307": "sodium_mg",
    "309": "zinc_mg",
    "312": "copper_mg",
    "315": "manganese_mg",
    "317": "selenium_ug",
    "320": "vitamin_a_ug_rae",
    "401": "vitamin_c_mg",
    "328": "vitamin_d_ug",
    "323": "vitamin_e_mg",
    "430": "vitamin_k_ug",
    "404": "thiamin_mg",
    "405": "riboflavin_mg",
    "406": "niacin_mg",
    "410": "pantothenic_acid_mg",
    "415": "vitamin_b6_mg",
    "417": "folate_ug",
    "418": "vitamin_b12_ug",
    "421": "choline_mg",
    "619": "omega3_ala_g",
    "629": "omega3_epa_g",
    "631": "omega3_dpa_g",
    "621": "omega3_dha_g",
    "605": "trans_fat_g",
    "501": "tryptophan_g",
    "502": "threonine_g",
    "503": "isoleucine_g",
    "504": "leucine_g",
    "505": "lysine_g",
    "506": "methionine_g",
    "508": "phenylalanine_g",
    "510": "valine_g",
    "511": "arginine_g",
    "514": "glycine_g",
    "517": "proline_g",
    "515": "glutamic_acid_g",
    # ── Old SR Legacy numbering (continued) ──
    # (new FDC numbers already listed above)
    # Omega-3 fatty acids
    "1404": "omega3_ala_g",
    "1278": "omega3_epa_g",
    "1279": "omega3_dpa_g",
    "1280": "omega3_dha_g",
    # Minerals
    "1087": "calcium_mg",
    "1089": "iron_mg",
    "1090": "magnesium_mg",
    "1091": "phosphorus_mg",
    "1092": "potassium_mg",
    "1093": "sodium_mg",
    "1095": "zinc_mg",
    "1098": "copper_mg",
    "1101": "manganese_mg",
    "1103": "selenium_ug",
    # Vitamins
    "1106": "vitamin_a_ug_rae",
    "1162": "vitamin_c_mg",
    "1114": "vitamin_d_ug",
    "1109": "vitamin_e_mg",
    "1185": "vitamin_k_ug",
    "1165": "thiamin_mg",
    "1166": "riboflavin_mg",
    "1167": "niacin_mg",
    "1170": "pantothenic_acid_mg",
    "1175": "vitamin_b6_mg",
    "1177": "folate_ug",
    "1178": "vitamin_b12_ug",
    "1180": "choline_mg",
    # Amino acids (selection)
    "1210": "tryptophan_g",
    "1211": "threonine_g",
    "1212": "isoleucine_g",
    "1213": "leucine_g",
    "1214": "lysine_g",
    "1215": "methionine_g",
    "1216": "phenylalanine_g",
    "1217": "valine_g",
    "1218": "arginine_g",
    "1220": "glycine_g",
    "1221": "proline_g",
    "1223": "glutamic_acid_g",
}

# All nutrient column names (for CREATE TABLE)
NUTRIENT_COLUMNS = list(dict.fromkeys(NUTRIENT_MAP.values()))  # deduplicated


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _build_create_table_sql():
    cols = "\n".join(f"    {col} REAL," for col in NUTRIENT_COLUMNS)
    return f"""
    CREATE TABLE IF NOT EXISTS diet_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        log_date        TEXT NOT NULL,
        meal_time       TEXT,
        meal_category   TEXT,
        food_name_raw   TEXT,
        food_name_usda  TEXT,
        fdc_id          INTEGER,
        quantity_g      REAL,
        unit_original   TEXT,
        usda_match_score REAL,
        logged_at       TEXT NOT NULL,
{cols}
        notes           TEXT
    )
    """


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_build_create_table_sql())
    # Migrate existing databases — add new columns if they don't exist
    existing = {row[1] for row in conn.execute("PRAGMA table_info(diet_log)")}
    for col in ["meal_category"]:
        if col not in existing:
            conn.execute(f"ALTER TABLE diet_log ADD COLUMN {col} TEXT")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Step 1 — Parse diet log with Claude
# ---------------------------------------------------------------------------

PARSE_SYSTEM_PROMPT = """
You are a dietary analysis assistant. The user will provide a free-text diet log
for a day. Extract every food and drink item into a structured JSON array.

For each item output:
{
  "time": "HH:MM or null",
  "meal": "breakfast | lunch | dinner | snack | supplement",
  "food": "concise English food description, suitable for a database search",
  "quantity": <number or null>,
  "unit": "g | ml | tbsp | tsp | cup | oz | slice | piece | handful | etc."
}

Rules:
- Convert household measures to grams where unambiguous (e.g. 1 tbsp olive oil → 14g).
  Keep the original unit in "unit" and put the gram equivalent in "quantity".
- If quantity is genuinely unknown, use null.
- Split composite meals into individual ingredients.
- Beverages (water, tea, coffee without additions) still get an entry.
- Infer meal category from time and context: before 11am = breakfast, 11am-3pm = lunch,
  3pm-6pm = snack, after 6pm = dinner. Pills, powders, capsules = supplement.
- If meal category is explicitly stated, use that.
- Output ONLY the JSON array — no prose, no markdown fences.
"""


CLEAN_QUERY_PROMPT = """
You are a USDA food database search expert. Convert the user's food description
into the best possible search term for the USDA SR Legacy database.

Rules:
- Use generic names, not brand names (e.g. "Warburtons rye bread" → "bread rye")
- Strip container descriptions (e.g. "sardines in tin" → "sardines canned oil")
- Expand abbreviations (e.g. "choc" → "chocolate")
- For plain cooked meats, keep the cooking method but NEVER use "breaded", "battered", "coated", "processed", "tenderloin", "tenders", "nuggets", or any brand names
- For coffee with nothing added, use "coffee brewed"
- For plain tea, use "tea brewed"
- For water, use "water tap"
- Return ONLY the search term — no explanation, no punctuation, just 1-5 words.

Examples:
  "chicken breast grilled" → "chicken breast grilled"
  "chicken thigh cooked" → "chicken thigh cooked"
  "beef mince cooked" → "beef mince cooked"
  "pork chop grilled" → "pork chop grilled"
  "rolled oats porridge" → "oats regular unenriched"
  "whole milk" → "milk fluid whole"
  "black coffee" → "coffee brewed"
  "sardines in olive oil tin" → "sardines canned oil"
  "rye bread slice" → "bread rye"
  "cherry tomatoes" → "tomatoes raw"
  "salmon fillet pan fried" → "salmon cooked dry heat"
  "steamed broccoli" → "broccoli cooked"
  "cooked brown rice" → "rice brown cooked"
  "dark chocolate 85%" → "chocolate dark"
  "olive oil" → "oil olive"
  "greek yoghurt" → "yogurt greek plain"
  "cheddar cheese" → "cheese cheddar"
"""

def clean_food_query(food_name: str, client: anthropic.Anthropic) -> str:
    """Use Claude to convert a raw food description into a clean USDA search term."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        system=CLEAN_QUERY_PROMPT,
        messages=[{"role": "user", "content": food_name}]
    )
    return response.content[0].text.strip().lower()


def parse_diet_log(raw_text: str, client: anthropic.Anthropic) -> list[dict]:
    """Use Claude to convert free-text diet log → list of structured food entries."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=PARSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_text}]
    )
    text = response.content[0].text.strip()
    # Strip any accidental markdown fences
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Step 2 — Match food to USDA FoodData Central
# ---------------------------------------------------------------------------

def search_usda(query: str, usda_key: str) -> object:
    """
    Search USDA FDC for a food. Returns the best match or None.
    Tries SR Legacy first, then Foundation, then Branded Food.
    """
    for data_type in ["SR Legacy", "Foundation", "Branded Food"]:
        params = {
            "query": query,
            "api_key": usda_key,
            "dataType": data_type,
            "pageSize": 3,
        }
        resp = requests.get(USDA_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        foods = resp.json().get("foods", [])
        if foods:
            return foods[0]
    return None


def search_all_databases(query: str, usda_key: str) -> dict:
    """
    Search both USDA and CoFID. Returns:
    {
        "source": "usda" or "cofid",
        "name": food name,
        "match": raw match object,
        "nutrients_100g": dict of nutrients per 100g
    }
    Prefers CoFID for UK foods, USDA as primary fallback.
    Both are tried and the one with more nutrient data wins.
    """
    usda_match = None
    cofid_match = None

    # Try USDA
    try:
        usda_match = search_usda(query, usda_key)
    except Exception:
        pass

    # Try CoFID
    try:
        cofid_match = search_cofid(query)
    except Exception:
        pass

    # Score each match by nutrient completeness
    usda_nutrients = {}
    cofid_nutrients = {}

    if usda_match:
        try:
            usda_nutrients = get_usda_nutrients(usda_match["fdcId"], usda_key)
        except Exception:
            pass

    if cofid_match:
        cofid_nutrients = cofid_to_nutrients(cofid_match)

    # Count meaningful (non-None, non-zero) nutrients for scoring
    def score(d):
        return sum(1 for v in d.values() if v is not None and v != 0.0)

    usda_score  = score(usda_nutrients)
    cofid_score = score(cofid_nutrients)

    # Pick whichever has more populated nutrient values
    # CoFID wins on a tie (UK-specific data preferred)
    if cofid_score >= usda_score and cofid_match:
        return {
            "source": "cofid",
            "name": cofid_match.get("food_name", ""),
            "match": cofid_match,
            "nutrients_100g": cofid_nutrients,
        }
    elif usda_score > 0 and usda_match:
        return {
            "source": "usda",
            "name": usda_match.get("description", ""),
            "match": usda_match,
            "nutrients_100g": usda_nutrients,
        }
    elif cofid_match:
        return {
            "source": "cofid",
            "name": cofid_match.get("food_name", ""),
            "match": cofid_match,
            "nutrients_100g": cofid_nutrients,
        }
    return None


def get_usda_nutrients(fdc_id: int, usda_key: str) -> dict:
    """Fetch full nutrient profile for a specific FDC ID. Returns per-100g values.
    Handles both Foundation food format and SR Legacy format from USDA FDC API."""
    url = USDA_FOOD_URL.format(fdc_id=fdc_id)
    resp = requests.get(url, params={"api_key": usda_key}, timeout=10)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    data = resp.json()

    nutrients_per_100g = {}
    for n in data.get("foodNutrients", []):
        # Try every possible location for the nutrient number across all USDA formats
        num = (
            str(n.get("nutrient", {}).get("number", ""))   # FDC nested format
            or str(n.get("nutrientNumber", ""))             # SR Legacy flat format
            or str(n.get("nutrientId", ""))                 # Foundation flat format
        )
        # Amount field also varies by format
        val = n.get("amount") if n.get("amount") is not None else n.get("value")

        if num and num in NUTRIENT_MAP and val is not None:
            col = NUTRIENT_MAP[num]
            nutrients_per_100g[col] = val

    return nutrients_per_100g


def scale_nutrients(nutrients_per_100g: dict, quantity_g: float) -> dict:
    """Scale per-100g nutrient values to the actual quantity consumed."""
    factor = quantity_g / 100.0
    return {col: round(val * factor, 4) for col, val in nutrients_per_100g.items()}


# ---------------------------------------------------------------------------
# Step 3 — Quantity normalisation helpers
# ---------------------------------------------------------------------------

UNIT_TO_GRAMS = {
    # Volume (approximate for water-density liquids)
    "ml": 1.0, "millilitre": 1.0, "milliliter": 1.0,
    "l": 1000.0, "litre": 1000.0, "liter": 1000.0,
    "cup": 240.0, "tbsp": 15.0, "tablespoon": 15.0,
    "tsp": 5.0, "teaspoon": 5.0, "fl oz": 30.0,
    # Weight
    "g": 1.0, "gram": 1.0, "grams": 1.0,
    "kg": 1000.0, "kilogram": 1000.0,
    "oz": 28.35, "ounce": 28.35,
    "lb": 453.6, "pound": 453.6,
    # Loose measures (sensible defaults)
    "slice": 30.0,      # bread slice
    "piece": 50.0,
    "handful": 30.0,
    "portion": 100.0,
    "tin": 120.0,       # drained tin of fish
    "can": 120.0,
}

def to_grams(quantity, unit: str) -> object:
    """Convert a quantity + unit to grams. Returns None if conversion unknown."""
    if quantity is None:
        return None
    unit_clean = str(unit).lower().strip()
    factor = UNIT_TO_GRAMS.get(unit_clean)
    if factor is None:
        return None
    return round(float(quantity) * factor, 2)


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class NutritionLogger:

    def __init__(self, anthropic_key: str, usda_key: str, db_path: str = "nutrition_log.db"):
        self.client   = anthropic.Anthropic(api_key=anthropic_key)
        self.usda_key = usda_key
        self.db_path  = db_path
        self.conn     = init_db(db_path)

    # ------------------------------------------------------------------ #
    # Public: log a diet entry                                             #
    # ------------------------------------------------------------------ #

    def log_diet_entry(self, raw_text: str, log_date = None) -> list[dict]:
        """
        Parse raw diet text, look up each food in USDA, and insert rows into the DB.
        Returns a list of result dicts (one per food item).

        log_date : ISO date string "YYYY-MM-DD" — defaults to today.
        """
        if log_date is None:
            log_date = datetime.date.today().isoformat()

        logged_at = datetime.datetime.now().isoformat()

        print(f"\n── Parsing diet log for {log_date} ──")
        parsed_items = parse_diet_log(raw_text, self.client)
        print(f"   Found {len(parsed_items)} food items")

        results = []
        for item in parsed_items:
            food_name_raw = item.get("food", "")
            meal_time     = item.get("time")
            meal_category = item.get("meal")
            quantity      = item.get("quantity")
            unit          = item.get("unit", "g")

            quantity_g = to_grams(quantity, unit)

            print(f"\n   → {food_name_raw} | {quantity}{unit} ({quantity_g}g)")

            # Clean the food name into a USDA-friendly search term
            search_term = clean_food_query(food_name_raw, self.client)
            print(f"     \u27f3 Search term: '{search_term}'")

            # Search USDA + CoFID, pick best match
            result = search_all_databases(search_term, self.usda_key)
            if result is None:
                print(f"     \u26a0 No match found in any database \u2014 logged with nulls")
                row = self._build_row(
                    log_date, meal_time, meal_category, food_name_raw,
                    None, None, quantity_g, unit, None, {}, logged_at
                )
                self._insert_row(row)
                results.append({"item": item, "match": None, "row": row})
                continue

            source         = result["source"]
            food_name_usda = result["name"]
            fdc_id         = result["match"].get("fdcId") if source == "usda" else None
            score          = result["match"].get("score") if source == "usda" else None
            nutrients_per_100g = result["nutrients_100g"]
            print(f"     \u2713 [{source.upper()}] {food_name_usda}")

            nutrients_scaled = scale_nutrients(nutrients_per_100g, quantity_g) \
                               if quantity_g else nutrients_per_100g

            row = self._build_row(
                log_date, meal_time, meal_category, food_name_raw,
                food_name_usda, fdc_id, quantity_g, unit, score,
                nutrients_scaled, logged_at
            )
            self._insert_row(row)
            results.append({"item": item, "match": result, "row": row})

        print(f"\n── Logged {len(results)} items to {self.db_path} ──\n")
        return results

    # ------------------------------------------------------------------ #
    # Public: query the log                                                #
    # ------------------------------------------------------------------ #

    def query(self, prompt: str, log_date = None) -> str:
        """
        Answer a natural-language question about the diet log.
        Fetches all rows for log_date (default: today) and passes to Claude.
        """
        if log_date is None:
            log_date = datetime.date.today().isoformat()

        rows = self._fetch_rows(log_date)
        if not rows:
            return f"No diet log entries found for {log_date}."

        # Serialise to compact JSON for the prompt context
        data_json = json.dumps(rows, indent=2)

        system = (
            "You are a clinical nutrition analyst. You will be given a JSON array of "
            "food log entries for a single day. Each entry includes the food name, "
            "meal time, quantity in grams, and scaled nutrient values. "
            "Answer the user's question precisely, citing foods and numeric values "
            "where relevant. If a nutrient value is missing (null), say so. "
            "Use UK English."
        )
        user = f"Diet log for {log_date}:\n\n{data_json}\n\nQuestion: {prompt}"

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        return response.content[0].text

    # ------------------------------------------------------------------ #
    # Public: daily summary                                                #
    # ------------------------------------------------------------------ #

    def daily_summary(self, log_date = None) -> dict:
        """
        Return summed totals for key nutrients across all entries for log_date.
        """
        if log_date is None:
            log_date = datetime.date.today().isoformat()

        key_nutrients = [
            "energy_kcal", "protein_g", "fat_total_g", "carbohydrate_g",
            "fibre_g", "sugars_g", "saturated_fat_g",
            "omega3_epa_g", "omega3_dha_g",
            "calcium_mg", "iron_mg", "magnesium_mg", "zinc_mg",
            "vitamin_d_ug", "vitamin_b12_ug", "folate_ug", "vitamin_c_mg",
        ]
        cols = ", ".join(f"SUM({c}) as {c}" for c in key_nutrients)
        sql  = f"SELECT {cols} FROM diet_log WHERE log_date = ?"
        row  = self.conn.execute(sql, (log_date,)).fetchone()
        return {k: round(v, 2) if v is not None else None for k, v in dict(row).items()}

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_row(self, log_date, meal_time, meal_category, food_name_raw,
                   food_name_usda, fdc_id, quantity_g, unit,
                   score, nutrients: dict, logged_at) -> dict:
        row = {
            "log_date":        log_date,
            "meal_time":       meal_time,
            "meal_category":   meal_category,
            "food_name_raw":   food_name_raw,
            "food_name_usda":  food_name_usda,
            "fdc_id":          fdc_id,
            "quantity_g":      quantity_g,
            "unit_original":   unit,
            "usda_match_score": score,
            "logged_at":       logged_at,
            "notes":           None,
        }
        for col in NUTRIENT_COLUMNS:
            row[col] = nutrients.get(col)
        return row

    def _insert_row(self, row: dict):
        cols   = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        sql    = f"INSERT INTO diet_log ({cols}) VALUES ({placeholders})"
        self.conn.execute(sql, list(row.values()))
        self.conn.commit()

    def _fetch_rows(self, log_date: str) -> list[dict]:
        sql  = "SELECT * FROM diet_log WHERE log_date = ? ORDER BY meal_time"
        rows = self.conn.execute(sql, (log_date,)).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Example usage (run this file directly to test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    logger = NutritionLogger(
        anthropic_key = os.environ["ANTHROPIC_API_KEY"],
        usda_key      = os.environ["USDA_API_KEY"],
        db_path       = "nutrition_log.db",
    )

    # ── Log a sample day ──
    sample_log = """
        8am - porridge made with 80g oats and 250ml whole milk, black coffee
        1pm - tin of sardines in olive oil (120g drained), 2 slices rye bread (~60g each),
              handful of cherry tomatoes (~100g)
        4pm - 30g dark chocolate 85%, green tea
        7pm - 200g salmon fillet pan-fried in olive oil (1 tbsp),
              steamed broccoli 150g, brown rice 180g cooked
    """

    logger.log_diet_entry(sample_log, log_date="2025-05-08")

    # ── Daily totals ──
    print("\nDaily summary:")
    summary = logger.daily_summary("2025-05-08")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # ── Natural language queries ──
    questions = [
        "What was my total protein intake today?",
        "Which meal contributed the most omega-3 EPA and DHA?",
        "How does my magnesium intake compare to the RDA of 375mg?",
        "What was my estimated calcium intake and which foods contributed most?",
    ]
    for q in questions:
        print(f"\nQ: {q}")
        print(logger.query(q, log_date="2025-05-08"))

    logger.close()
