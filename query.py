import sys, json, re, datetime
sys.path.insert(0, ".")
import config
from nutrition_logger import NutritionLogger, search_usda, get_usda_nutrients, scale_nutrients, clean_food_query, to_grams

TODAY = datetime.date.today().isoformat()

logger = NutritionLogger(
    anthropic_key=config.ANTHROPIC_KEY,
    usda_key=config.USDA_KEY,
    db_path="nutrition_log.db"
)

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

print("\n" + chr(9556) + chr(9552)*38 + chr(9559))
print(chr(9553) + "        Nutrition Tool                " + chr(9553))
print(chr(9560) + chr(9552)*22 + chr(9566) + chr(9552)*15 + chr(9563))
print(chr(9553) + "  1 - Analyse a meal                  " + chr(9553))
print(chr(9553) + "  2 - Query my logged data            " + chr(9553))
print(chr(9553) + chr(9552)*38 + chr(9553))

choice = input("\nChoose 1 or 2: ").strip()

if choice == "1":
    print("\nType each ingredient and quantity, one per line.")
    print("Example:  chicken breast grilled 100g")
    print("Type END when finished.\n")

    items = []
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
        items.append((food, qty_g))
        print(f"  Added: {food} ({qty_g}g)")

    if not items:
        print("Nothing entered.")
        logger.close()
        sys.exit(0)

    print("\nLooking up nutritional data...\n")
    totals = {n: 0.0 for n, _ in NUTRIENTS}

    for food, qty_g in items:
        term = clean_food_query(food, logger.client)
        match = search_usda(term, config.USDA_KEY)
        if not match:
            print(f"No match found for: {food}")
            continue
        n100 = get_usda_nutrients(match["fdcId"], config.USDA_KEY)
        scaled = scale_nutrients(n100, qty_g)
        print("=" * 55)
        desc = match["description"]
        print(f"{food.title()} ({qty_g}g) -> {desc}")
        print("=" * 55)
        for name, unit in NUTRIENTS:
            v = scaled.get(name)
            if v and v > 0:
                print(f"  {name:<22} {round(v,2):>8} {unit}")
        print()
        for name, _ in NUTRIENTS:
            totals[name] += scaled.get(name) or 0.0

    print("=" * 55)
    print("MEAL TOTALS")
    print("=" * 55)
    for name, unit in NUTRIENTS:
        v = round(totals[name], 2)
        if v > 0:
            print(f"  {name:<22} {v:>8} {unit}")

elif choice == "2":
    conn = __import__("sqlite3").connect("nutrition_log.db")
    conn.row_factory = __import__("sqlite3").Row
    dates = [r[0] for r in conn.execute("SELECT DISTINCT log_date FROM diet_log ORDER BY log_date DESC LIMIT 30").fetchall()]
    if not dates:
        print("No data logged yet.")
        logger.close()
        sys.exit(0)
    print("\nDates in database:")
    for d in dates:
        print(f"  {d}")
    print("\n  1 - Specific day  2 - Last 7 days  3 - Last 30 days  4 - All time")
    scope = input("\nChoose 1-4: ").strip()
    if scope == "1":
        d = input(f"Date [{TODAY}]: ").strip() or TODAY
        rows = conn.execute("SELECT * FROM diet_log WHERE log_date=? ORDER BY meal_time", (d,)).fetchall()
        label = d
    elif scope == "2":
        cutoff = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        rows = conn.execute("SELECT * FROM diet_log WHERE log_date>=? ORDER BY log_date,meal_time", (cutoff,)).fetchall()
        label = "last 7 days"
    elif scope == "3":
        cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        rows = conn.execute("SELECT * FROM diet_log WHERE log_date>=? ORDER BY log_date,meal_time", (cutoff,)).fetchall()
        label = "last 30 days"
    else:
        rows = conn.execute("SELECT * FROM diet_log ORDER BY log_date,meal_time").fetchall()
        label = "all time"
    conn.close()
    data_json = json.dumps([dict(r) for r in rows], indent=2)
    SYSTEM = "You are a clinical nutrition analyst. Answer questions precisely with specific foods, dates, and numeric values. Use UK RNIs. Be concise."
    print(f"\nFound {len(rows)} entries for {label}. Type EXIT to quit.\n")
    while True:
        q = input("Question: ").strip()
        if q.upper() in ("EXIT","QUIT","Q"):
            break
        if not q:
            continue
        r = logger.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role":"user","content":f"Data ({label}):\n\n{data_json}\n\nQuestion: {q}"}]
        )
        print(f"\n{r.content[0].text}\n")
        print("-"*50 + "\n")

logger.close()
