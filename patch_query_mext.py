"""
patch_query_mext.py
Run from ~/nutrition-logger:
    python3 patch_query_mext.py
"""
import ast

with open("query.py") as f:
    lines = f.read().splitlines()

# Show lines around the search_usda call
print("Lines around the food lookup in query.py:")
for i, line in enumerate(lines):
    if "search_usda" in line or "get_usda_nutrients" in line or "usda_name" in line:
        for j in range(max(0, i-3), min(len(lines), i+5)):
            print(f"  {j}: {lines[j]}")
        print()

# Find the target: "term = clean_food_query..." or the search_usda call
target = None
for i, line in enumerate(lines):
    if "search_usda" in line and "match" in line:
        target = i
        break

if target is None:
    # Try finding by context
    for i, line in enumerate(lines):
        if "search_usda" in line:
            target = i
            break

if target is None:
    print("ERROR: Could not find search_usda call")
    raise SystemExit(1)

print(f"Found search_usda call at line {target}: {lines[target]}")

# Find the clean_food_query call just before it
clean_line = None
for i in range(target-1, max(0, target-5), -1):
    if "clean_food_query" in lines[i]:
        clean_line = i
        break

if clean_line is None:
    print("clean_food_query not found before search_usda, inserting MEXT check before search_usda")
    insert_at = target
else:
    print(f"Found clean_food_query at line {clean_line}: {lines[clean_line]}")
    insert_at = clean_line

# Get the indentation from the target line
indent = len(lines[insert_at]) - len(lines[insert_at].lstrip())
I = " " * indent

# Build the MEXT replacement block
replacement = [
    I + "# MEXT lookup for Japanese foods",
    I + "import mext as _mxt_q",
    I + "import os as _os_q",
    I + "import sqlite3 as _sq_q",
    I + '_mdb_q = _os_q.path.join(_os_q.path.dirname(_os_q.path.abspath(__file__)), "mext.db")',
    I + "_mi_q = _mxt_q.lookup_mext(food.lower().strip())",
    I + "if _mi_q and _os_q.path.exists(_mdb_q):",
    I + "    _mn_q = _mxt_q.get_mext_nutrients(_mi_q, _mdb_q)",
    I + "    if _mn_q:",
    I + "        _c_q = _sq_q.connect(_mdb_q)",
    I + '        _r_q = _c_q.execute("SELECT food_name FROM mext_foods WHERE item_no=?", (_mi_q,)).fetchone()',
    I + "        _c_q.close()",
    I + "        _nm_q = _r_q[0] if _r_q else _mi_q",
    I + '        print("     ✓ [MEXT] " + _nm_q)',
    I + "        scaled = {k: v * qty_g / 100.0 for k, v in _mn_q.items() if v is not None}",
    I + "        per_food.append((food, qty_g, _nm_q, scaled))",
    I + "        continue",
]

# Keep the original lines from insert_at onwards
new_lines = lines[:insert_at] + replacement + lines[insert_at:]
new_content = "\n".join(new_lines)

try:
    ast.parse(new_content)
    print("Syntax OK — saving query.py")
    with open("query.py", "w") as f:
        f.write(new_content)
    print("Done. Test with: python3 query.py")
except SyntaxError as e:
    print(f"Syntax error at line {e.lineno}: {e.msg}")
    # Show context
    nc_lines = new_content.splitlines()
    for j in range(max(0, e.lineno-3), min(len(nc_lines), e.lineno+3)):
        print(f"  {j+1}: {nc_lines[j]}")
    print("File NOT saved.")
