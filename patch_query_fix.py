"""
patch_query_fix.py
Two targeted fixes to query.py:
  1. MEXT branch: pass _mn_q (per-100g) to resolve_ingredient, not undefined n100
  2. Non-MEXT branch: use search_all_databases instead of search_usda
     so CoFID lookup (including banana) fires correctly

Run from ~/nutrition-logger:
    python3 patch_query_fix.py
"""
import ast

with open("query.py") as f:
    content = f.read()

# ── FIX 1: MEXT branch passes undefined n100, should pass _mn_q ──────────────
old1 = ("                _sc_accepted, food, qty_g, _sc_n100 = _sc.resolve_ingredient(\n"
        "                    food, qty_g, n100, _do_lookup)")
new1 = ("                _sc_accepted, food, qty_g, _sc_n100 = _sc.resolve_ingredient(\n"
        "                    food, qty_g, _mn_q, _do_lookup)")

if old1 in content:
    content = content.replace(old1, new1)
    print("Fix 1 applied: MEXT branch now passes _mn_q to resolve_ingredient")
else:
    print("Fix 1: already applied or not found — checking current state")
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'resolve_ingredient' in line:
            print(f"  Line {i}: {lines[i]}")
            print(f"  Line {i+1}: {lines[i+1]}")

# ── FIX 2: Replace search_usda path with search_all_databases ─────────────────
# The current non-MEXT block looks like:
#     term = clean_food_query(food, logger.client)
#     match = search_usda(term, config.USDA_KEY)
#     if not match:
#         print(f"  ✗ No match found for: {food}")
#         continue
#     n100 = get_usda_nutrients(match["fdcId"], config.USDA_KEY)
#     scaled = scale_nutrients(n100, qty_g)
#     per_food.append((food, qty_g, match["description"], scaled))
#     for name, _ in NUTRIENTS:
#         totals[name] += scaled.get(name) or 0.0
#
# Replace with search_all_databases which checks CoFID lookup first

old2 = ('        term = clean_food_query(food, logger.client)\n'
        '        match = search_usda(term, config.USDA_KEY)\n'
        '        if not match:\n'
        '            print(f"  ✗ No match found for: {food}")\n'
        '            continue\n'
        '        n100 = get_usda_nutrients(match["fdcId"], config.USDA_KEY)\n'
        '        scaled = scale_nutrients(n100, qty_g)\n'
        '        per_food.append((food, qty_g, match["description"], scaled))\n'
        '        for name, _ in NUTRIENTS:\n'
        '            totals[name] += scaled.get(name) or 0.0')

new2 = ('        term = clean_food_query(food, logger.client)\n'
        '        result = search_all_databases(term, config.USDA_KEY,\n'
        '                                      original_food=food,\n'
        '                                      client=logger.client)\n'
        '        if not result:\n'
        '            print(f"  ✗ No match found for: {food}")\n'
        '            continue\n'
        '        n100 = result["nutrients_100g"]\n'
        '        matched_name = result["name"]\n'
        '        # Sense check on per-100g nutrients\n'
        '        def _do_lookup2(new_food, new_qty):\n'
        '            r2 = search_all_databases(clean_food_query(new_food, logger.client),\n'
        '                                      config.USDA_KEY,\n'
        '                                      original_food=new_food,\n'
        '                                      client=logger.client)\n'
        '            if r2:\n'
        '                return r2["name"], r2["nutrients_100g"]\n'
        '            return None, {}\n'
        '        _sc2_ok, food, qty_g, _sc2_n100 = _sc.resolve_ingredient(\n'
        '            food, qty_g, n100, _do_lookup2)\n'
        '        if not _sc2_ok:\n'
        '            continue\n'
        '        if _sc2_n100:\n'
        '            n100 = _sc2_n100\n'
        '        scaled = scale_nutrients(n100, qty_g)\n'
        '        per_food.append((food, qty_g, matched_name, scaled))\n'
        '        for name, _ in NUTRIENTS:\n'
        '            totals[name] += scaled.get(name) or 0.0')

if old2 in content:
    content = content.replace(old2, new2)
    print("Fix 2 applied: non-MEXT branch now uses search_all_databases")
else:
    print("Fix 2: could not find exact target — showing current non-MEXT block:")
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'search_usda' in line and 'config' in line:
            for j in range(max(0, i-2), min(len(lines), i+12)):
                print(f"  {j}: {lines[j]}")
            break

# Also need to import search_all_databases in query.py if not already there
if 'search_all_databases' not in content.split('from nutrition_logger')[1].split('\n')[0] if 'from nutrition_logger' in content else '':
    old_import = 'from nutrition_logger import NutritionLogger, search_usda, get_usda_nutrients, scale_nutrients, clean_food_query'
    new_import = 'from nutrition_logger import NutritionLogger, search_usda, search_all_databases, get_usda_nutrients, scale_nutrients, clean_food_query'
    if old_import in content:
        content = content.replace(old_import, new_import)
        print("Fix 3 applied: added search_all_databases to imports")
    else:
        # Check what import line looks like
        for line in content.split('\n')[:20]:
            if 'from nutrition_logger' in line:
                print(f"  Current import: {line}")
                if 'search_all_databases' in line:
                    print("  search_all_databases already imported")

try:
    ast.parse(content)
    print("Syntax OK — saving")
    with open("query.py", "w") as f:
        f.write(content)
    print("\nDone. Test with:")
    print("  python3 query.py")
    print("  Enter: banana 150g")
    print("  Should now match: Bananas, flesh only (CoFID, ~89 kcal/100g)")
    print("  No sense check flag expected for reasonable quantity")
except SyntaxError as e:
    print(f"Syntax error at line {e.lineno}: {e.msg} — NOT saved")
    lines = content.split('\n')
    for j in range(max(0, e.lineno-3), min(len(lines), e.lineno+3)):
        print(f"  {j+1}: {lines[j]}")
