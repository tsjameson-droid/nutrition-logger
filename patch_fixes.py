"""
patch_fixes.py
Applies three fixes:
  1. query.py line 126: pass n100 (per-100g) not scaled to resolve_ingredient
  2. nutrition_logger.py PICK_MATCH_PROMPT: prefer fresh/raw over dried/processed
  3. nutrition_logger.py COFID_LOOKUP: add banana → CoFID 14-318

Run from ~/nutrition-logger:
    python3 patch_fixes.py
"""
import ast

# ─────────────────────────────────────────────────────────
# FIX 1: query.py — pass n100 not scaled to resolve_ingredient
# ─────────────────────────────────────────────────────────
print("Fix 1: query.py — pass nutrients_100g to sense check...")
with open("query.py") as f:
    q = f.read()

old1 = "                _sc_accepted, food, qty_g, _sc_n100 = _sc.resolve_ingredient(\n                    food, qty_g, scaled, _do_lookup)"
new1 = "                _sc_accepted, food, qty_g, _sc_n100 = _sc.resolve_ingredient(\n                    food, qty_g, n100, _do_lookup)"

if old1 in q:
    q = q.replace(old1, new1)
    print("  ✓ Fixed: resolve_ingredient now receives per-100g nutrients")
else:
    # Try to find the line and show context
    lines = q.split('\n')
    for i, line in enumerate(lines):
        if 'resolve_ingredient' in line and 'sc_accepted' in line:
            print(f"  Found at line {i}: {lines[i]}")
            print(f"  Next line {i+1}: {lines[i+1]}")
    print("  WARNING: Could not find exact target — check manually")

try:
    ast.parse(q)
    print("  Syntax OK")
    with open("query.py", "w") as f:
        f.write(q)
except SyntaxError as e:
    print(f"  Syntax error {e.lineno}: {e.msg} — NOT saved")

# ─────────────────────────────────────────────────────────
# FIX 2: nutrition_logger.py — improve PICK_MATCH_PROMPT
# ─────────────────────────────────────────────────────────
print("\nFix 2: nutrition_logger.py — improve pick_best_match prompt...")
with open("nutrition_logger.py") as f:
    n = f.read()

# Find PICK_MATCH_PROMPT
if "PICK_MATCH_PROMPT" not in n:
    print("  ERROR: PICK_MATCH_PROMPT not found in nutrition_logger.py")
else:
    # Find the whole string assignment
    idx = n.find("PICK_MATCH_PROMPT")
    # Find the end of the string (next variable assignment at column 0)
    chunk = n[idx:idx+2000]
    print(f"  Current prompt (first 300 chars):\n  {chunk[:300]}")

    # Build new prompt — find the triple-quoted string
    import re
    m = re.search(r'PICK_MATCH_PROMPT\s*=\s*(""".*?"""|\'\'\'.*?\'\'\')', n, re.DOTALL)
    if m:
        old_prompt = m.group(0)
        new_prompt = '''PICK_MATCH_PROMPT = """You are a food matching assistant. Given a diary entry and a numbered list of database candidates, reply with ONLY the number of the best match, or NONE if nothing is suitable.

CRITICAL RULES:
- Prefer fresh, raw, or whole foods unless the diary entry explicitly says dried, dehydrated, powder, canned, or processed.
- NEVER choose a dried, dehydrated, or powder form when the entry says just the plain food name (e.g. "banana" means fresh banana, NOT banana powder).
- NEVER choose a concentrate, extract, or supplement form for plain food entries.
- Prefer the simplest preparation matching the entry. "banana" → raw banana. "chicken" → raw or cooked chicken, not chicken powder.
- If multiple candidates are equally fresh/raw, prefer the one closest to the exact wording of the diary entry.
- Reply with ONLY a number (e.g. 3) or the word NONE. No explanation."""'''

        if old_prompt in n:
            n = n.replace(old_prompt, new_prompt)
            print("  ✓ PICK_MATCH_PROMPT updated with fresh/raw preference rules")
        else:
            print("  WARNING: Could not match existing prompt exactly")
            print(f"  Found: {old_prompt[:100]}...")
    else:
        print("  ERROR: Could not parse PICK_MATCH_PROMPT string")

# ─────────────────────────────────────────────────────────
# FIX 3: nutrition_logger.py — add banana to COFID_LOOKUP
# ─────────────────────────────────────────────────────────
print("\nFix 3: nutrition_logger.py — add banana to COFID_LOOKUP...")

if '"banana"' in n or "'banana'" in n:
    print("  banana already in COFID_LOOKUP — skipping")
else:
    # Find the Fruit section or insert before closing brace of COFID_LOOKUP
    # Look for a fruit section comment
    if "# Fruit" in n:
        old3 = "    # Fruit"
        new3 = '    # Fruit\n    "banana":                  "14-318",  # Bananas, flesh only'
        if old3 in n:
            n = n.replace(old3, new3, 1)
            print("  ✓ Added banana → CoFID 14-318 under Fruit section")
        else:
            print("  WARNING: '# Fruit' comment found but replace failed")
    else:
        # Insert before the closing of COFID_LOOKUP dict
        # Find end of COFID_LOOKUP by looking for }
        idx = n.find("COFID_LOOKUP = {")
        if idx >= 0:
            # Find the closing brace
            brace_count = 0
            for i, ch in enumerate(n[idx:]):
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        close_idx = idx + i
                        break
            # Insert before closing brace
            insert = '\n    # Fruit\n    "banana":                  "14-318",  # Bananas, flesh only\n'
            n = n[:close_idx] + insert + n[close_idx:]
            print("  ✓ Added banana → CoFID 14-318 to COFID_LOOKUP")
        else:
            print("  ERROR: COFID_LOOKUP not found")

try:
    ast.parse(n)
    print("  Syntax OK")
    with open("nutrition_logger.py", "w") as f:
        f.write(n)
except SyntaxError as e:
    print(f"  Syntax error {e.lineno}: {e.msg} — NOT saved")

print("\nAll fixes applied. Test with:")
print("  python3 query.py")
print("  Enter: banana 150g")
print("  Should match CoFID fresh banana, no sense check needed")
print("  Enter: banana 5000g")
print("  Should match fresh banana AND trigger sense check (quantity too high)")
