"""
sense_check.py
==============
Quality control for nutrition logging.

Two public functions:
    check_ingredient(food_name, qty_g, nutrients_100g, config=None)
        -> list of Flag objects

    check_daily_totals(totals, log_date, config=None)
        -> list of Flag objects

And one interactive flow for use in scripts:
    resolve_ingredient(food_name, qty_g, nutrients_100g, lookup_fn, config=None)
        -> (accepted: bool, corrected_food: str|None, corrected_qty: float|None)
        If flags are raised, pauses and asks the user to accept, correct, or skip.
        If corrected, calls lookup_fn(new_food, new_qty) to re-lookup.

Config is loaded from sense_check_config.json in the same directory.
If the file does not exist, defaults are written on first run.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

_DEFAULT_CONFIG = {
    "daily": {
        "energy_kcal_min": 1200,
        "energy_kcal_max": 5000,
        "protein_g_min": 20,
        "protein_g_max": 300,
        "fat_g_min": 10,
        "fat_g_max": 250,
        "carbs_g_min": 10,
        "carbs_g_max": 700,
        "single_food_energy_pct_max": 60,
    },
    "per_ingredient": {
        "energy_kcal_per_100g_max": 900,
        "protein_g_per_100g_max": 90,
        "fat_g_per_100g_max": 100,
        "carbs_g_per_100g_max": 100,
        "single_serving_energy_max": 2000,
        "quantity_g_max_solid": 800,
        "quantity_ml_max_liquid": 2000,
    },
    "food_type_energy_ranges": {
        "vegetable": {
            "keywords": ["broccoli", "spinach", "kale", "cabbage", "carrot",
                         "celery", "cucumber", "tomato", "pepper", "courgette",
                         "aubergine", "onion", "leek", "asparagus", "mushroom",
                         "pea", "bean sprout", "lettuce", "rocket", "watercress",
                         "daikon", "edamame"],
            "min": 5, "max": 120,
        },
        "fruit": {
            "keywords": ["apple", "banana", "orange", "grape", "strawberry",
                         "blueberry", "raspberry", "mango", "pineapple",
                         "watermelon", "melon", "pear", "peach", "plum",
                         "cherry", "lemon", "lime"],
            "min": 20, "max": 100,
        },
        "oil_fat": {
            "keywords": ["oil", "butter", "lard", "ghee", "dripping",
                         "suet", "margarine", "mayonnaise"],
            "min": 600, "max": 920,
        },
        "lean_meat": {
            "keywords": ["chicken breast", "turkey breast", "cod", "haddock",
                         "tuna", "prawn", "shrimp", "white fish"],
            "min": 70, "max": 200,
        },
        "coffee_tea": {
            "keywords": ["coffee", "tea", "espresso", "americano"],
            "min": 0, "max": 30,
        },
        "water": {
            "keywords": ["water", "sparkling water", "mineral water"],
            "min": 0, "max": 5,
        },
    },
}


@dataclass
class Flag:
    level: str        # "warning" or "error"
    field: str        # what was checked
    message: str
    value: float
    threshold: float


def _load_config(config=None):
    if config is not None:
        return config
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "sense_check_config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            try:
                loaded = json.load(f)
                # Remove comment keys
                for section in list(loaded.keys()):
                    if section.startswith("_"):
                        del loaded[section]
                    elif isinstance(loaded[section], dict):
                        for k in list(loaded[section].keys()):
                            if k.startswith("_"):
                                del loaded[section][k]
                return loaded
            except Exception:
                pass
    # Write defaults
    with open(config_path, "w") as f:
        out = dict(_DEFAULT_CONFIG)
        out["_comment"] = "Edit thresholds to suit your needs."
        json.dump(out, f, indent=2)
    return _DEFAULT_CONFIG


def _match_food_type(food_name: str, food_type_ranges: dict):
    """Return (type_name, range_dict) if food name matches a type, else None."""
    name_lower = food_name.lower()
    for type_name, spec in food_type_ranges.items():
        if type_name.startswith("_"):
            continue
        for kw in spec.get("keywords", []):
            if kw in name_lower:
                return type_name, spec
    return None, None


def check_ingredient(food_name: str, qty_g: float,
                     nutrients_100g: dict, config=None) -> list:
    """
    Check a single ingredient for implausible values.
    Returns list of Flag objects (empty = all clear).
    """
    cfg = _load_config(config)
    pi = cfg.get("per_ingredient", {})
    ftr = cfg.get("food_type_energy_ranges", {})
    flags = []

    if not nutrients_100g:
        return flags

    e100 = nutrients_100g.get("energy_kcal", 0) or 0
    p100 = nutrients_100g.get("protein_g", 0) or 0
    f100 = nutrients_100g.get("fat_total_g", 0) or 0
    c100 = nutrients_100g.get("carbohydrate_g", 0) or 0

    # Scale to actual quantity
    qty = qty_g or 0
    e_total = e100 * qty / 100
    p_total = p100 * qty / 100

    # --- Per 100g checks ---
    max_e = pi.get("energy_kcal_per_100g_max", 900)
    if e100 > max_e:
        flags.append(Flag("warning", "energy_per_100g",
                          f"{food_name}: {e100:.0f} kcal/100g seems very high (max expected {max_e})",
                          e100, max_e))

    max_p = pi.get("protein_g_per_100g_max", 90)
    if p100 > max_p:
        flags.append(Flag("warning", "protein_per_100g",
                          f"{food_name}: {p100:.1f}g protein/100g seems very high (max expected {max_p}g)",
                          p100, max_p))

    max_f = pi.get("fat_g_per_100g_max", 100)
    if f100 > max_f:
        flags.append(Flag("warning", "fat_per_100g",
                          f"{food_name}: {f100:.1f}g fat/100g seems very high (max expected {max_f}g)",
                          f100, max_f))

    max_c = pi.get("carbs_g_per_100g_max", 100)
    if c100 > max_c:
        flags.append(Flag("warning", "carbs_per_100g",
                          f"{food_name}: {c100:.1f}g carbs/100g seems very high (max expected {max_c}g)",
                          c100, max_c))

    # --- Food type energy range check ---
    type_name, type_range = _match_food_type(food_name, ftr)
    if type_range and e100 > 0:
        t_min = type_range.get("min", 0)
        t_max = type_range.get("max", 999)
        if e100 < t_min:
            flags.append(Flag("warning", "food_type_energy",
                              f"{food_name} matched as {type_name}: "
                              f"{e100:.0f} kcal/100g is lower than expected ({t_min}-{t_max}). "
                              f"Wrong food matched?",
                              e100, t_min))
        elif e100 > t_max:
            flags.append(Flag("error", "food_type_energy",
                              f"{food_name} matched as {type_name}: "
                              f"{e100:.0f} kcal/100g is higher than expected ({t_min}-{t_max}). "
                              f"Wrong food matched?",
                              e100, t_max))

    # --- Single serving total energy ---
    max_serving_e = pi.get("single_serving_energy_max", 2000)
    if e_total > max_serving_e:
        flags.append(Flag("warning", "single_serving_energy",
                          f"{food_name} ({qty:.0f}g): {e_total:.0f} kcal total seems very high",
                          e_total, max_serving_e))

    # --- Quantity checks ---
    is_liquid = any(w in food_name.lower() for w in
                    ["milk", "juice", "water", "coffee", "tea", "soup",
                     "stock", "broth", "oil", "wine", "beer", "sake",
                     "drink", "smoothie", "shake"])
    if is_liquid:
        max_qty = pi.get("quantity_ml_max_liquid", 2000)
    else:
        max_qty = pi.get("quantity_g_max_solid", 800)

    if qty > max_qty:
        flags.append(Flag("warning", "quantity",
                          f"{food_name}: {qty:.0f}{'ml' if is_liquid else 'g'} seems like a lot "
                          f"(max expected {max_qty}{'ml' if is_liquid else 'g'})",
                          qty, max_qty))

    return flags


def check_daily_totals(totals: dict, log_date: str = "",
                       food_contributions: list = None, config=None) -> list:
    """
    Check daily totals for implausible values.
    totals: dict of nutrient -> value (scaled to actual intake)
    food_contributions: optional list of (food_name, energy_kcal) for dominance check
    Returns list of Flag objects.
    """
    cfg = _load_config(config)
    d = cfg.get("daily", {})
    flags = []

    label = f" on {log_date}" if log_date else ""

    e = totals.get("energy_kcal", 0) or 0
    p = totals.get("protein_g", 0) or 0
    f = totals.get("fat_total_g", 0) or 0
    c = totals.get("carbohydrate_g", 0) or 0

    def _check(val, min_key, max_key, name, unit):
        lo = d.get(min_key, 0)
        hi = d.get(max_key, 9999)
        if val > 0 and val < lo:
            flags.append(Flag("warning", name,
                               f"Daily {name}{label}: {val:.1f}{unit} is below the expected minimum ({lo}{unit})",
                               val, lo))
        elif val > hi:
            flags.append(Flag("error", name,
                               f"Daily {name}{label}: {val:.1f}{unit} is above the expected maximum ({hi}{unit})",
                               val, hi))

    _check(e, "energy_kcal_min", "energy_kcal_max", "energy", " kcal")
    _check(p, "protein_g_min", "protein_g_max", "protein", "g")
    _check(f, "fat_g_min", "fat_g_max", "fat", "g")
    _check(c, "carbs_g_min", "carbs_g_max", "carbs", "g")

    # Single food dominance check
    if food_contributions and e > 0:
        pct_max = d.get("single_food_energy_pct_max", 60)
        for food_name, food_energy in food_contributions:
            pct = (food_energy / e) * 100
            if pct > pct_max:
                flags.append(Flag("warning", "single_food_dominance",
                                   f"{food_name} contributes {pct:.0f}% of daily energy "
                                   f"({food_energy:.0f} kcal of {e:.0f} total). "
                                   f"Check quantity or match is correct.",
                                   pct, pct_max))

    return flags


def _print_flags(flags: list):
    """Print flags with colour coding."""
    for flag in flags:
        prefix = "  ⚠" if flag.level == "warning" else "  ✗"
        print(f"{prefix} {flag.message}")


def resolve_ingredient(food_name: str, qty_g: float, nutrients_100g: dict,
                       lookup_fn, config=None):
    """
    Interactive sense-check for a single ingredient.

    lookup_fn: callable(food_name: str, qty_g: float) -> (matched_name, nutrients_100g)
               Should perform database lookup and return the match.

    Returns:
        (accepted: bool,
         final_food_name: str,
         final_qty_g: float,
         final_nutrients_100g: dict)

    If no flags: returns (True, food_name, qty_g, nutrients_100g) immediately.
    If flags and user accepts: same.
    If flags and user corrects: re-looks up and returns new values.
    If flags and user skips: returns (False, ...).
    """
    flags = check_ingredient(food_name, qty_g, nutrients_100g, config)
    if not flags:
        return True, food_name, qty_g, nutrients_100g

    print()
    print("  ┌─ Sense check flagged ─────────────────────────────")
    _print_flags(flags)
    print("  └────────────────────────────────────────────────────")
    print()
    print("  What would you like to do?")
    print("  [A] Accept anyway")
    print("  [C] Correct — re-enter food name and/or quantity")
    print("  [S] Skip — don't log this item")
    print()

    while True:
        choice = input("  Your choice (A/C/S): ").strip().upper()
        if choice == "A":
            return True, food_name, qty_g, nutrients_100g

        elif choice == "S":
            print(f"  Skipped: {food_name}")
            return False, food_name, qty_g, nutrients_100g

        elif choice == "C":
            print()
            new_food = input(f"  Food name [{food_name}]: ").strip()
            if not new_food:
                new_food = food_name

            qty_str = input(f"  Quantity in grams [{qty_g}g]: ").strip()
            if qty_str:
                m = re.match(r"([\d.]+)", qty_str)
                new_qty = float(m.group(1)) if m else qty_g
            else:
                new_qty = qty_g

            print(f"  Looking up: {new_food} {new_qty}g ...")
            try:
                new_matched_name, new_nutrients = lookup_fn(new_food, new_qty)
                if new_nutrients:
                    print(f"  ✓ Matched: {new_matched_name}")
                    # Recurse to check the corrected entry
                    return resolve_ingredient(new_food, new_qty,
                                              new_nutrients, lookup_fn, config)
                else:
                    print(f"  ✗ No match found for '{new_food}'. Skipping.")
                    return False, new_food, new_qty, {}
            except Exception as e:
                print(f"  ✗ Lookup failed: {e}. Skipping.")
                return False, new_food, new_qty, {}
        else:
            print("  Please enter A, C, or S")


def resolve_daily_totals(totals: dict, log_date: str = "",
                         food_contributions: list = None, config=None) -> bool:
    """
    Interactive sense-check for daily totals.
    Returns True if user accepts, False if user wants to review.
    """
    flags = check_daily_totals(totals, log_date, food_contributions, config)
    if not flags:
        return True

    print()
    print("  ┌─ Daily totals sense check ─────────────────────────")
    _print_flags(flags)
    print("  └─────────────────────────────────────────────────────")
    print()
    print("  [A] Accept and continue")
    print("  [R] Review — I'll check my entries manually")
    print()

    while True:
        choice = input("  Your choice (A/R): ").strip().upper()
        if choice == "A":
            return True
        elif choice == "R":
            print()
            print("  Entries saved. Run python3 query.py to review your logged items.")
            return False
        else:
            print("  Please enter A or R")
