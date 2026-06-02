"""
build_mext_db.py
================
Run once to build mext.db from the MEXT 2015 Excel file.

Usage:
    python3 build_mext_db.py mext_2015.xlsx
    python3 build_mext_db.py mext_2015.xlsx --output /path/to/mext.db
"""

import sys
import sqlite3
import argparse

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip3 install openpyxl")
    sys.exit(1)


# Map from Excel column index (0-based) to (db_column_name, sqlite_type)
COL_MAP = {
    0:  ('food_group',       'TEXT'),
    1:  ('item_no',          'TEXT'),
    2:  ('index_no',         'INTEGER'),
    3:  ('food_name',        'TEXT'),
    4:  ('refuse_pct',       'REAL'),
    5:  ('energy_kcal',      'REAL'),
    6:  ('energy_kj',        'REAL'),
    7:  ('water_g',          'REAL'),
    9:  ('protein_g',        'REAL'),  # amino-acid based protein (preferred)
    10: ('fat_g',            'REAL'),
    12: ('sat_fat_g',        'REAL'),
    13: ('mono_fat_g',       'REAL'),
    14: ('poly_fat_g',       'REAL'),
    15: ('cholesterol_mg',   'REAL'),
    16: ('carbs_g',          'REAL'),
    18: ('fibre_sol_g',      'REAL'),
    19: ('fibre_insol_g',    'REAL'),
    20: ('fibre_total_g',    'REAL'),
    22: ('sodium_mg',        'REAL'),
    23: ('potassium_mg',     'REAL'),
    24: ('calcium_mg',       'REAL'),
    25: ('magnesium_mg',     'REAL'),
    26: ('phosphorus_mg',    'REAL'),
    27: ('iron_mg',          'REAL'),
    28: ('zinc_mg',          'REAL'),
    29: ('copper_mg',        'REAL'),
    30: ('manganese_mg',     'REAL'),
    31: ('iodine_ug',        'REAL'),
    32: ('selenium_ug',      'REAL'),
    35: ('retinol_ug',       'REAL'),
    37: ('beta_carotene_ug', 'REAL'),
    40: ('vita_rae_ug',      'REAL'),
    41: ('vitamin_d_ug',     'REAL'),
    42: ('vitamin_e_mg',     'REAL'),
    46: ('vitamin_k_ug',     'REAL'),
    47: ('thiamin_mg',       'REAL'),
    48: ('riboflavin_mg',    'REAL'),
    49: ('niacin_mg',        'REAL'),
    50: ('vitamin_b6_mg',    'REAL'),
    51: ('vitamin_b12_ug',   'REAL'),
    52: ('folate_ug',        'REAL'),
    53: ('pantothenic_mg',   'REAL'),
    54: ('biotin_ug',        'REAL'),
    55: ('vitamin_c_mg',     'REAL'),
    57: ('alcohol_g',        'REAL'),
    60: ('caffeine_mg',      'REAL'),
}

SORTED_COLS = sorted(COL_MAP.keys())


def clean_val(v, col_type):
    """Convert MEXT cell values to Python types.
    
    MEXT uses:
    - None / blank  -> NULL
    - '-'           -> NULL (not measured / not applicable)
    - 'Tr' / '(Tr)' -> 0.0 (trace amount)
    - '(0)'         -> 0.0
    - '(x.x)'       -> x.x (estimated value, parentheses = less reliable but valid)
    """
    if v is None:
        return None
    s = str(v).strip()
    if s in ('', '-'):
        return None
    if col_type == 'TEXT':
        return s
    if s in ('Tr', 'tr', '(0)', '(Tr)'):
        return 0.0
    s = s.strip('()')
    try:
        return float(s)
    except ValueError:
        return None


def build(xlsx_path, db_path):
    print(f"Loading {xlsx_path} ...")
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    print(f"  Sheet: {ws.title}")

    conn = sqlite3.connect(db_path)
    conn.execute('DROP TABLE IF EXISTS mext_foods')

    col_defs = ', '.join(f"{COL_MAP[i][0]} {COL_MAP[i][1]}" for i in SORTED_COLS)
    conn.execute(f'''
        CREATE TABLE mext_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {col_defs},
            food_name_lower TEXT
        )
    ''')
    conn.execute('CREATE INDEX idx_mext_name ON mext_foods(food_name_lower)')

    col_names = [COL_MAP[i][0] for i in SORTED_COLS] + ['food_name_lower']
    placeholders = ', '.join('?' for _ in col_names)
    insert_sql = f"INSERT INTO mext_foods ({', '.join(col_names)}) VALUES ({placeholders})"

    inserted = 0
    skipped = 0

    for row in ws.iter_rows(min_row=9, values_only=True):
        # Skip header/blank rows — data rows have a numeric item_no like '04046'
        if not row[1] or not str(row[1]).strip():
            skipped += 1
            continue
        if not row[3]:
            skipped += 1
            continue

        row_vals = []
        for col_idx in SORTED_COLS:
            col_type = COL_MAP[col_idx][1]
            raw = row[col_idx] if col_idx < len(row) else None
            row_vals.append(clean_val(raw, col_type))

        food_name = str(row[3]).strip()
        row_vals.append(food_name.lower())

        conn.execute(insert_sql, row_vals)
        inserted += 1

    conn.commit()
    conn.close()

    print(f"  Inserted: {inserted} foods")
    print(f"  Skipped:  {skipped} blank/header rows")
    print(f"  Output:   {db_path}")
    print("Done.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build mext.db from MEXT 2015 Excel')
    parser.add_argument('xlsx', help='Path to mext_2015.xlsx')
    parser.add_argument('--output', default='mext.db', help='Output SQLite path (default: mext.db)')
    args = parser.parse_args()
    build(args.xlsx, args.output)
