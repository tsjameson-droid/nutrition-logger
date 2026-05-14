"""
nutrition_logger/db.py
========================
Database layer. Env-gated path, schema, migrations.

Environment:
    NUTRITION_LOGGER_ENV = prod (default) | test
    NUTRITION_LOGGER_DB_DIR = override DB directory (optional)
"""

import os
import sqlite3
from pathlib import Path

# ── Environment ───────────────────────────────────────────────────────────────

ENV = os.environ.get("NUTRITION_LOGGER_ENV", "prod").lower()

if ENV not in ("prod", "test"):
    raise ValueError(f"NUTRITION_LOGGER_ENV must be 'prod' or 'test', got: {ENV}")

IS_TEST = ENV == "test"

def get_db_dir() -> Path:
    override = os.environ.get("NUTRITION_LOGGER_DB_DIR")
    if override:
        return Path(override).expanduser()
    return Path("~/projects/nutrition-logger/data").expanduser()

def get_db_path() -> Path:
    db_dir = get_db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    filename = "nutrition_log_test.db" if IS_TEST else "nutrition_log.db"
    return db_dir / filename

def get_cofid_path() -> Path:
    """CoFID database lives alongside the main DB."""
    candidates = [
        get_db_dir() / "cofid.db",
        Path(__file__).parent.parent / "data" / "cofid.db",
        Path("cofid.db"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

# ── Schema ────────────────────────────────────────────────────────────────────

NUTRIENT_COLUMNS = [
    "energy_kcal", "protein_g", "fat_total_g", "carbohydrate_g",
    "fibre_g", "sugars_g", "saturated_fat_g", "monounsaturated_fat_g",
    "polyunsaturated_fat_g", "trans_fat_g", "omega3_ala_g", "omega3_epa_g",
    "omega3_dpa_g", "omega3_dha_g", "calcium_mg", "iron_mg", "magnesium_mg",
    "phosphorus_mg", "potassium_mg", "sodium_mg", "zinc_mg", "copper_mg",
    "manganese_mg", "selenium_ug", "iodine_ug", "vitamin_a_ug_rae",
    "vitamin_c_mg", "vitamin_d_ug", "vitamin_e_mg", "vitamin_k_ug",
    "thiamin_mg", "riboflavin_mg", "niacin_mg", "pantothenic_acid_mg",
    "vitamin_b6_mg", "folate_ug", "vitamin_b12_ug", "choline_mg",
    "tryptophan_g", "threonine_g", "isoleucine_g", "leucine_g",
    "lysine_g", "methionine_g", "phenylalanine_g", "valine_g",
    "arginine_g", "glycine_g", "proline_g", "glutamic_acid_g",
]

_NUTRIENT_COLS_DDL = "\n".join(f"    {col} REAL," for col in NUTRIENT_COLUMNS)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS diet_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id          TEXT,
    user_id             TEXT NOT NULL DEFAULT 'gabriel',
    log_date            TEXT NOT NULL,
    meal_time           TEXT,
    meal_category       TEXT,
    source              TEXT DEFAULT 'terminal',
    food_name_raw       TEXT,
    food_name_matched   TEXT,
    fdc_id              INTEGER,
    db_source           TEXT,
    quantity_g          REAL,
    unit_original       TEXT,
    shorthand_matched   INTEGER DEFAULT 0,
    parse_confidence    REAL DEFAULT 1.0,
    ambiguity_note      TEXT,
    logged_at           TEXT NOT NULL,
{_NUTRIENT_COLS_DDL}
    notes               TEXT
)
"""

MIGRATIONS = [
    # Each entry: (column_name, column_def)
    # Applied once if column doesn't exist — safe to run repeatedly
    ("command_id",        "TEXT"),
    ("user_id",           "TEXT NOT NULL DEFAULT 'gabriel'"),
    ("source",            "TEXT DEFAULT 'terminal'"),
    ("food_name_matched", "TEXT"),
    ("db_source",         "TEXT"),
    ("shorthand_matched", "INTEGER DEFAULT 0"),
    ("parse_confidence",  "REAL DEFAULT 1.0"),
    ("ambiguity_note",    "TEXT"),
    ("meal_category",     "TEXT"),
]

# ── Connection ────────────────────────────────────────────────────────────────

def get_connection(db_path=None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=None) -> sqlite3.Connection:
    """Initialise or migrate the database. Safe to call on every startup."""
    conn = get_connection(db_path)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()

    # Apply migrations
    existing = {row[1] for row in conn.execute("PRAGMA table_info(diet_log)")}
    for col_name, col_def in MIGRATIONS:
        if col_name not in existing:
            try:
                conn.execute(f"ALTER TABLE diet_log ADD COLUMN {col_name} {col_def}")
                conn.commit()
            except Exception:
                pass  # column may already exist under different def

    return conn

# ── Insert / fetch helpers ────────────────────────────────────────────────────

def insert_row(conn: sqlite3.Connection, row: dict):
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO diet_log ({cols}) VALUES ({placeholders})", list(row.values()))
    conn.commit()

def fetch_rows(conn: sqlite3.Connection, log_date: str, user_id: str = "gabriel") -> list:
    rows = conn.execute(
        "SELECT * FROM diet_log WHERE log_date = ? AND user_id = ? ORDER BY meal_time",
        (log_date, user_id)
    ).fetchall()
    return [dict(r) for r in rows]

def fetch_rows_range(conn: sqlite3.Connection, start_date: str, end_date: str,
                     user_id: str = "gabriel") -> list:
    rows = conn.execute(
        "SELECT * FROM diet_log WHERE log_date >= ? AND log_date <= ? AND user_id = ? ORDER BY log_date, meal_time",
        (start_date, end_date, user_id)
    ).fetchall()
    return [dict(r) for r in rows]

def daily_totals(conn: sqlite3.Connection, log_date: str, user_id: str = "gabriel") -> dict:
    cols = ", ".join(f"SUM({c}) as {c}" for c in NUTRIENT_COLUMNS)
    row = conn.execute(
        f"SELECT {cols} FROM diet_log WHERE log_date = ? AND user_id = ?",
        (log_date, user_id)
    ).fetchone()
    return {k: round(v, 3) if v is not None else None for k, v in dict(row).items()}
