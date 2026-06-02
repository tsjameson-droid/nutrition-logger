"""
query.py
=========
Two modes:
  1 — Analyse a meal (type ingredients, get instant nutrition breakdown)
  2 — Query your logged data in plain English

Run: python3 query.py
"""

from nutrition_logger import NutritionLogger, search_usda, search_all_databases, get_usda_nutrients, scale_nutrients, clean_food_query
import config, sqlite3, datetime, json
import sense_check as _sc

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
        # MEXT lookup for Japanese foods
        import mext as _mxt_q
        import os as _os_q
        import sqlite3 as _sq_q
        _mdb_q = _os_q.path.join(_os_q.path.dirname(_os_q.path.abspath(__file__)), "mext.db")
        _mi_q = _mxt_q.lookup_mext(food.lower().strip())
        if _mi_q and _os_q.path.exists(_mdb_q):
            _mn_q = _mxt_q.get_mext_nutrients(_mi_q, _mdb_q)
            if _mn_q:
                _c_q = _sq_q.connect(_mdb_q)
                _r_q = _c_q.execute("SELECT food_name FROM mext_foods WHERE item_no=?", (_mi_q,)).fetchone()
                _c_q.close()
                _nm_q = _r_q[0] if _r_q else _mi_q
                print("     ✓ [MEXT] " + _nm_q)
                scaled = {k: v * qty_g / 100.0 for k, v in _mn_q.items() if v is not None}
                # Sense check before logging
                def _do_lookup(new_food, new_qty):
                    import mext as _mxt_sc, os as _os_sc, sqlite3 as _sq_sc
                    _mdb = _os_sc.path.join(_os_sc.path.dirname(_os_sc.path.abspath(__file__)), "mext.db")
                    _mi = _mxt_sc.lookup_mext(new_food.lower().strip())
                    if _mi and _os_sc.path.exists(_mdb):
                        _mn2 = _mxt_sc.get_mext_nutrients(_mi, _mdb)
                        if _mn2:
                            _c3 = _sq_sc.connect(_mdb)
                            _r3 = _c3.execute("SELECT food_name FROM mext_foods WHERE item_no=?", (_mi,)).fetchone()
                            _c3.close()
                            return (_r3[0] if _r3 else _mi), _mn2
                    _m2 = search_usda(clean_food_query(new_food, logger.client), config.USDA_KEY)
                    if _m2:
                        _n2 = get_usda_nutrients(_m2["fdcId"], config.USDA_KEY)
                        _n2s = scale_nutrients(_n2, new_qty)
                        return _m2["description"], _n2
                    return None, {}
                _sc_accepted, food, qty_g, _sc_n100 = _sc.resolve_ingredient(
                    food, qty_g, _mn_q, _do_lookup)
                if not _sc_accepted:
                    continue
                # Update scaled with potentially corrected nutrients
                if _sc_n100:
                    scaled = scale_nutrients(_sc_n100, qty_g)
                per_food.append((food, qty_g, _nm_q, scaled))
                continue
        term = clean_food_query(food, logger.client)
        result = search_all_databases(term, config.USDA_KEY,
                                      original_food=food,
                                      client=logger.client)
        if not result:
            print(f"  ✗ No match found for: {food}")
            continue
        n100 = result["nutrients_100g"]
        matched_name = result["name"]
        # Sense check on per-100g nutrients
        def _do_lookup2(new_food, new_qty):
            r2 = search_all_databases(clean_food_query(new_food, logger.client),
                                      config.USDA_KEY,
                                      original_food=new_food,
                                      client=logger.client)
            if r2:
                return r2["name"], r2["nutrients_100g"]
            return None, {}
        _sc2_ok, food, qty_g, _sc2_n100 = _sc.resolve_ingredient(
            food, qty_g, n100, _do_lookup2)
        if not _sc2_ok:
            continue
        if _sc2_n100:
            n100 = _sc2_n100
        scaled = scale_nutrients(n100, qty_g)
        per_food.append((food, qty_g, matched_name, scaled))
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
    # Daily totals sense check
    _food_contribs = [(f, s.get("energy_kcal", 0) or 0) for f, _, _, s in per_food]
    _sc.resolve_daily_totals(totals, food_contributions=_food_contribs)
    
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