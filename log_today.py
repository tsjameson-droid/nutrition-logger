"""
log_today.py
=============
Five ways to log your diet. Run: python3 log_today.py
"""

from nutrition_logger import (
    NutritionLogger,
    transcribe_image_file,
    transcribe_handwritten_pdf,
    is_scanned_pdf
)
import config, datetime, sys, os

TODAY = datetime.date.today().isoformat()

logger = NutritionLogger(
    anthropic_key = config.ANTHROPIC_KEY,
    usda_key      = config.USDA_KEY,
    db_path       = "nutrition_log.db"
)

def read_digital_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()

MEALS = ["breakfast", "lunch", "dinner", "snack", "supplement"]

print("\n╔════════════════════════════════════════╗")
print("║         Nutrition Logger               ║")
print("╠════════════════════════════════════════╣")
print("║  1 — Type your diet log now            ║")
print("║  2 — Load from a typed/digital PDF     ║")
print("║  3 — Load from a handwritten PDF       ║")
print("║  4 — Load from a photo (JPG/PNG)       ║")
print("║  5 — Edit text directly in this script ║")
print("║  6 — Retry last transcription           ║")
print("║  7 — Log a saved recipe                 ║")
print("╚════════════════════════════════════════╝")
print(f"\n  Logging for: {TODAY}")

choice = input("\nChoose 1–5: ").strip()

# ── Mode 1: Interactive typing by meal ───────────────────────────────────────

if choice == "1":
    all_entries = []
    print("\nYou'll enter each meal separately.")

    while True:
        print("\nWhich meal?")
        for i, m in enumerate(MEALS, 1):
            print(f"  {i} — {m.capitalize()}")
        print("  0 — Done, log everything")

        meal_choice = input("\nChoose: ").strip()
        if meal_choice == "0":
            break
        if not meal_choice.isdigit() or int(meal_choice) not in range(1, len(MEALS)+1):
            print("Invalid — try again")
            continue

        meal_name = MEALS[int(meal_choice) - 1]
        print(f"\nEnter your {meal_name} items.")
        print("Include quantities where you can (e.g. '40g oats', '200ml milk').")
        print("Type END on its own line when done.\n")

        lines = []
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            lines.append(line)

        if lines:
            block = f"[{meal_name.upper()}]\n" + "\n".join(lines)
            all_entries.append(block)
            print(f"✓ {meal_name.capitalize()} saved")

    if not all_entries:
        print("Nothing entered — exiting.")
        logger.close()
        sys.exit(0)

    diet_text = "\n\n".join(all_entries)

# ── Mode 2: Digital/typed PDF ─────────────────────────────────────────────────

elif choice == "2":
    pdf_path = input("\nDrag your PDF here (or type the full path): ").strip().strip("'\"")
    if not os.path.exists(pdf_path):
        print(f"✗ File not found: {pdf_path}")
        logger.close()
        sys.exit(1)
    print(f"\nReading: {os.path.basename(pdf_path)}")
    if is_scanned_pdf(pdf_path):
        print("  ⚠ This PDF looks scanned/handwritten — try option 3 instead")
        logger.close()
        sys.exit(1)
    diet_text = read_digital_pdf(pdf_path)
    if not diet_text:
        print("✗ Could not extract text")
        logger.close()
        sys.exit(1)
    print(f"  Extracted {len(diet_text)} characters")

# ── Mode 3: Handwritten PDF ───────────────────────────────────────────────────

elif choice == "3":
    pdf_path = input("\nDrag your handwritten PDF here (or type the full path): ").strip().strip("'\"")
    if not os.path.exists(pdf_path):
        print(f"✗ File not found: {pdf_path}")
        logger.close()
        sys.exit(1)
    print(f"\nTranscribing handwriting: {os.path.basename(pdf_path)}")
    print("  (Claude will read each page — this takes ~10 seconds per page)")
    diet_text = transcribe_handwritten_pdf(pdf_path, logger.client)
    print(f"\n  Transcribed text:\n  {diet_text[:300]}...")

# ── Mode 4: Photo (JPG/PNG) ───────────────────────────────────────────────────

elif choice == "4":
    img_path = input("\nDrag your photo here (or type the full path): ").strip().strip("'\"")
    if not os.path.exists(img_path):
        print(f"✗ File not found: {img_path}")
        logger.close()
        sys.exit(1)
    ext = img_path.lower().split(".")[-1]
    if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
        print(f"✗ Unsupported format: .{ext} — use JPG or PNG")
        logger.close()
        sys.exit(1)
    print(f"\nTranscribing: {os.path.basename(img_path)}")
    print("  (Claude is reading the image...)")
    diet_text = transcribe_image_file(img_path, logger.client)
    print(f"\n  Transcribed text:\n  {diet_text[:300]}...")

# ── Mode 5: Edit text in script ───────────────────────────────────────────────

elif choice == "5":
    diet_text = """

    [BREAKFAST]
    40g rolled oats with 200ml whole milk, black coffee

    [LUNCH]
    120g tin sardines, 1 slice rye bread, handful cherry tomatoes

    [DINNER]
    150g salmon fillet, 150g broccoli, 180g cooked brown rice

    [SUPPLEMENT]
    400mg magnesium glycinate, vitamin D3 2000IU

    """
elif choice == "6":
    if not os.path.exists("last_transcription.txt"):
        print("No previous transcription found.")
        logger.close()
        sys.exit(1)
    with open("last_transcription.txt") as tf:
        diet_text = tf.read()
    print(f"  Loaded previous transcription ({len(diet_text)} characters)")
    print(f"
  Preview:
  {diet_text[:300]}...")

elif choice == "7":
    import sqlite3, json
    if not os.path.exists("recipes.db"):
        print("No recipes saved yet. Run python3 recipes.py to create one.")
        logger.close()
        sys.exit(0)
    conn = sqlite3.connect("recipes.db")
    conn.row_factory = sqlite3.Row
    recipes = conn.execute("SELECT id, name, servings FROM recipes ORDER BY name").fetchall()
    if not recipes:
        print("No recipes saved yet.")
        logger.close()
        sys.exit(0)
    print("
Saved recipes:")
    for i, r in enumerate(recipes, 1):
        print(f"  {i} — {r['name']}")
    choice2 = input("
Choose number: ").strip()
    if not choice2.isdigit() or int(choice2) not in range(1, len(recipes)+1):
        print("Invalid choice.")
        logger.close()
        sys.exit(1)
    recipe = dict(recipes[int(choice2)-1])
    servings_str = input(f"How many servings? [{recipe['servings']}]: ").strip()
    servings = float(servings_str) if servings_str else float(recipe["servings"])
    ingredients = conn.execute(
        "SELECT food_name, quantity_g FROM recipe_ingredients WHERE recipe_id = ?",
        (recipe["id"],)
    ).fetchall()
    conn.close()
    lines = []
    for ing in ingredients:
        scaled_qty = round(ing["quantity_g"] * servings / float(recipe["servings"]), 1)
        lines.append(f"{ing['food_name']} {scaled_qty}g")
    diet_text = f"[RECIPE: {recipe['name']}]
" + "
".join(lines)
    print(f"
✓ Loaded recipe '{recipe['name']}' ({servings} serving(s))")

else:
    print("Invalid choice.")
    logger.close()
    sys.exit(1)

# ── Date ──────────────────────────────────────────────────────────────────────

date_input = input(f"\nLog date [{TODAY}] — press Enter for today, or type YYYY-MM-DD: ").strip()
log_date = date_input if date_input else TODAY

while True:
    try:
        datetime.date.fromisoformat(log_date)
        break
    except ValueError:
        print(f"✗ Invalid date: {log_date} — please use YYYY-MM-DD format")
        date_input = input(f"Try again [{TODAY}]: ").strip()
        log_date = date_input if date_input else TODAY

# ── Log it ────────────────────────────────────────────────────────────────────

logger.log_diet_entry(diet_text, log_date=log_date)
logger.close()
print(f"\n✓ Logged to nutrition_log.db for {log_date}\n")
