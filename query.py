"""
query.py
=========
Two modes:
  1 — Analyse a meal (type ingredients, get instant nutrition breakdown)
  2 — Query your logged data in plain English

Run: python3 query.py
"""

from nutrition_logger import NutritionLogger, search_usda, get_usda_nutrients, scale_nutrients, clean_food_query
import config, sqlite3, datetime, json

TODAY = datetime.date.today().isoformat()

logger = NutritionLogger(
    anthropic_key = config.ANTHROPIC_KEY,
    usda_key      = config.USDA_KEY,
    db_path       = "nutrition_log.db"
)

print("\n╔══════════════════════════════════════╗")
print("║        Nutrition Tool                ║")
print("╠══════════════════════════════════════╣")
print("║  1 — Analyse a meal                  ║")
print("║  2 — Query my logged data            ║")
print("╚══════════════════════════════════════╝")

choice = input("\nChoose 1 or 2: ").strip()

# ── Mode 1: Instant meal analyser ────────────────────────────────────────────

if choice == "1":
    print("\nEnter each ingredient on a new line.")
    print("Format: food name, quantity and unit")
    print("Example:")
    print("  chicken breast grilled, 100g")
    print("  broccoli raw, 120g")
    print("  rice white cooked, 150g")
    print("\nType END when finished.\n")

    import re
    from nutrition_logger import to_grams

    items = []
    while True:
        line = input("  > ").strip()
        if line.upper() == "END":
            break
        if not line:
            continue

        # Find a number anywhere in the line e.g. "chicken breast 100g" or "150g rice"
        m = re.search(r"([\d.]+)\s*(g|ml|kg|oz|lb|tbsp|tsp|cup|slice|piece|handful|tin|can|)", line, re.IGNORECASE)
        if m:
            qty = float(m.group(1))
            unit = m.group(2).lower() or "g"
            qty_g = to_grams(qty, unit) or qty
            # Remove the quantity part to get the food name
            food = line[:m.start()].strip() + " " + line[m.end():].strip()
            food = food.strip()
        else:
            food = line
            qty_g = 100.0
            print(f"  No quantity found — using 100g")

        items.append((food, qty_g))
        print(f"  ✓ Added: {food} ({qty_g}g)")

    if not items:
        print("Nothing entered.")
        logger.close()
        exit()

    print("\nLooking up nutritional data...\n")

    NUTRIENTS = [
        ("energy_kcal","kcal"),("protein_g","g"),("fat_total_g","g"),
        ("saturated_fat_g","g"),("carbohydrate_g","g"),("fibre_g","g"),
        ("sugars_g","g"),("calcium_mg","mg"),("iron_mg","mg"),
        ("magnesium_mg","mg"),("potassium_mg","mg"),("sodium_mg","mg"),
        ("zinc_mg","mg"),("selenium_ug","ug"),("vitamin_a_ug_rae","ug"),
        ("vitamin_c_mg","mg"),("vitamin_d_ug","ug"),("vitamin_b6_mg","mg"),
        ("vitamin_b12_ug","ug"),("folate_ug","ug"),("omega3_ala_g","g"),
        ("omega3_epa_g","g"),("omega3_dha_g","g"),
    ]

    totals = {n: 0.0 for n, _ in NUTRIENTS}
    per_food = []

    for food, qty_g in items:
        term = clean_food_query(food, logger.client)
        match = search_usda(term, config.USDA_KEY)
        if not match:
            print(f"  ✗ No match found for: {food}")
            continue
        n100 = get_usda_nutrients(match["fdcId"], config.USDA_KEY)
        scaled = scale_nutrients(n100, qty_g)
        per_food.append((food, qty_g, match["description"], scaled))
        for name, _ in NUTRIENTS:
            totals[name] += scaled.get(name) or 0.0

    # Print per-food breakdown
    for food, qty_g, usda_name, scaled in per_food:
        print(f"{'='*55}")
        print(f"{food.title()} ({qty_g}g)")
        print(f"USDA match: {usda_name}")
        print(f"{'='*55}")
        print(f"  {'Nutrient':<22} {'Amount':>12}")
        print(f"  {'-'*36}")
        for name, unit in NUTRIENTS:
            v = scaled.get(name)
            if v is not None and v > 0:
                print(f"  {name:<22} {round(v,2):>8} {unit}")
        print()

    # Print totals
    print(f"{'='*55}")
    print("MEAL TOTALS")
    print(f"{'='*55}")
    print(f"  {'Nutrient':<22} {'Total':>12}")
    print(f"  {'-'*36}")
    for name, unit in NUTRIENTS:
        v = round(totals[name], 2)
        if v > 0:
            print(f"  {name:<22} {v:>8} {unit}")
    print()

    # Ask if they want to log it
    save = input("Log this meal to your database? (y/n): ").strip().lower()
    if save == "y":
        meal_lines = [f"{food}, {qty_g}g" for food, qty_g in items]
        diet_text = "\n".join(meal_lines)
        date_input = input(f"Date [{TODAY}]: ").strip()
        log_date = date_input if date_input else TODAY
        logger.log_diet_entry(diet_text, log_date=log_date)
        print(f"✓ Logged to database for {log_date}")

# ── Mode 2: Query logged data ─────────────────────────────────────────────────

elif choice == "2":
    conn = sqlite3.connect("nutrition_log.db")
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT log_date FROM diet_log ORDER BY log_date DESC LIMIT 30"
    ).fetchall()]
    conn.close()

    if not dates:
        print("\nNo data logged yet. Run log_today.py first.")
        logger.close()
        exit()

    print(f"\nDates in database ({len(dates)} days):")
    for d in dates:
        print(f"  {d}")

    print("\n  1 — A specific day")
    print("  2 — Last 7 days")
    print("  3 — Last 30 days")
    print("  4 — All time")

    scope = input("\nChoose 1-4: ").strip()

    conn = sqlite3.connect("nutrition_log.db")
    conn.row_factory = sqlite3.Row

    if scope == "1":
        date_input = input(f"Date [{TODAY}]: ").strip()
        log_date = date_input if date_input else TODAY
        rows = conn.execute(
            "SELECT * FROM diet_log WHERE log_date = ? ORDER BY meal_time",
            (log_date,)
        ).fetchall()
        scope_label = log_date
    elif scope == "2":
        import datetime as dt
        cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
        rows = conn.execute(
            "SELECT * FROM diet_log WHERE log_date >= ? ORDER BY log_date, meal_time",
            (cutoff,)
        ).fetchall()
        scope_label = "last 7 days"
    elif scope == "3":
        import datetime as dt
        cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        rows = conn.execute(
            "SELECT * FROM diet_log WHERE log_date >= ? ORDER BY log_date, meal_time",
            (cutoff,)
        ).fetchall()
        scope_label = "last 30 days"
    else:
        rows = conn.execute(
            "SELECT * FROM diet_log ORDER BY log_date, meal_time"
        ).fetchall()
        scope_label = "all time"

    conn.close()

    if not rows:
        print(f"\nNo data found.")
        logger.close()
        exit()

    data = [dict(r) for r in rows]
    data_json = json.dumps(data, indent=2)

    SYSTEM = """You are a clinical nutrition analyst. You have food log data in JSON.
Answer questions precisely with specific foods, dates, and numeric values.
Use UK RNIs as reference points. Be concise — numbers first, context second."""

    print(f"\nFound {len(rows)} entries for {scope_label}.")
    print("Ask anything. Type EXIT to quit.\n")

    while True:
        question = input("Question: ").strip()
        if question.upper() in ("EXIT", "QUIT", "Q"):
            break
        if not question:
            continue
        response = logger.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Data ({scope_label}):\n\n{data_json}\n\nQuestion: {question}"
            }]
        )
        print(f"\n{response.content[0].text}\n")
        print("-" * 50 + "\n")

else:
    print("Invalid choice.")

logger.close()
