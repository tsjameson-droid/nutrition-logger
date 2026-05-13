"""
validate_vs_cronometer.py
==========================
Compares your system's nutrient outputs against Cronometer (NCCDB)
values from a Cronometer CSV export.

Usage:
    1. Export your Cronometer data as CSV (Nutrition Reports → Export)
    2. Place the CSV in your nutrition-logger folder
    3. Run: python3 validate_vs_cronometer.py
"""

import sys, os, json
sys.path.insert(0, ".")
import config
import pandas as pd
import sqlite3
from nutrition_logger import (
    search_all_databases, scale_nutrients, clean_food_query,
    to_grams, NutritionLogger
)
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

CSV_PATH = "cronometer_combined.csv"   # combined 3-year dataset
TOP_N    = 30                   # how many foods to validate

# Map Cronometer column names → our nutrient column names
CRONOMETER_MAP = {
    "Energy (kcal)":       "energy_kcal",
    "Protein (g)":         "protein_g",
    "Fat (g)":             "fat_total_g",
    "Carbs (g)":           "carbohydrate_g",
    "Fiber (g)":           "fibre_g",
    "Sugars (g)":          "sugars_g",
    "Saturated (g)":       "saturated_fat_g",
    "Monounsaturated (g)": "monounsaturated_fat_g",
    "Polyunsaturated (g)": "polyunsaturated_fat_g",
    "Calcium (mg)":        "calcium_mg",
    "Iron (mg)":           "iron_mg",
    "Magnesium (mg)":      "magnesium_mg",
    "Phosphorus (mg)":     "phosphorus_mg",
    "Potassium (mg)":      "potassium_mg",
    "Sodium (mg)":         "sodium_mg",
    "Zinc (mg)":           "zinc_mg",
    "Copper (mg)":         "copper_mg",
    "Manganese (mg)":      "manganese_mg",
    "Selenium (µg)":       "selenium_ug",
    "Vitamin A (µg)":      "vitamin_a_ug_rae",
    "Vitamin C (mg)":      "vitamin_c_mg",
    "Vitamin D (IU)":      "vitamin_d_ug",   # will convert IU→µg
    "Vitamin E (mg)":      "vitamin_e_mg",
    "Vitamin K (µg)":      "vitamin_k_ug",
    "B1 (Thiamine) (mg)":  "thiamin_mg",
    "B2 (Riboflavin) (mg)":"riboflavin_mg",
    "B3 (Niacin) (mg)":    "niacin_mg",
    "B5 (Pantothenic Acid) (mg)": "pantothenic_acid_mg",
    "B6 (Pyridoxine) (mg)":"vitamin_b6_mg",
    "B12 (Cobalamin) (µg)":"vitamin_b12_ug",
    "Folate (µg)":         "folate_ug",
    "EPA (g)":             "omega3_epa_g",
    "DHA (g)":             "omega3_dha_g",
    "ALA (g)":             "omega3_ala_g",
}

KEY_NUTRIENTS = [
    "energy_kcal", "protein_g", "fat_total_g", "carbohydrate_g",
    "fibre_g", "calcium_mg", "iron_mg", "magnesium_mg",
    "potassium_mg", "sodium_mg", "zinc_mg", "vitamin_c_mg",
    "vitamin_d_ug", "vitamin_b12_ug", "folate_ug",
    "omega3_epa_g", "omega3_dha_g",
]

# ── Load Cronometer data ──────────────────────────────────────────────────────

if not os.path.exists(CSV_PATH):
    print(f"CSV not found: {CSV_PATH}")
    print("Place your Cronometer export CSV in this folder and update CSV_PATH")
    sys.exit(1)

df = pd.read_csv(CSV_PATH)

# Convert Vitamin D from IU to µg (1 IU = 0.025 µg)
if "Vitamin D (IU)" in df.columns:
    df["Vitamin D (µg)"] = df["Vitamin D (IU)"] * 0.025
    CRONOMETER_MAP["Vitamin D (µg)"] = "vitamin_d_ug"
    del CRONOMETER_MAP["Vitamin D (IU)"]

# Get top N most common foods (excluding custom recipes and supplements)
skip_keywords = ["_GH", "_CustomGH", "Custom", "custom", "Tim ", "GHKJ",
                 "Truvani", "Nutricost", "Nordic", "UCan", "HMB", "Leucine",
                 "Whey", "Casein", "CocoaVia", "Cocoa Via", "Re-Lyte"]

top_foods = []
for food, count in df['Food Name'].value_counts().items():
    if not any(k in food for k in skip_keywords):
        top_foods.append(food)
    if len(top_foods) >= TOP_N:
        break

print(f"\nValidating top {TOP_N} standard foods from Cronometer export")
print(f"Date range: {df['Day'].min()} to {df['Day'].max()}")
print(f"Total entries: {len(df)}\n")

# ── Set up logger ─────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=config.ANTHROPIC_KEY)

# ── Run comparison ────────────────────────────────────────────────────────────

results = []

print(f"{'Food':<40} {'DB':<6} {'Match':<35} {'Status'}")
print("-" * 100)

for food_name in top_foods:
    # Get Cronometer per-100g values (average across all entries for this food)
    food_rows = df[df['Food Name'] == food_name]
    
    # Get the amount column
    if 'Amount' not in food_rows.columns:
        continue
    
    # Calculate per-100g values from Cronometer
    crono_per_100g = {}
    for crono_col, our_col in CRONOMETER_MAP.items():
        if crono_col in food_rows.columns:
            # Sum nutrients and amounts, then calculate per 100g
            total_nutrient = food_rows[crono_col].sum()
            # Try to parse amounts (e.g. "100 g", "1 cup")
            # Use the average nutrient density approach
            total_entries = len(food_rows)
            avg_nutrient = total_nutrient / total_entries if total_entries > 0 else 0
            crono_per_100g[our_col] = avg_nutrient  # avg per serving for now

    # Search our system
    term = clean_food_query(food_name, client)
    result = search_all_databases(term, config.USDA_KEY,
                                      original_food=food_name, client=client)
    
    if not result:
        print(f"  {food_name[:38]:<40} {'—':<6} {'NO MATCH':<35} ✗")
        results.append({
            "food": food_name, "matched": False,
            "source": None, "match_name": None,
            "crono": crono_per_100g, "ours": {}
        })
        continue

    source    = result["source"].upper()
    match_name = result["name"][:34]
    our_nutrients = result["nutrients_100g"]
    
    # Compare key nutrients
    errors = []
    for nutrient in KEY_NUTRIENTS:
        crono_val = crono_per_100g.get(nutrient)
        our_val   = our_nutrients.get(nutrient)
        if crono_val and our_val and crono_val > 0:
            pct_error = abs(crono_val - our_val) / crono_val * 100
            if pct_error > 25:
                errors.append(f"{nutrient}:{round(pct_error)}%err")

    status = "✓" if not errors else f"⚠ {', '.join(errors[:2])}"
    print(f"  {food_name[:38]:<40} [{source}]  {match_name:<35} {status}")
    
    results.append({
        "food": food_name,
        "matched": True,
        "source": source,
        "match_name": result["name"],
        "search_term": term,
        "crono": crono_per_100g,
        "ours": our_nutrients,
    })

# ── Summary ───────────────────────────────────────────────────────────────────

matched   = sum(1 for r in results if r["matched"])
unmatched = len(results) - matched

print(f"\n{'='*60}")
print(f"VALIDATION SUMMARY")
print(f"{'='*60}")
print(f"  Foods tested:    {len(results)}")
print(f"  Matched:         {matched} ({round(matched/len(results)*100)}%)")
print(f"  No match:        {unmatched}")

usda_count  = sum(1 for r in results if r.get("source") == "USDA")
cofid_count = sum(1 for r in results if r.get("source") == "COFID")
print(f"  Source — USDA:   {usda_count}")
print(f"  Source — CoFID:  {cofid_count}")

# Save full results
with open("validation_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Full results saved to: validation_results.json")
print(f"  Open in Excel or share with Tom for detailed review.\n")
