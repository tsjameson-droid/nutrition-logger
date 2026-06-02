"""
patch_mext.py
Run from ~/nutrition-logger:
    python3 patch_mext.py
"""
import ast

with open("nutrition_logger.py") as f:
    lines = f.read().splitlines()

# Find the target line
target = None
for i, line in enumerate(lines):
    if "# Clean the food name into a USDA-friendly search term" in line:
        target = i
        break

if target is None:
    print("ERROR: Could not find target line. Already patched?")
    raise SystemExit(1)

print(f"Found target at line {target}")
print("Lines being replaced:")
for j in range(target, min(target + 11, len(lines))):
    print(f"  {j}: {lines[j]}")

# The replacement block — 12 spaces indent to match surrounding code
I = "            "
replacement = [
    I + "# MEXT lookup: check Japanese DB before transforming the food name",
    I + "import mext as _mxt",
    I + "import os as _os",
    I + "import sqlite3 as _sq",
    I + '_mdb = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "mext.db")',
    I + "_mi = _mxt.lookup_mext(food_name_raw.lower().strip())",
    I + "if _mi and _os.path.exists(_mdb):",
    I + "    _mn = _mxt.get_mext_nutrients(_mi, _mdb)",
    I + "    if _mn:",
    I + "        _c2 = _sq.connect(_mdb)",
    I + '        _r2 = _c2.execute("SELECT food_name FROM mext_foods WHERE item_no=?", (_mi,)).fetchone()',
    I + "        _c2.close()",
    I + "        _nm = _r2[0] if _r2 else _mi",
    I + '        print("     \u2713 [MEXT] " + _nm)',
    I + '        result = {"source": "mext", "name": _nm, "match": {}, "nutrients_100g": _mn}',
    I + "    else:",
    I + "        _mi = None",
    I + "if not _mi or not _os.path.exists(_mdb):",
    I + "    # Clean the food name into a USDA-friendly search term",
    I + "    search_term = clean_food_query(food_name_raw, self.client)",
    I + '    print("     \u27f3 Search term: " + repr(search_term))',
    I + "    # Search USDA + CoFID — Claude picks best match",
    I + "    result = search_all_databases(",
    I + "        search_term, self.usda_key,",
    I + "        original_food=food_name_raw,",
    I + "        client=self.client",
    I + "    )",
]

# Replace lines target through target+10 (11 lines)
new_lines = lines[:target] + replacement + lines[target + 11:]
new_content = "\n".join(new_lines)

try:
    ast.parse(new_content)
    print("Syntax OK — saving")
    with open("nutrition_logger.py", "w") as f:
        f.write(new_content)
    print("Done. Test with: python3 query.py")
except SyntaxError as e:
    print(f"Syntax error at line {e.lineno}: {e.msg}")
    print("File NOT saved.")
