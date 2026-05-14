"""
log_today.py
=============
Log your diet and manage recipes. Run: python3 log_today.py
"""

from nutrition_logger import (
    NutritionLogger,
    transcribe_image_file,
    transcribe_handwritten_pdf,
    is_scanned_pdf,
    search_all_databases,
    scale_nutrients,
    clean_food_query,
    to_grams
)
import config, datetime, sys, os, re, sqlite3, json

TODAY = datetime.date.today().isoformat()

logger = NutritionLogger(
    anthropic_key = config.ANTHROPIC_KEY,
    usda_key      = config.USDA_KEY,
    db_path       = "nutrition_log.db"
)

def read_digital_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()

MEALS = ["breakfast", "lunch", "dinner", "snack", "supplement"]

KEY_NUTRIENTS = [
    ("energy_kcal","kcal"),("protein_g","g"),("fat_total_g","g"),
    ("saturated_fat_g","g"),("carbohydrate_g","g"),("fibre_g","g"),
    ("sugars_g","g"),("calcium_mg","mg"),("iron_mg","mg"),
    ("magnesium_mg","mg"),("potassium_mg","mg"),("sodium_mg","mg"),
    ("zinc_mg","mg"),("selenium_ug","ug"),("vitamin_a_ug_rae","ug"),
    ("vitamin_c_mg","mg"),("vitamin_d_ug","ug"),("vitamin_b6_mg","mg"),
    ("vitamin_b12_ug","ug"),("folate_ug","ug"),("omega3_ala_g","g"),
    ("omega3_epa_g","g"),("omega3_dha_g","g"),
]

# ── Recipe helpers ────────────────────────────────────────────────────────────

RECIPES_DB = "recipes.db"

def init_recipes_db():
    conn = sqlite3.connect(RECIPES_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL, description TEXT,
        servings REAL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS recipe_ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL,
        food_name TEXT NOT NULL, quantity_g REAL NOT NULL,
        usda_match TEXT, db_source TEXT, nutrients TEXT,
        FOREIGN KEY (recipe_id) REFERENCES recipes(id))""")
    conn.commit()
    return conn

def save_recipe():
    conn = init_recipes_db()
    conn.row_factory = sqlite3.Row
    print("\nSave a new recipe")
    print("-" * 40)
    name = input("Recipe name: ").strip()
    if not name:
        print("No name entered.")
        conn.close()
        return
    existing = conn.execute("SELECT id FROM recipes WHERE LOWER(name)=?", (name.lower(),)).fetchone()
    if existing:
        ow = input("Recipe already exists. Overwrite? (y/n): ").strip().lower()
        if ow != "y":
            conn.close()
            return
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (existing[0],))
        conn.execute("DELETE FROM recipes WHERE id=?", (existing[0],))
        conn.commit()
    description = input("Description (optional, press Enter to skip): ").strip()
    while True:
        s = input("How many servings does this make? [1]: ").strip()
        if not s:
            servings = 1.0
            break
        try:
            servings = float(s)
            break
        except ValueError:
            print("  Please enter a number e.g. 1 or 2")
    print("\nEnter each ingredient one per line (e.g. 'oats 80g')")
    print("Type END when finished.\n")
    raw = []
    while True:
        line = input("  > ").strip()
        if line.upper() == "END":
            break
        if not line:
            continue
        m = re.search(r"([0-9.]+)\s*(g|ml|kg|oz|lb|tbsp|tsp|cup|slice|piece|handful|tin|can)?", line, re.IGNORECASE)
        if m:
            qty_g = to_grams(float(m.group(1)), (m.group(2) or "g").lower()) or float(m.group(1))
            food = (line[:m.start()] + " " + line[m.end():]).strip()
        else:
            food = line
            qty_g = 100.0
        raw.append((food, qty_g))
        print("  Added: " + food + " (" + str(qty_g) + "g)")
    if not raw:
        print("No ingredients entered.")
        conn.close()
        return
    print("\nLooking up " + str(len(raw)) + " ingredients...")
    now = datetime.datetime.now().isoformat()
    cursor = conn.execute(
        "INSERT INTO recipes (name,description,servings,created_at,updated_at) VALUES (?,?,?,?,?)",
        (name, description, servings, now, now))
    recipe_id = cursor.lastrowid
    for food, qty_g in raw:
        term = clean_food_query(food, logger.client)
        result = search_all_databases(term, config.USDA_KEY, original_food=food, client=logger.client)
        if result:
            nutrients = scale_nutrients(result["nutrients_100g"], qty_g)
            usda_match = result["name"]
            db_source = result["source"]
            print("  ✓ [" + db_source.upper() + "] " + food + " → " + usda_match)
        else:
            nutrients = {}
            usda_match = None
            db_source = None
            print("  ✗ No match: " + food)
        conn.execute(
            "INSERT INTO recipe_ingredients (recipe_id,food_name,quantity_g,usda_match,db_source,nutrients) VALUES (?,?,?,?,?,?)",
            (recipe_id, food, qty_g, usda_match, db_source, json.dumps(nutrients)))
    conn.commit()
    print("\n✓ Recipe '" + name + "' saved (" + str(len(raw)) + " ingredients)")
    conn.close()

def list_recipes():
    if not os.path.exists(RECIPES_DB):
        print("No recipes saved yet.")
        return
    conn = sqlite3.connect(RECIPES_DB)
    conn.row_factory = sqlite3.Row
    recipes = conn.execute("SELECT * FROM recipes ORDER BY name").fetchall()
    if not recipes:
        print("No recipes saved yet.")
        conn.close()
        return
    print("\nSaved recipes:")
    for r in recipes:
        ings = conn.execute("SELECT COUNT(*) FROM recipe_ingredients WHERE recipe_id=?", (r["id"],)).fetchone()[0]
        print("  " + r["name"] + " (" + str(ings) + " ingredients, " + str(r["servings"]) + " serving(s))")
    conn.close()

# ── Main menu ─────────────────────────────────────────────────────────────────

print("\n╔══════════════════════════════════════════╗")
print("║          Nutrition Logger                ║")
print("╠══════════════════════════════════════════╣")
print("║  LOG FOOD                                ║")
print("║  1 — Type your diet log now              ║")
print("║  2 — Load from a typed/digital PDF       ║")
print("║  3 — Load from a handwritten PDF         ║")
print("║  4 — Load from a photo (JPG/PNG)         ║")
print("║  5 — Edit text directly in this script   ║")
print("║  6 — Retry last transcription            ║")
print("║  7 — Log a saved recipe                  ║")
print("╠══════════════════════════════════════════╣")
print("║  RECIPES                                 ║")
print("║  8 — Save a new recipe                   ║")
print("║  9 — View saved recipes                  ║")
print("╚══════════════════════════════════════════╝")
print("\n  Logging for: " + TODAY)

choice = input("\nChoose 1-9: ").strip()

# ── Recipe management ─────────────────────────────────────────────────────────

if choice == "8":
    save_recipe()
    logger.close()
    sys.exit(0)

elif choice == "9":
    list_recipes()
    logger.close()
    sys.exit(0)

# ── Log food modes ────────────────────────────────────────────────────────────

elif choice == "1":
    all_entries = []
    print("\nYou'll enter each meal separately.")
    while True:
        print("\nWhich meal?")
        for i, m in enumerate(MEALS, 1):
            print("  " + str(i) + " — " + m.capitalize())
        print("  0 — Done, log everything")
        meal_choice = input("\nChoose: ").strip()
        if meal_choice == "0":
            break
        if not meal_choice.isdigit() or int(meal_choice) not in range(1, len(MEALS)+1):
            print("Invalid — try again")
            continue
        meal_name = MEALS[int(meal_choice) - 1]
        print("\nEnter your " + meal_name + " items.")
        print("Include quantities where you can. Type END when done.\n")
        lines = []
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            lines.append(line)
        if lines:
            block = "[" + meal_name.upper() + "]\n" + "\n".join(lines)
            all_entries.append(block)
            print("✓ " + meal_name.capitalize() + " saved")
    if not all_entries:
        print("Nothing entered.")
        logger.close()
        sys.exit(0)
    diet_text = "\n\n".join(all_entries)

elif choice == "2":
    pdf_path = input("\nDrag your PDF here: ").strip().strip("'\"")
    if not os.path.exists(pdf_path):
        print("✗ File not found: " + pdf_path)
        logger.close()
        sys.exit(1)
    if is_scanned_pdf(pdf_path):
        print("  ⚠ Looks scanned — try option 3 instead")
        logger.close()
        sys.exit(1)
    diet_text = read_digital_pdf(pdf_path)
    print("  Extracted " + str(len(diet_text)) + " characters")

elif choice == "3":
    pdf_path = input("\nDrag your handwritten PDF here: ").strip().strip("'\"")
    if not os.path.exists(pdf_path):
        print("✗ File not found")
        logger.close()
        sys.exit(1)
    print("\nTranscribing handwriting...")
    diet_text = transcribe_handwritten_pdf(pdf_path, logger.client)
    with open("last_transcription.txt", "w") as tf:
        tf.write(diet_text)
    print("\n  Preview:\n  " + diet_text[:300] + "...")

elif choice == "4":
    img_path = input("\nDrag your photo here: ").strip().strip("'\"")
    if not os.path.exists(img_path):
        print("✗ File not found")
        logger.close()
        sys.exit(1)
    print("\nTranscribing image...")
    diet_text = transcribe_image_file(img_path, logger.client)
    with open("last_transcription.txt", "w") as tf:
        tf.write(diet_text)
    print("\n  Preview:\n  " + diet_text[:300] + "...")

elif choice == "5":
    diet_text = """

    [BREAKFAST]
    40g rolled oats with 200ml whole milk, black coffee

    [LUNCH]
    120g tin sardines, 1 slice rye bread, handful cherry tomatoes

    [DINNER]
    150g salmon fillet, 150g broccoli, 180g cooked brown rice

    """

elif choice == "6":
    if not os.path.exists("last_transcription.txt"):
        print("No previous transcription found.")
        logger.close()
        sys.exit(1)
    with open("last_transcription.txt") as tf:
        diet_text = tf.read()
    print("  Loaded (" + str(len(diet_text)) + " characters)")
    print("\n  Preview:\n  " + diet_text[:300] + "...")

elif choice == "7":
    if not os.path.exists(RECIPES_DB):
        print("No recipes saved yet. Choose option 8 to create one.")
        logger.close()
        sys.exit(0)
    conn = sqlite3.connect(RECIPES_DB)
    conn.row_factory = sqlite3.Row
    recipes = conn.execute("SELECT id, name, servings FROM recipes ORDER BY name").fetchall()
    if not recipes:
        print("No recipes saved yet.")
        logger.close()
        sys.exit(0)
    print("\nSaved recipes:")
    for i, r in enumerate(recipes, 1):
        print("  " + str(i) + " — " + r["name"])
    choice2 = input("\nChoose number: ").strip()
    if not choice2.isdigit() or int(choice2) not in range(1, len(recipes)+1):
        print("Invalid choice.")
        logger.close()
        sys.exit(1)
    recipe = dict(recipes[int(choice2)-1])
    servings_str = input("How many servings? [" + str(recipe["servings"]) + "]: ").strip()
    servings = float(servings_str) if servings_str else float(recipe["servings"])
    ingredients = conn.execute(
        "SELECT food_name, quantity_g FROM recipe_ingredients WHERE recipe_id=?",
        (recipe["id"],)).fetchall()
    conn.close()
    lines = []
    for ing in ingredients:
        scaled = round(ing["quantity_g"] * servings / float(recipe["servings"]), 1)
        lines.append(ing["food_name"] + " " + str(scaled) + "g")
    diet_text = "[RECIPE: " + recipe["name"] + "]\n" + "\n".join(lines)
    print("\n✓ Loaded '" + recipe["name"] + "' (" + str(servings) + " serving(s))")

else:
    print("Invalid choice.")
    logger.close()
    sys.exit(1)

# ── Date ──────────────────────────────────────────────────────────────────────

date_input = input("\nLog date [" + TODAY + "] — press Enter for today, or YYYY-MM-DD: ").strip()
log_date = date_input if date_input else TODAY

while True:
    try:
        datetime.date.fromisoformat(log_date)
        break
    except ValueError:
        print("✗ Invalid date — use YYYY-MM-DD")
        date_input = input("Try again [" + TODAY + "]: ").strip()
        log_date = date_input if date_input else TODAY

# ── Log it ────────────────────────────────────────────────────────────────────

logger.log_diet_entry(diet_text, log_date=log_date)
logger.close()
print("\n✓ Logged to nutrition_log.db for " + log_date + "\n")
