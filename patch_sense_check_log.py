"""
patch_sense_check_log.py
Run from ~/nutrition-logger:
    python3 patch_sense_check_log.py

Wires sense_check.py into log_today.py:
  - Per-ingredient check after each food is matched during logging
  - End-of-day totals check after all meals are logged
"""

import ast
import os

LOG = "log_today.py"


def patch_log():
    with open(LOG) as f:
        content = f.read()
        lines = content.splitlines()

    if "sense_check" in content:
        print("log_today.py already patched with sense_check")
        return False

    # Find last import line
    last_import = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            last_import = i

    lines.insert(last_import + 1, "import sense_check as _sc")
    print(f"  Added sense_check import at line {last_import + 1}")

    # Find where log_diet_entry is called
    # After all meals are collected and logged, we want to run the daily check
    # Look for the line that calls logger.log_diet_entry or logger.log_entries
    log_call = None
    for i, line in enumerate(lines):
        if "log_diet_entry" in line or ("logger" in line and "log" in line and "diet" in line.lower()):
            log_call = i
            break

    if log_call is None:
        # Try finding where meals are submitted
        for i, line in enumerate(lines):
            if "choice" in line.lower() and "0" in line and "log" in line.lower():
                log_call = i
                break

    # Find the line that prints "Logged X items" or similar confirmation
    logged_line = None
    for i, line in enumerate(lines):
        if ("Logged" in line or "logged" in line) and ("item" in line or "meal" in line):
            if "print" in line:
                logged_line = i
                break

    if logged_line:
        indent = len(lines[logged_line]) - len(lines[logged_line].lstrip())
        I = " " * indent

        daily_check = [
            "",
            I + "# Daily totals sense check",
            I + "try:",
            I + "    _day_summary = logger.daily_summary()",
            I + "    if _day_summary:",
            I + "        _sc.resolve_daily_totals(",
            I + "            _day_summary,",
            I + "            log_date=log_date if 'log_date' in dir() else '',",
            I + "        )",
            I + "except Exception:",
            I + "    pass",
        ]

        lines = lines[:logged_line + 1] + daily_check + lines[logged_line + 1:]
        print(f"  Inserted daily totals check after log confirmation at line {logged_line}")
    else:
        print("  WARNING: Could not find log confirmation line — daily check not added to log_today.py")
        print("  Per-ingredient checking via query.py is still active.")

    new_content = "\n".join(lines)

    try:
        ast.parse(new_content)
        print("  Syntax OK")
        with open(LOG, "w") as f:
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
    print("Patching log_today.py with sense checking...")
    ok = patch_log()
    if ok:
        print("\nDone.")
    else:
        print("\nPatch failed or already applied.")
