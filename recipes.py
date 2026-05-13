"""
recipes.py
===========
Save, view, and manage custom recipes.
Saved recipes can be logged directly from log_today.py.

Run: python3 recipes.py
"""

import sqlite3, json, sys, datetime
sys.path.insert(0, ".")
import config
from nutrition_logger import (
    NutritionLogger, search_all_databases, scale_nutrients,
    clean_food_query, to_grams
)
import re

RECIPES_DB = "recipes.db"

# ── Database setup ────────────────────────────────────────────────────────────

def init_recipes_db():
    conn = sqlite3.connect(RECIPES_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            description TEXT,
            servings    REAL DEFAULT 1,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id   INTEGER NOT NULL,
            food_name   TEXT NOT NULL,
            quantity_g  REAL NOT NULL,
            usda_match  TEXT,
            db_source   TEXT,
            nutrients   TEXT,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)
    conn.commit()
    return conn

# ── Nutrient totals ───────────────────────────────────────────────────────────

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

def sum_nutrients(ingredients):
    totals = {n: 0.0 for n, _ in KEY_NUTRIENTS}
    for ing in ingredients:
        nutrients = json.loads(ing["nutrients"] or "{}")
        for name, _ in KEY_NUTRIENTS:
            totals[name] += nutrients.get(name) or 0.0
    return totals

def print_nutrients(totals, servings=1, label="TOTALS"):
    print(f"\n  {label}")
    print(f"  {'-'*45}")
    for name, unit in KEY_NUTRIENTS:
        v = round(totals[name] / servings, 2)
        if v > 0:
            print(f"  {name:<25} {v:>8} {unit}")

# ── Save a new recipe ─────────────────────────────────────────────────────────

def save_recipe(logger, conn):
    print("\nSave a new recipe")
    print("-" * 40)

    name = input("Recipe name (e.g. 'Tom porridge', 'SSG shake'): ").strip()
    if not name:
        print("No name entered.")
        return

    # Check if already exists
    existing = conn.execute(
        "SELECT id FROM recipes WHERE LOWER(name) = ?", (name.lower(),)
    ).fetchone()
    if existing:
        overwrite = input(f"Recipe '{name}' already exists. Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            return
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (existing[0],))
        conn.execute("DELETE FROM recipes WHERE id = ?", (existing[0],))
        conn.commit()

    description = input("Description (optional, press Enter to skip): ").strip()

    while True:
        servings_str = input("How many servings does this make? [1]: ").strip()
        if not servings_str:
            servings = 1.0
            break
        try:
            servings = float(servings_str)
            break
        except ValueError:
            print("  Please enter a number e.g. 1 or 2")

    print("\nEnter each ingredient one per line (e.g. 'oats 80g')")
    print("Type END when finished.\n")

    raw_ingredients = []
    while True:
        line = input("  > ").strip()
        if line.upper() == "END":
            break
        if not line:
            continue
        m = re.search(
            r"([0-9.]+)\s*(g|ml|kg|oz|lb|tbsp|tsp|cup|slice|piece|handful|tin|can)?",
            line, re.IGNORECASE
        )
        if m:
            qty_g = to_grams(float(m.group(1)), (m.group(2) or "g").lower()) or float(m.group(1))
            food = (line[:m.start()] + " " + line[m.end():]).strip()
        else:
            food = line
            qty_g = 100.0
        raw_ingredients.append((food, qty_g))
        print(f"  Added: {food} ({qty_g}g)")

    if not raw_ingredients:
        print("No ingredients entered.")
        return

    print(f"\nLooking up {len(raw_ingredients)} ingredients...\n")

    now = datetime.datetime.now().isoformat()
    cursor = conn.execute(
        "INSERT INTO recipes (name, description, servings, created_at, updated_at) VALUES (?,?,?,?,?)",
        (name, description, servings, now, now)
    )
    recipe_id = cursor.lastrowid

    for food, qty_g in raw_ingredients:
        term = clean_food_query(food, logger.client)
        result = search_all_databases(term, config.USDA_KEY)
        if result:
            nutrients = scale_nutrients(result["nutrients_100g"], qty_g)
            usda_match = result["name"]
            db_source = result["source"]
            print(f"  ✓ [{db_source.upper()}] {food} → {usda_match}")
        else:
            nutrients = {}
            usda_match = None
            db_source = None
            print(f"  ✗ No match found for: {food}")

        conn.execute(
            "INSERT INTO recipe_ingredients (recipe_id, food_name, quantity_g, usda_match, db_source, nutrients) VALUES (?,?,?,?,?,?)",
            (recipe_id, food, qty_g, usda_match, db_source, json.dumps(nutrients))
        )

    conn.commit()

    # Show nutrient summary
    ingredients = conn.execute(
        "SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,)
    ).fetchall()
    ingredients = [dict(r) for r in ingredients]
    totals = sum_nutrients(ingredients)

    print(f"\n✓ Recipe '{name}' saved ({len(raw_ingredients)} ingredients, {servings} serving(s))")
    print_nutrients(totals, servings=1, label=f"PER SERVING ({servings} serving recipe)")

# ── List all recipes ──────────────────────────────────────────────────────────

def list_recipes(conn):
    recipes = conn.execute(
        "SELECT * FROM recipes ORDER BY name"
    ).fetchall()

    if not recipes:
        print("\nNo recipes saved yet.")
        return

    print(f"\n{'='*50}")
    print(f"SAVED RECIPES ({len(recipes)})")
    print(f"{'='*50}")

    for r in recipes:
        r = dict(r)
        ingredients = conn.execute(
            "SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (r["id"],)
        ).fetchall()
        ingredients = [dict(i) for i in ingredients]
        totals = sum_nutrients(ingredients)
        kcal = round(totals["energy_kcal"] / r["servings"], 1)
        protein = round(totals["protein_g"] / r["servings"], 1)
        print(f"\n  {r['name']}")
        if r["description"]:
            print(f"  {r['description']}")
        print(f"  {len(ingredients)} ingredients | {r['servings']} serving(s)")
        print(f"  Per serving: {kcal} kcal | {protein}g protein")

# ── View a recipe in detail ───────────────────────────────────────────────────

def view_recipe(conn):
    recipes = conn.execute("SELECT name FROM recipes ORDER BY name").fetchall()
    if not recipes:
        print("\nNo recipes saved yet.")
        return

    print("\nSaved recipes:")
    for i, r in enumerate(recipes, 1):
        print(f"  {i} — {r[0]}")

    choice = input("\nEnter number: ").strip()
    if not choice.isdigit() or int(choice) not in range(1, len(recipes)+1):
        print("Invalid choice.")
        return

    name = recipes[int(choice)-1][0]
    recipe = dict(conn.execute("SELECT * FROM recipes WHERE name = ?", (name,)).fetchone())
    ingredients = [dict(r) for r in conn.execute(
        "SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (recipe["id"],)
    ).fetchall()]

    print(f"\n{'='*55}")
    print(f"{recipe['name'].upper()}")
    if recipe["description"]:
        print(f"{recipe['description']}")
    print(f"Servings: {recipe['servings']}")
    print(f"{'='*55}")
    print("\nIngredients:")
    for ing in ingredients:
        src = f"[{ing['db_source'].upper()}]" if ing["db_source"] else ""
        print(f"  {ing['food_name']} ({ing['quantity_g']}g) → {ing['usda_match'] or 'no match'} {src}")

    totals = sum_nutrients(ingredients)
    print_nutrients(totals, servings=1, label="TOTALS (whole recipe)")
    if recipe["servings"] > 1:
        print_nutrients(totals, servings=recipe["servings"], label=f"PER SERVING (1/{int(recipe['servings'])})")

# ── Delete a recipe ───────────────────────────────────────────────────────────

def delete_recipe(conn):
    recipes = conn.execute("SELECT id, name FROM recipes ORDER BY name").fetchall()
    if not recipes:
        print("\nNo recipes saved yet.")
        return

    print("\nSaved recipes:")
    for i, r in enumerate(recipes, 1):
        print(f"  {i} — {r[1]}")

    choice = input("\nEnter number to delete: ").strip()
    if not choice.isdigit() or int(choice) not in range(1, len(recipes)+1):
        print("Invalid choice.")
        return

    recipe_id, name = recipes[int(choice)-1]
    confirm = input(f"Delete '{name}'? (y/n): ").strip().lower()
    if confirm == "y":
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))
        conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        conn.commit()
        print(f"✓ '{name}' deleted")

# ── Main menu ─────────────────────────────────────────────────────────────────

conn = init_recipes_db()
conn.row_factory = sqlite3.Row

logger = NutritionLogger(
    anthropic_key=config.ANTHROPIC_KEY,
    usda_key=config.USDA_KEY,
    db_path="nutrition_log.db"
)

print("\n╔══════════════════════════════════════╗")
print("║         Recipe Manager               ║")
print("╠══════════════════════════════════════╣")
print("║  1 — Save a new recipe               ║")
print("║  2 — View all recipes                ║")
print("║  3 — View a recipe in detail         ║")
print("║  4 — Delete a recipe                 ║")
print("╚══════════════════════════════════════╝")

choice = input("\nChoose 1-4: ").strip()

if choice == "1":
    save_recipe(logger, conn)
elif choice == "2":
    list_recipes(conn)
elif choice == "3":
    view_recipe(conn)
elif choice == "4":
    delete_recipe(conn)
else:
    print("Invalid choice.")

logger.close()
conn.close()
