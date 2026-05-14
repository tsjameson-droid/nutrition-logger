"""
nutrition_logger/core.py
=========================
Pure library functions. No I/O, no blocking, no input().

Public API:
    parse(text, user_id)             -> list[dict]
    log(text, user_id, ...)          -> dict
    answer(question, user_id)        -> str
    query(question, user_id)         -> dict
"""

import re
import json
import uuid
import datetime
import logging

import anthropic

from . import db as _db
from . import shorthand as _sh
from . import hds as _hds
from .lookup import lookup_food, clean_query, scale_nutrients, to_grams
from .format import confirmation_slack, query_reply_slack, daily_total_line

logger = logging.getLogger(__name__)

# ── Client ────────────────────────────────────────────────────────────────────

_client_cache = None

def _client() -> anthropic.Anthropic:
    global _client_cache
    if _client_cache is None:
        import os
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            try:
                import config as c; key = c.ANTHROPIC_KEY
            except ImportError:
                pass
        _client_cache = anthropic.Anthropic(api_key=key)
    return _client_cache

# ── Parse ─────────────────────────────────────────────────────────────────────

PARSE_SYSTEM = """You are a dietary analysis assistant.
Convert a food log into a JSON array. For each food item output:
{
  "time": "HH:MM or null",
  "meal": "breakfast|lunch|dinner|snack|supplement",
  "food": "concise English food description",
  "quantity": <number or null>,
  "unit": "g|ml|oz|slice|piece|handful|tbsp|tsp|cup"
}
Rules:
- Split composite meals into separate ingredients
- Infer meal from time (before 11=breakfast, 11-15=lunch, 15-18=snack, after 18=dinner)
- If quantity unknown, use null
- Preserve bean origin verbatim (e.g. "Costa Rica espresso" not just "espresso")
- For espresso: if a gram weight is stated, use it exactly — do not substitute a default
- Output ONLY the JSON array
"""

def parse(text: str, user_id: str = "gabriel") -> list:
    """
    Best-effort parse of free-text food log.

    Process:
    1. Check each line for shorthand patterns (additive — shorthand emits
       extra rows alongside literal items, not instead of them)
    2. Check for special cases (eaten_out → flag, no macro lookup)
    3. Parse remaining lines with Claude
    4. Apply parsing rules (espresso weight, bean origin)

    Returns list of item dicts:
    {
        food, quantity, unit, time, meal,
        _shorthand_matched, _shorthand_family,
        _shorthand_macros,   # direct macros from YAML (may contain nulls)
        _eat_out,
        _confidence,
        _ambiguity_note,
    }
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    items = []

    # Remove meal-tag headers like [BREAKFAST]
    content_lines = []
    current_meal = None
    for line in lines:
        tag = re.match(r'^\[([A-Z]+)\]', line)
        if tag:
            current_meal = tag.group(1).lower()
            rest = line[tag.end():].strip()
            if rest:
                content_lines.append((rest, current_meal))
        else:
            content_lines.append((line, current_meal))

    # Check special cases first
    full_text_lower = text.lower()
    special = _sh.check_special_cases(full_text_lower)
    eat_out = special is not None and special["name"] == "eaten_out"

    # Shorthand check (per line — additive)
    shorthand_expansions = []
    non_shorthand = []
    for line, meal_hint in content_lines:
        expansion = _sh.expand(line)
        if expansion:
            for item in expansion["items"]:
                shorthand_expansions.append({
                    "food": item["label"],
                    "quantity": item.get("dose_ml", 100),
                    "unit": "ml",
                    "time": None,
                    "meal": meal_hint,
                    "_shorthand_matched": True,
                    "_shorthand_family": expansion["family"],
                    "_shorthand_macros": item,  # direct macros, nulls intact
                    "_eat_out": eat_out,
                    "_confidence": 1.0,
                    "_ambiguity_note": None,
                })
            # Also keep the literal line for Claude to parse the non-milk parts
            non_shorthand.append((line, meal_hint))
        else:
            non_shorthand.append((line, meal_hint))

    # Claude parse of non-shorthand lines
    if non_shorthand:
        text_for_claude = "\n".join(
            (f"[{hint.upper()}] " if hint else "") + l
            for l, hint in non_shorthand
        )
        try:
            resp = _client().messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                system=PARSE_SYSTEM,
                messages=[{"role": "user", "content": text_for_claude}]
            )
            raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
            parsed = json.loads(raw)
            for item in parsed:
                # Apply espresso shot weight rule
                shot_g = _sh.extract_shot_weight_g(item.get("food", ""))
                if shot_g is not None and "espresso" in item.get("food", "").lower():
                    item["quantity"] = shot_g
                    item["unit"] = "g"
                # Apply bean origin rule — food name preserved as-is from parser
                item["_shorthand_matched"] = False
                item["_shorthand_family"] = None
                item["_shorthand_macros"] = None
                item["_eat_out"] = eat_out
                item["_confidence"] = 0.9
                item["_ambiguity_note"] = None
                if eat_out:
                    item["_ambiguity_note"] = "eaten_out: composition unknown"
        except Exception as e:
            logger.warning(f"Parse error: {e}")
            parsed = []
        items.extend(parsed)

    items.extend(shorthand_expansions)
    return items


# ── Log ────────────────────────────────────────────────────────────────────────

def log(
    text: str,
    user_id: str = "gabriel",
    log_date: str = None,
    source: str = "terminal",
    command_id: str = None,
    reply_channel: str = "terminal",
) -> dict:
    """
    Parse food text, look up nutrients, store in SQLite, enqueue HDS event.

    Shorthand items use YAML macros directly — no DB lookup.
    Koji nulls stay null — no fallback lookup to fill missing fields.
    eat_out items are tagged and skipped for macro lookup.

    Returns:
    {
        "logged":   [list of row dicts written to DB],
        "skipped":  [items that couldn't be matched],
        "reply":    terse confirmation string (channel-aware),
        "totals":   today's running nutrient totals,
    }
    """
    if log_date is None:
        log_date = datetime.date.today().isoformat()
    if command_id is None:
        command_id = str(uuid.uuid4())
    logged_at = datetime.datetime.now().isoformat()

    conn = _db.init_db()
    logged_rows = []
    skipped = []

    parsed_items = parse(text, user_id)

    for item in parsed_items:
        food_raw   = item.get("food", "")
        quantity   = item.get("quantity")
        unit       = item.get("unit", "g")
        meal_time  = item.get("time")
        meal_cat   = item.get("meal")
        shorthand  = item.get("_shorthand_matched", False)
        sh_macros  = item.get("_shorthand_macros")
        eat_out    = item.get("_eat_out", False)
        confidence = item.get("_confidence", 0.9)
        ambiguity  = item.get("_ambiguity_note")

        qty_g = to_grams(quantity, unit) if quantity else None

        # Build nutrient dict
        nutrients = {}

        if shorthand and sh_macros:
            # Use YAML macros directly — nulls stay null, no fallback
            nutrients = _sh.item_to_nutrients(sh_macros)
            food_matched = sh_macros.get("label", food_raw)
            db_source = "shorthand_yaml"
            fdc_id = None

        elif eat_out:
            # Flag only — no macro lookup
            food_matched = food_raw
            db_source = None
            fdc_id = None
            if not ambiguity:
                ambiguity = "eaten_out: composition unknown"

        else:
            # Standard DB lookup
            try:
                query_term = clean_query(food_raw, _client())
                result = lookup_food(query_term, food_raw, _client())
            except Exception as e:
                logger.warning(f"Lookup failed for '{food_raw}': {e}")
                result = None

            if result:
                n100 = result["nutrients_100g"]
                nutrients = scale_nutrients(n100, qty_g) if qty_g else n100
                food_matched = result["name"]
                db_source = result["source"]
                fdc_id = result.get("match", {}).get("fdcId") if db_source == "usda" else None
            else:
                food_matched = food_raw
                db_source = None
                fdc_id = None
                ambiguity = (ambiguity or "") + " no_db_match"
                skipped.append(food_raw)

        # Build DB row
        row = {
            "command_id":       command_id,
            "user_id":          user_id,
            "log_date":         log_date,
            "meal_time":        meal_time,
            "meal_category":    meal_cat,
            "source":           source,
            "food_name_raw":    food_raw,
            "food_name_matched": food_matched,
            "fdc_id":           fdc_id,
            "db_source":        db_source,
            "quantity_g":       qty_g,
            "unit_original":    unit,
            "shorthand_matched": 1 if shorthand else 0,
            "parse_confidence": confidence,
            "ambiguity_note":   ambiguity,
            "logged_at":        logged_at,
        }
        for col in _db.NUTRIENT_COLUMNS:
            row[col] = nutrients.get(col)  # None if not present

        _db.insert_row(conn, row)
        logged_rows.append(row)

        # HDS queue — fire and forget
        _hds.write_food_intake_event(
            user_id=user_id,
            log_date=log_date,
            meal_time=meal_time,
            meal_category=meal_cat,
            food_name_raw=food_raw,
            food_name_matched=food_matched,
            quantity_g=qty_g,
            nutrients=nutrients,
            db_row_id=conn.execute("SELECT last_insert_rowid()").fetchone()[0],
            shorthand_matched=shorthand,
            parse_confidence=confidence,
            ambiguity_note=ambiguity,
            source=source,
            command_id=command_id,
        )

    # Today's running totals
    totals = _db.daily_totals(conn, log_date, user_id)
    conn.close()

    reply = confirmation_slack(logged_rows, totals)

    return {
        "logged":  logged_rows,
        "skipped": skipped,
        "reply":   reply,
        "totals":  totals,
    }


# ── Answer (natural language) ─────────────────────────────────────────────────

ANSWER_SYSTEM = """You are a clinical nutrition analyst.
You have food log data for a user. Answer the question precisely using
specific foods, dates, and numeric values. Use UK RNIs as reference where
relevant. Be concise — numbers first, context second. UK English."""

def answer(question: str, user_id: str = "gabriel",
           days_back: int = 1, log_date: str = None) -> str:
    """
    Natural language answer from DB. Consistent shape with confirmation replies:
    if it's a 'what did I eat today' query, uses query_reply_slack format.
    """
    if log_date is None:
        log_date = datetime.date.today().isoformat()

    conn = _db.init_db()
    start = (datetime.date.fromisoformat(log_date)
             - datetime.timedelta(days=days_back - 1)).isoformat()
    rows = _db.fetch_rows_range(conn, start, log_date, user_id)
    totals = _db.daily_totals(conn, log_date, user_id)
    conn.close()

    if not rows:
        return f"No food logged for {user_id} on {log_date}."

    # If query is a simple 'what did I eat' — use structured reply format
    eat_keywords = {"eat", "ate", "ate today", "log", "logged", "have today", "eaten"}
    if any(kw in question.lower() for kw in eat_keywords) and days_back <= 1:
        return query_reply_slack(rows, totals, question)

    # Otherwise: Claude with full data context
    data_json = json.dumps(rows, indent=2, default=str)
    resp = _client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=ANSWER_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Data ({start} to {log_date}):\n\n{data_json}\n\nQuestion: {question}"}]
    )
    return resp.content[0].text.strip()


# ── Query (structured) ────────────────────────────────────────────────────────

def query(question: str, user_id: str = "gabriel",
          days_back: int = 7, log_date: str = None) -> dict:
    """
    Structured query for scientists. Returns:
    {
        "answer": str,          # same shape as answer()
        "rows": list[dict],     # raw DB rows
        "totals": dict,         # aggregated nutrient totals
        "date_range": (str, str),
    }
    Import and call directly from BEAST, analyst, workbench.
    """
    if log_date is None:
        log_date = datetime.date.today().isoformat()
    start = (datetime.date.fromisoformat(log_date)
             - datetime.timedelta(days=days_back - 1)).isoformat()

    conn = _db.init_db()
    rows = _db.fetch_rows_range(conn, start, log_date, user_id)
    totals = _db.daily_totals(conn, log_date, user_id)
    conn.close()

    return {
        "answer":     answer(question, user_id, days_back, log_date),
        "rows":       rows,
        "totals":     totals,
        "date_range": (start, log_date),
    }
