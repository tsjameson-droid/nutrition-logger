"""
patch_sense_check.py
Run from ~/nutrition-logger:
    python3 patch_sense_check.py

Wires sense_check.py into:
  - query.py  (per-ingredient check + daily totals check)
  - log_today.py is handled separately by patch_sense_check_log.py
"""

import ast
import os

QUERY = "query.py"


def patch_query():
    with open(QUERY) as f:
        lines = f.read().splitlines()

    # Find the for loop that iterates over items and does lookup
    # We need to find:
    #   1. The MEXT check block start (to wrap it)
    #   2. The per_food.append line (to insert sense check after lookup)
    #   3. The MEAL TOTALS print (to insert daily check before it)

    # Find import block - add sense_check import after existing imports
    last_import = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            last_import = i

    # Check if already patched
    if any("sense_check" in line for line in lines):
        print("query.py already patched with sense_check")
        return False

    # Insert import
    lines.insert(last_import + 1, "import sense_check as _sc")
    print(f"  Added sense_check import at line {last_import + 1}")

    # Re-index after insert
    # Find the per_food.append line
    append_line = None
    for i, line in enumerate(lines):
        if "per_food.append" in line and "food" in line and "qty_g" in line:
            append_line = i
            break

    if append_line is None:
        print("ERROR: Could not find per_food.append line")
        return False

    print(f"  Found per_food.append at line {append_line}: {lines[append_line]}")

    # Get indentation of that line
    indent = len(lines[append_line]) - len(lines[append_line].lstrip())
    I = " " * indent

    # Find what variable holds the matched name and nutrients at that point
    # The MEXT block sets: per_food.append((food, qty_g, _nm_q, scaled))
    # The USDA block sets: per_food.append((food, qty_g, match["description"], scaled))
    # We need to insert BEFORE append, wrapping with sense check

    # Build the lookup function and sense check block
    # Insert before the per_food.append line
    sense_block = [
        I + "# Sense check before logging",
        I + "def _do_lookup(new_food, new_qty):",
        I + "    import mext as _mxt_sc, os as _os_sc, sqlite3 as _sq_sc",
        I + "    _mdb = _os_sc.path.join(_os_sc.path.dirname(_os_sc.path.abspath(__file__)), \"mext.db\")",
        I + "    _mi = _mxt_sc.lookup_mext(new_food.lower().strip())",
        I + "    if _mi and _os_sc.path.exists(_mdb):",
        I + "        _mn2 = _mxt_sc.get_mext_nutrients(_mi, _mdb)",
        I + "        if _mn2:",
        I + "            _c3 = _sq_sc.connect(_mdb)",
        I + "            _r3 = _c3.execute(\"SELECT food_name FROM mext_foods WHERE item_no=?\", (_mi,)).fetchone()",
        I + "            _c3.close()",
        I + "            return (_r3[0] if _r3 else _mi), _mn2",
        I + "    _m2 = search_usda(clean_food_query(new_food, logger.client), config.USDA_KEY)",
        I + "    if _m2:",
        I + "        _n2 = get_usda_nutrients(_m2[\"fdcId\"], config.USDA_KEY)",
        I + "        _n2s = scale_nutrients(_n2, new_qty)",
        I + "        return _m2[\"description\"], _n2",
        I + "    return None, {}",
        I + "_sc_accepted, food, qty_g, _sc_n100 = _sc.resolve_ingredient(",
        I + "    food, qty_g, scaled, _do_lookup)",
        I + "if not _sc_accepted:",
        I + "    continue",
        I + "# Update scaled with potentially corrected nutrients",
        I + "if _sc_n100:",
        I + "    scaled = scale_nutrients(_sc_n100, qty_g)",
    ]

    lines = lines[:append_line] + sense_block + lines[append_line:]
    print(f"  Inserted sense check block before per_food.append ({len(sense_block)} lines)")

    # Now find the MEAL TOTALS print to insert daily check before it
    # Re-scan with updated line numbers
    totals_print = None
    for i, line in enumerate(lines):
        if "MEAL TOTALS" in line and "print" in line:
            totals_print = i
            break

    if totals_print is None:
        print("WARNING: Could not find MEAL TOTALS print — daily check not added")
    else:
        indent2 = len(lines[totals_print]) - len(lines[totals_print].lstrip())
        I2 = " " * indent2

        # Build food_contributions list from per_food
        daily_block = [
            I2 + "# Daily totals sense check",
            I2 + "_food_contribs = [(f, s.get(\"energy_kcal\", 0) or 0) for f, _, _, s in per_food]",
            I2 + "_sc.resolve_daily_totals(totals, food_contributions=_food_contribs)",
            I2 + "",
        ]

        lines = lines[:totals_print] + daily_block + lines[totals_print:]
        print(f"  Inserted daily totals check before MEAL TOTALS at line {totals_print}")

    new_content = "\n".join(lines)

    try:
        ast.parse(new_content)
        print("  Syntax OK")
        with open(QUERY, "w") as f:
            f.write(new_content)
        return True
    except SyntaxError as e:
        print(f"  Syntax error at line {e.lineno}: {e.msg}")
        ctx = new_content.splitlines()
        for j in range(max(0, e.lineno - 3), min(len(ctx), e.lineno + 3)):
            print(f"    {j+1}: {ctx[j]}")
        print("  File NOT saved.")
        return False


if __name__ == "__main__":
    print("Patching query.py with sense checking...")
    ok = patch_query()
    if ok:
        print("\nDone. Test with:")
        print("  python3 query.py")
        print("  Choose 1, enter a food with a suspicious quantity (e.g. 'broccoli 5000g')")
        print("  You should see the sense check fire and ask A/C/S")
    else:
        print("\nPatch failed or already applied.")
