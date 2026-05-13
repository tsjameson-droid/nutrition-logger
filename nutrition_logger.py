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

# Curated lookup table: common food descriptions → CoFID food_code
# Checked against CoFID 2021 — use shortest/simplest name where possible
COFID_LOOKUP = {
    # Dairy
    "whole milk":              "12-596",  # Milk, whole, pasteurised, average
    "semi skimmed milk":       "12-313",  # Milk, semi-skimmed, pasteurised, average
    "skimmed milk":            "12-310",  # Milk, skimmed, pasteurised, average
    "full fat milk":           "12-596",
    "butter":                  "17-685",  # Butter, salted
    "unsalted butter":         "17-661",
    "cheddar":                 "12-346",  # Cheese, Cheddar, English
    "cheddar cheese":          "12-346",
    "greek yoghurt":           "12-555",  # Yogurt, Greek style, plain
    "greek yogurt":            "12-555",
    "plain yoghurt":           "12-371",  # Yogurt, plain, whole milk
    "cream cheese":            "12-349",
    "double cream":            "12-330",
    "single cream":            "12-328",
    # Eggs
    "eggs scrambled":          "12-963",  # Eggs, chicken, whole, scrambled, without milk
    "scrambled eggs":          "12-963",
    "boiled egg":              "12-940",  # Eggs, chicken, whole, boiled
    "fried egg":               "12-947",  # Eggs, chicken, whole, fried
    "poached egg":             "12-950",  # Eggs, chicken, whole, poached
    "raw egg":                 "12-931",  # Eggs, chicken, whole, raw, value
    # Grains
    "oats":                    "11-788",  # Porridge oats, unfortified
    "rolled oats":             "11-788",
    "porridge oats":           "11-788",
    "white bread":             "11-980",  # Bread, white, sliced
    "wholemeal bread":         "11-981",  # Bread, wholemeal, average
    "brown bread":             "11-983",  # Bread, brown, average
    "rye bread":               "11-984",  # Bread, rye, average
    "white rice cooked":       "11-862",  # Rice, white, long grain, boiled
    "rice white cooked":       "11-862",
    "basmati rice cooked":     "11-858",  # Rice, white, basmati, boiled
    "brown rice cooked":       "11-869",  # Rice, brown, wholegrain, boiled
    "rice brown cooked":       "11-869",
    "pasta cooked":            "11-1129", # Pasta, white, dried, boiled
    "pasta white cooked":      "11-1129",
    "pasta wholemeal cooked":  "11-723",  # Pasta, wholewheat, boiled
    "couscous cooked":         "11-804",  # Couscous, cooked
    "quinoa cooked":           "11-819",  # Quinoa, cooked
    # Meat
    "chicken breast grilled":  "18-323",  # Chicken, breast, grilled without skin, meat only
    "chicken breast raw":      "18-100",  # Chicken, breast, raw, meat only
    "chicken breast baked":    "18-323",
    "chicken thigh grilled":   "18-331",  # Chicken, thigh, grilled, meat only
    "beef mince cooked":       "18-470",  # Beef, mince, stewed
    "beef mince raw":          "18-469",
    "beef mince":              "18-470",
    "salmon raw":              "16-356",  # Salmon, farmed, flesh only, raw
    "salmon fillet raw":       "16-356",
    "salmon baked":            "16-359",  # Salmon, farmed, flesh only, baked
    "salmon grilled":          "16-359",
    "salmon fillet":           "16-359",
    "tuna canned brine":       "16-416",  # Tuna, canned in brine, drained
    "tuna canned":             "16-416",
    "tuna canned oil":         "16-417",  # Tuna, canned in sunflower oil, drained
    "sardines canned oil":     "16-440",  # Sardines, canned in olive oil, drained
    "sardines canned":         "16-424",  # Sardines, canned in brine, drained
    "cod baked":               "16-175",  # Cod, baked
    "cod raw":                 "16-168",
    "mackerel grilled":        "16-241",  # Mackerel, grilled
    # Vegetables
    "broccoli raw":            "13-502",  # Broccoli, green, raw
    "broccoli cooked":         "13-503",  # Broccoli, green, boiled
    "spinach raw":             "13-521",  # Spinach, baby, raw
    "spinach cooked":          "13-524",  # Spinach, boiled
    "sweet potato raw":        "13-463",  # Sweet potato, raw, flesh only
    "sweet potato baked":      "13-464",  # Sweet potato, baked
    "sweet potato cooked":     "13-465",  # Sweet potato, boiled
    "cherry tomatoes":         "13-477",  # Tomatoes, cherry, raw
    "tomatoes raw":            "13-474",  # Tomatoes, raw
    "avocado":                 "14-386",  # Avocado, Hass, flesh only
    "cucumber":                "13-488",
    "carrots raw":             "13-484",
    "carrots cooked":          "13-485",
    "onion raw":               "13-493",
    "garlic":                  "13-491",
    "mushrooms raw":           "13-492",
    "mushrooms cooked":        "13-490",
    "kale raw":                "13-505",
    "peppers raw":             "13-496",
    "courgette raw":           "13-487",
    # Fruit
    "banana":                  "14-318",  # Bananas, flesh only
    "apple":                   "14-319",  # Apples, eating, raw, flesh and skin
    "blueberries":             "14-325",
    "strawberries":            "14-330",
    "raspberries":             "14-328",
    "orange":                  "14-370",
    "mango":                   "14-351",
    "grapes":                  "14-340",
    # Legumes
    "chickpeas cooked":        "13-662",  # Beans, chick peas, boiled
    "chickpeas":               "13-662",
    "lentils cooked":          "13-658",  # Lentils, red, split, boiled
    "red lentils cooked":      "13-658",
    "kidney beans cooked":     "13-657",
        "edamame":                 "13-649",
    # Nuts & seeds
    "almonds":                 "14-870",  # Almonds, flaked and ground
    "walnuts":                 "14-879",  # Walnuts, kernel only
    "cashews":                 "14-874",
    "peanuts":                 "14-876",
    "pumpkin seeds":           "14-884",
    "sunflower seeds":         "14-886",
    "chia seeds":              "14-893",
    "flaxseed":                "14-882",
    # Fats & oils
    "olive oil":               "17-038",
    "coconut oil":             "17-031",
    "rapeseed oil":            "17-040",
    "sunflower oil":           "17-043",
    # Other

    # ── Personalised lookup (built from 3 years of dietary diary) ──────────────
    # Oils
    "extra virgin olive oil":       "17-038",
    "olive oil":                    "17-038",
    # Grains & noodles
    "rice white long grain cooked": "11-862",
        "quinoa cooked":                "11-819",
    "buckwheat cooked":             "11-820",
    "millet cooked":                "11-821",
    "buckwheat dry":                "11-022",
    "sourdough bread":              "11-981",  # use wholemeal as proxy
    # Vegetables
    "aubergine cooked":             "13-651",  # Aubergine, flesh and skin, boiled
    "aubergine boiled":             "13-651",
    "eggplant cooked":              "13-651",
    "green beans cooked":           "13-654",  # Beans, runner, boiled
    "green bean boiled":            "13-654",
    "spinach cooked":               "13-550",  # Spinach, baby, boiled
    "courgette cooked":             "13-628",  # Courgette, boiled
    "zucchini cooked":              "13-628",
    "tomato cooked":                "13-479",  # Tomatoes, stewed
    "tomato boiled":                "13-479",  # Tomatoes, stewed
    "tomato raw":                   "13-517",  # Tomatoes, standard, raw
    "cherry tomatoes":              "13-519",
    "okra cooked":                  "13-652",
    "pumpkin cooked":               "13-549",
    "cauliflower cooked":           "13-513",
    "cabbage green cooked":         "13-511",
    "cabbage red cooked":           "13-540",
    "kale cooked":                  "13-649",
    "bok choy cooked":              "13-516",  # Pak choi, steamed
    "pak choi cooked":              "13-516",
    "butternut squash":             "13-644",
    "butternut squash baked":       "13-644",
    "celeriac cooked":              "13-585",
    "cucumber raw":                 "13-523",
    "avocado":                      "14-386",
    "peach raw":                    "14-299",
    "shiitake cooked":              "13-295",
    "maitake raw":                  "13-294",  # closest mushroom
    # Eggs
    "egg raw":                      "12-937",  # Eggs, chicken, whole, raw
    "egg whole raw":                "12-937",
    "duck egg":                     "12-920",  # Eggs, duck, whole, raw
    "duck eggs":                    "12-920",
    "egg white cooked":             "12-941",  # Eggs, chicken, white, boiled
    "egg scrambled":                "12-963",
    # Dairy
    "whole milk":                   "12-596",
    "a2 whole milk":                "12-596",
    "goat cheese soft":             "12-357",
    "goat cheese":                  "12-357",
    # Nuts & seeds
    "walnuts":                      "14-879",
    "almonds raw":                  "14-896",  # Almonds, whole kernels
    "almonds":                      "14-896",
    "macadamia nuts raw":           "14-891",
    "macadamia nuts":               "14-891",
    "cashews raw":                  "14-811",
    "cashews":                      "14-811",
    # Legumes
    "lentils boiled":               "13-658",  # Lentils, red, split, boiled
    "lentils cooked":               "13-658",
    "white beans boiled":           "13-087",
        "kidney beans":                 "13-659",  # Beans, red kidney, boiled
    "adzuki beans":                 "13-655",  # Beans, adzuki, boiled
    # Protein & meat
    "chicken breast skinless cooked": "18-323",  # Chicken, breast, grilled without skin
    "chicken breast cooked":          "18-323",
    "chicken thigh skin removed":     "18-331",  # Chicken thigh, grilled meat only
    # Starches
    "potato boiled":                "13-605",  # Potatoes, old, boiled, flesh only
    "potato baked":                 "13-620",  # Potatoes, old, baked, flesh only
    "potatoes baked flesh and skin": "13-491",  # Potatoes, old, baked, flesh and skin
    "sweet potato baked":           "13-672",
    "sweet potato boiled":          "13-646",  # Sweet potato, flesh only, boiled
    # Bread
    "white bread":                  "11-980",
    # Other
    "honey":                        "17-050",
    # ── Exact search terms from validation (Claude-generated) ──────────────────
    # These keys match EXACTLY what Claude generates as search terms
    "mushrooms cooked":             "13-505",  # Mushrooms, white, raw (closest in CoFID)
    "carrots cooked":               "13-497",  # Carrots, old, boiled
    "asparagus cooked":             "13-638",  # Asparagus, steamed
    "oil olive":                    "17-038",   # Claude generates this for olive oil
    "oil extra virgin olive":       "17-038",
    "egg raw whole":                "12-937",   # Whole egg raw
    "egg chicken raw":              "12-937",
    "broccoli green boiled":        "13-503",   # Regular broccoli boiled
    "broccoli fresh cooked":        "13-503",
    "broccoli cooked fresh":        "13-503",
    "courgette boiled":             "13-628",
    "courgette fresh cooked":       "13-628",
    "aubergine boiled":             "13-651",
    "aubergine fresh cooked":       "13-651",
    "chicken breast skinless":      "18-323",
    "chicken breast skinless cooked":"18-323",
    "beans black boiled":           "13-063",  # Beans, blackeye - closest to black beans in CoFID
    "black beans boiled":           "13-063",
    "black beans canned":           "13-063",
    "beans black canned":           "13-063",
    "mushrooms common boiled":      "13-505",  # Mushrooms, white, raw
    "mushroom fresh cooked":        "13-505",
    "mushrooms fresh cooked":       "13-505",
    "cauliflower boiled":           "13-513",
    "cauliflower fresh cooked":     "13-513",
        "rice white long grain":        "11-862",
    "rice white enriched cooked":   "11-862",
    "salad tossed":                 "15-648",
    "salad mixed greens":           "15-648",
    "salad mixed greens dressing":  "15-648",
    "red wine":                     "17-752",
    "cod liver oil":                "17-488",
    "hazelnut butter":              "14-874",
    "cashew butter":                "14-811",
    "hummus":                       "13-556",
    "houmous":                      "13-556",
    "fennel raw":                   "13-241",
    "fennel bulb raw":              "13-241",
    "swiss chard cooked":           "13-224",
    "chard cooked":                 "13-224",
    "artichoke cooked":             "13-154",
    "globe artichoke":              "13-154",
    "red pepper raw":               "13-524",
    "red bell pepper raw":          "13-524",
    "garlic raw":                   "13-491",
    "courgette raw":                "13-627",
    "zucchini raw":                 "13-627",
    "tossed salad":                 "15-648",
    "green salad":                  "15-648",
    "asparagus cooked":             "13-591",
    
    "mushrooms cooked":             "13-297",
    "mushroom boiled":              "13-297",
    "cauliflower cooked":           "13-513",
    "cauliflower boiled":           "13-513",
    "pesto":                        "15-838",
    "lentil soup":                  "17-808",
    "tossed salad with dressing":   "15-648",
    "honey":                   "17-118",
    "sugar":                   "17-079",
    "soy sauce":               "17-150",
    "tomato puree":            "13-480",
}

def search_cofid(query: str) -> object:
    """
    Search CoFID database. First tries curated lookup table,
    then falls back to word-order-independent fuzzy search.
    """
    db_path = find_cofid_db()
    if not db_path:
        return None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 1. Try curated lookup table (exact and partial key matches)
    query_lower = query.lower().strip()
    # Try progressively shorter versions of the query
    for length in range(len(query_lower.split()), 0, -1):
        partial = " ".join(query_lower.split()[:length])
        if partial in COFID_LOOKUP:
            food_code = COFID_LOOKUP[partial]
            result = conn.execute(
                "SELECT * FROM cofid WHERE food_code = ?", (food_code,)
            ).fetchone()
            if result:
                conn.close()
                return dict(result)

    # 2. Word-order-independent search (all words must appear)
    words = [w for w in query_lower.split() if len(w) > 2]
    if words:
        for num_words in range(len(words), 0, -1):
            subset = words[:num_words]
            conditions = " AND ".join(
                [f"LOWER(food_name) LIKE ?" for _ in subset]
            )
            params = [f"%{w}%" for w in subset]
            results = conn.execute(
                f"SELECT * FROM cofid WHERE {conditions} ORDER BY LENGTH(food_name) LIMIT 3",
                params
            ).fetchall()
            if results:
                conn.close()
                return dict(results[0])

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
You are a food database search assistant. Your job is to convert a food description
from a diet diary into a clean, accurate search term for a food composition database.

Rules:
1. ALWAYS keep the core food name — if the diary says "carrots", search for "carrots"
2. Keep the cooking method if relevant (e.g. "carrots boiled", "chicken grilled")
3. Strip brand names, container types, and irrelevant qualifiers
4. Strip filler words like "from fresh", "homemade", "a portion of"
5. For plain meats, use the cut + cooking method ONLY — never add "breaded", "coated", "processed"
6. For whole eggs, always say "egg whole" not just "egg white" or "egg yolk"
7. For coffee black, use "coffee"
8. For olive oil, use "olive oil" (not "oil olive")
9. Return ONLY the search term — 1-4 words, no punctuation, no explanation

Examples:
  "carrots, cooked from fresh" → "carrots boiled"
  "broccoli, cooked from fresh" → "broccoli boiled"
  "mushrooms, cooked from fresh" → "mushrooms boiled"
  "asparagus, cooked from fresh" → "asparagus boiled"
  "cauliflower, cooked from fresh" → "cauliflower boiled"
  "courgette, cooked from fresh" → "courgette boiled"
  "aubergine, cooked" → "aubergine boiled"
  "spinach, cooked from fresh" → "spinach boiled"
  "zucchini, cooked from fresh" → "courgette boiled"
  "chicken breast, skinless, cooked" → "chicken breast grilled"
  "chicken breast grilled" → "chicken breast grilled"
  "egg, raw" → "egg whole raw"
  "egg, whole, cooked, scrambled" → "egg scrambled"
  "extra virgin olive oil" → "olive oil"
  "rice, white, long-grain, regular, enriched, cooked" → "rice white cooked"
  "tossed salad, plain, with dressing" → "salad green"
  "chocolate, dark, 70-85% cacao" → "chocolate dark"
  "sweet potato, baked" → "sweet potato baked"
  "black beans, canned, drained" → "black beans"
  "soba noodles, buckwheat based, cooked" → "soba noodles cooked"
  "walnuts" → "walnuts"
  "almonds, raw" → "almonds raw"
  "salmon fillet, pan fried" → "salmon grilled"
  "whole milk" → "whole milk"
  "greek yoghurt, full fat" → "greek yoghurt"
"""

VALIDATE_PROMPT = """
You are checking whether a food database search term correctly represents
a food item from a diet diary.

Given the original food name and the proposed search term, reply with:
- The search term if it is correct and will find the right food
- A corrected search term if the proposed one is wrong or misleading

Rules for a GOOD search term:
- Contains the core food name from the diary entry
- If diary says "carrots" the search must include "carrot"
- If diary says "mushrooms" the search must include "mushroom"
- If diary says "asparagus" the search must include "asparagus"
- Cooking method is preserved if present
- No brand names, no filler words
- 1-4 words only

Reply with ONLY the final search term — no explanation.
"""

def clean_food_query(food_name: str, client: anthropic.Anthropic) -> str:
    """
    Two-step process:
    1. Claude generates a search term from the food description
    2. Claude validates the search term actually matches the food
    Returns the validated search term.
    """
    # Step 1: Generate search term
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        system=CLEAN_QUERY_PROMPT,
        messages=[{"role": "user", "content": food_name}]
    )
    search_term = response.content[0].text.strip().lower()

    # Step 2: Validate — quick sanity check
    # Extract the core food word(s) from the original name
    # If none of the core words appear in the search term, ask Claude to fix it
    core_words = [w.lower() for w in food_name.replace(",", " ").split()
                  if len(w) > 3 and w.lower() not in {
                      "cooked", "fresh", "from", "with", "without", "plain",
                      "drained", "canned", "based", "boiled", "baked", "fried",
                      "grilled", "steamed", "roasted", "homemade", "regular",
                      "enriched", "long-grain", "skinless", "boneless", "whole",
                      "organic", "natural", "unsalted", "salted", "dried"
                  }][:2]

    term_words = search_term.lower().split()
    match_found = any(
        any(cw in tw or tw in cw for tw in term_words)
        for cw in core_words
    )

    if not match_found and core_words:
        # Search term doesn't contain the core food — ask Claude to validate
        validate_response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            system=VALIDATE_PROMPT,
            messages=[{"role": "user", "content": f"Diary entry: {food_name}\nProposed search term: {search_term}"}]
        )
        corrected = validate_response.content[0].text.strip().lower()
        return corrected

    return search_term


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


PICK_MATCH_PROMPT = """
You are a food matching expert. A user has logged a food item in their diet diary.
You will be given the original diary entry and a list of candidate matches from
food composition databases (USDA and CoFID).

Your job: pick the single best match, or say NONE if nothing is close enough.

Rules:
- The match must be the same food as the diary entry — not a different food with
  a similar name
- Prefer plain/generic versions over branded, processed, or composite dishes
- Prefer the cooking method stated in the diary (raw, boiled, grilled, baked etc.)
- If the diary says "carrots boiled", a match called "Carrots, old, boiled in
  unsalted water" is correct; "Carrot cake" or "Carrot soup" is not
- If no candidate is clearly the right food, reply NONE

Reply with ONLY the candidate number (1, 2, 3...) or NONE.
No explanation. Just the number or NONE.
"""

def pick_best_match(original_food: str, candidates: list, client) -> object:
    """
    Ask Claude to pick the best match from a list of candidates.
    candidates: list of dicts with keys: number, name, source
    Returns the chosen candidate dict or None.
    """
    if not candidates:
        return None

    lines = [f"Diary entry: {original_food}", "", "Candidates:"]
    for c in candidates:
        lines.append(f"  {c['number']}. [{c['source']}] {c['name']}")

    prompt = "\n".join(lines)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
        system=PICK_MATCH_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    reply = response.content[0].text.strip().upper()

    if reply == "NONE":
        return None
    try:
        num = int(reply)
        chosen = next((c for c in candidates if c["number"] == num), None)
        return chosen
    except (ValueError, StopIteration):
        return None


def get_candidates(query: str, usda_key: str, n: int = 5) -> list:
    """
    Gather up to n candidates from both USDA and CoFID.
    Returns list of dicts: {number, source, name, match, nutrients_100g}
    """
    candidates = []
    num = 1

    # USDA candidates
    for data_type in ["SR Legacy", "Foundation"]:
        try:
            params = {
                "query": query,
                "api_key": usda_key,
                "dataType": data_type,
                "pageSize": 3,
            }
            resp = requests.get(USDA_SEARCH_URL, params=params, timeout=10)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            foods = resp.json().get("foods", [])
            for food in foods[:2]:
                candidates.append({
                    "number": num,
                    "source": "USDA",
                    "name": food["description"],
                    "match": food,
                    "fdc_id": food["fdcId"],
                    "nutrients_100g": None,  # fetched later if chosen
                })
                num += 1
                if num > n:
                    break
        except Exception:
            pass
        if num > n:
            break

    # CoFID candidates (word-order-independent search)
    db_path = find_cofid_db()
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            words = [w for w in query.lower().split() if len(w) > 2]
            for num_words in range(len(words), 0, -1):
                subset = words[:num_words]
                conditions = " AND ".join(
                    [f"LOWER(food_name) LIKE ?" for _ in subset]
                )
                params = [f"%{w}%" for w in subset]
                results = conn.execute(
                    f"SELECT * FROM cofid WHERE {conditions} ORDER BY LENGTH(food_name) LIMIT 3",
                    params
                ).fetchall()
                if results:
                    for row in results[:2]:
                        row = dict(row)
                        candidates.append({
                            "number": num,
                            "source": "CoFID",
                            "name": row["food_name"],
                            "match": row,
                            "fdc_id": None,
                            "nutrients_100g": None,
                        })
                        num += 1
                    break
            conn.close()
        except Exception:
            pass

    return candidates


def search_all_databases(query: str, usda_key: str, original_food: str = None,
                         client=None) -> dict:
    """
    Claude-picks architecture:
    1. Check curated lookup table — if found, trust it unconditionally
    2. Otherwise gather top candidates from USDA + CoFID
    3. Claude picks the best match (or NONE)
    4. Fetch full nutrients for the chosen match

    original_food: the raw diary entry (used by Claude to make the right pick)
    client: Anthropic client (required for Claude-picks)
    """
    query_lower = query.lower().strip()

    # ── 1. Curated lookup ─────────────────────────────────────────────────────
    for length in range(len(query_lower.split()), 0, -1):
        partial = " ".join(query_lower.split()[:length])
        if partial in COFID_LOOKUP:
            db_path = find_cofid_db()
            if db_path:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                food_code = COFID_LOOKUP[partial]
                row = conn.execute(
                    "SELECT * FROM cofid WHERE food_code = ?", (food_code,)
                ).fetchone()
                conn.close()
                if row:
                    row = dict(row)
                    nutrients = cofid_to_nutrients(row)
                    if nutrients:
                        return {
                            "source": "cofid",
                            "name": row.get("food_name", ""),
                            "match": row,
                            "nutrients_100g": nutrients,
                        }

    # ── 2. Gather candidates ──────────────────────────────────────────────────
    candidates = get_candidates(query, usda_key)
    if not candidates:
        return None

    # ── 3. Claude picks ───────────────────────────────────────────────────────
    food_label = original_food or query
    if client:
        chosen = pick_best_match(food_label, candidates, client)
    else:
        chosen = candidates[0]  # fallback if no client

    if chosen is None:
        return None

    # ── 4. Fetch full nutrients for chosen match ───────────────────────────────
    if chosen["source"] == "USDA":
        try:
            nutrients = get_usda_nutrients(chosen["fdc_id"], usda_key)
        except Exception:
            nutrients = {}
        return {
            "source": "usda",
            "name": chosen["name"],
            "match": chosen["match"],
            "nutrients_100g": nutrients,
        }
    else:
        nutrients = cofid_to_nutrients(chosen["match"])
        return {
            "source": "cofid",
            "name": chosen["name"],
            "match": chosen["match"],
            "nutrients_100g": nutrients,
        }


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

            # Search USDA + CoFID — Claude picks best match
            result = search_all_databases(
                search_term, self.usda_key,
                original_food=food_name_raw,
                client=self.client
            )
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
