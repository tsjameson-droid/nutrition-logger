"""
mext.py
=======
Search and retrieve nutrients from the MEXT 2015 Japanese food composition database.

Integrates into the existing lookup pipeline alongside CoFID and USDA.
Place mext.db in the same directory as cofid.db (~/nutrition-logger/ for Tom,
~/projects/nutrition-logger/data/ for Gabriel's HDS setup).

Public API
----------
search_mext(query: str, db_path: str) -> list[dict]
    Returns up to 5 candidate matches sorted by relevance.

get_mext_nutrients(item_no: str, db_path: str) -> dict
    Returns nutrients per 100g for a given MEXT item_no.

MEXT_TO_STANDARD(nutrients: dict) -> dict
    Maps MEXT column names to the standard nutrient schema used by
    nutrition_logger.py / core.py.
"""

import sqlite3
import os
import re
from typing import Optional


# ---------------------------------------------------------------------------
# MEXT column name -> standard schema name used by the rest of the pipeline
# ---------------------------------------------------------------------------
_MEXT_TO_STD = {
    'energy_kcal':      'energy_kcal',
    'protein_g':        'protein_g',
    'fat_g':            'fat_total_g',
    'sat_fat_g':        'saturated_fat_g',
    'mono_fat_g':       'monounsaturated_fat_g',
    'poly_fat_g':       'polyunsaturated_fat_g',
    'cholesterol_mg':   'cholesterol_mg',
    'carbs_g':          'carbohydrate_g',
    'fibre_total_g':    'fibre_g',
    'fibre_sol_g':      'fibre_soluble_g',
    'fibre_insol_g':    'fibre_insoluble_g',
    'sodium_mg':        'sodium_mg',
    'potassium_mg':     'potassium_mg',
    'calcium_mg':       'calcium_mg',
    'magnesium_mg':     'magnesium_mg',
    'phosphorus_mg':    'phosphorus_mg',
    'iron_mg':          'iron_mg',
    'zinc_mg':          'zinc_mg',
    'copper_mg':        'copper_mg',
    'manganese_mg':     'manganese_mg',
    'iodine_ug':        'iodine_ug',
    'selenium_ug':      'selenium_ug',
    'retinol_ug':       'retinol_ug',
    'beta_carotene_ug': 'beta_carotene_ug',
    'vita_rae_ug':      'vitamin_a_ug_rae',
    'vitamin_d_ug':     'vitamin_d_ug',
    'vitamin_e_mg':     'vitamin_e_mg',
    'vitamin_k_ug':     'vitamin_k_ug',
    'thiamin_mg':       'thiamin_mg',
    'riboflavin_mg':    'riboflavin_mg',
    'niacin_mg':        'niacin_mg',
    'vitamin_b6_mg':    'vitamin_b6_mg',
    'vitamin_b12_ug':   'vitamin_b12_ug',
    'folate_ug':        'folate_ug',
    'pantothenic_mg':   'pantothenic_acid_mg',
    'biotin_ug':        'biotin_ug',
    'vitamin_c_mg':     'vitamin_c_mg',
    'alcohol_g':        'alcohol_g',
    'caffeine_mg':      'caffeine_mg',
}

# Nutrient columns to fetch from DB (all except id, food_group, item_no etc.)
_NUTRIENT_COLS = list(_MEXT_TO_STD.keys())


def _get_conn(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"mext.db not found at {db_path}. "
            "Run build_mext_db.py first to create it from mext_2015.xlsx"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _tokenise(query: str) -> list:
    """Split query into meaningful words, stripping stop words."""
    stop = {'raw', 'cooked', 'boiled', 'fresh', 'dried', 'the', 'and', 'of',
            'in', 'with', 'a', 'an', 'for', 'to', 'from'}
    tokens = re.findall(r'[a-z0-9]+', query.lower())
    return [t for t in tokens if t not in stop and len(t) > 1]


def _score_match(query_tokens: list, food_name: str) -> int:
    """Score how well food_name matches the query tokens.
    
    Scoring:
    - +10 for each token found in name
    - +5 bonus if first token is the first word of the food name
    - +3 bonus for exact substring match of full query
    """
    name_lower = food_name.lower()
    score = 0
    for token in query_tokens:
        if token in name_lower:
            score += 10
    if query_tokens and name_lower.startswith(query_tokens[0]):
        score += 5
    full_query = ' '.join(query_tokens)
    if full_query in name_lower:
        score += 3
    return score


def search_mext(query: str, db_path: str, limit: int = 5) -> list:
    """Search MEXT database for foods matching query.

    Parameters
    ----------
    query : str
        Free-text search term, e.g. "natto", "soba boiled", "maitake mushroom"
    db_path : str
        Path to mext.db
    limit : int
        Max candidates to return (default 5)

    Returns
    -------
    list of dicts with keys: item_no, food_name, energy_kcal, protein_g, source
    """
    tokens = _tokenise(query)
    if not tokens:
        return []

    try:
        conn = _get_conn(db_path)
    except FileNotFoundError:
        return []

    # Build WHERE clause: any row containing at least one token
    conditions = ' OR '.join(f"food_name_lower LIKE ?" for _ in tokens)
    params = [f'%{t}%' for t in tokens]

    rows = conn.execute(
        f"SELECT item_no, food_name, energy_kcal, protein_g "
        f"FROM mext_foods WHERE {conditions}",
        params
    ).fetchall()
    conn.close()

    # Score and sort
    scored = []
    for row in rows:
        score = _score_match(tokens, row['food_name'])
        if score > 0:
            scored.append((score, dict(row)))

    scored.sort(key=lambda x: -x[0])

    results = []
    for _, r in scored[:limit]:
        r['source'] = 'MEXT'
        results.append(r)

    return results


def get_mext_nutrients(item_no: str, db_path: str) -> dict:
    """Retrieve per-100g nutrients for a MEXT food item.

    Parameters
    ----------
    item_no : str
        MEXT item number, e.g. '04046' (natto)
    db_path : str
        Path to mext.db

    Returns
    -------
    dict mapping standard nutrient names to values per 100g.
    Missing values are omitted (not set to 0).
    """
    conn = _get_conn(db_path)
    cols = ', '.join(_NUTRIENT_COLS)
    row = conn.execute(
        f"SELECT {cols} FROM mext_foods WHERE item_no = ?",
        (item_no,)
    ).fetchone()
    conn.close()

    if not row:
        return {}

    result = {}
    for mext_col, std_col in _MEXT_TO_STD.items():
        v = row[mext_col]
        if v is not None:
            result[std_col] = v

    return result


def mext_to_standard(nutrients: dict) -> dict:
    """Map MEXT column names to the standard pipeline schema.
    
    Use this if you have a raw dict from the DB and need standard names.
    get_mext_nutrients() already applies this mapping, so you only need
    this function if you're working with raw DB rows directly.
    """
    return {_MEXT_TO_STD[k]: v for k, v in nutrients.items() if k in _MEXT_TO_STD and v is not None}


# ---------------------------------------------------------------------------
# Curated MEXT lookup table for Gabriel's most-consumed Japanese foods
# Keys are lowercase search terms Claude might generate.
# Values are MEXT item_no strings.
# ---------------------------------------------------------------------------
MEXT_LOOKUP = {
    # Natto
    'natto':                        '04046',
    'natto itohiki':                '04046',
    'fermented soybeans':           '04046',
    'hikiwari natto':               '04047',
    'natto hikiwari':               '04047',

    # Soba
    'soba':                         '01130',
    'soba noodles':                 '01130',
    'soba noodles boiled':          '01130',
    'soba boiled':                  '01130',
    'buckwheat noodles':            '01130',
    'buckwheat noodles boiled':     '01130',
    'soba noodles dry':             '01129',
    'buckwheat noodles dry':        '01129',
    'soba fresh':                   '01128',
    'soba fresh boiled':            '01128',

    # Tofu
    'tofu':                         '04032',
    'tofu firm':                    '04032',
    'regular tofu':                 '04032',
    'momen tofu':                   '04032',
    'silken tofu':                  '04033',
    'soft tofu':                    '04033',
    'kinugoshi tofu':               '04033',
    'tofu silken':                  '04033',
    'grilled tofu':                 '04038',
    'yaki tofu':                    '04038',
    'fried tofu':                   '04039',
    'freeze dried tofu':            '04042',
    'kori dofu':                    '04042',

    # Miso
    'miso':                         '17045',
    'miso paste':                   '17045',
    'white miso':                   '17045',
    'shiro miso':                   '17044',
    'aka miso':                     '17046',
    'red miso':                     '17046',
    'mugi miso':                    '17047',
    'barley miso':                  '17047',
    'hatcho miso':                  '17048',
    'miso soup':                    '17050',
    'instant miso soup':            '17050',

    # Mushrooms
    'maitake':                      '08028',
    'maitake mushroom':             '08028',
    'maitake raw':                  '08028',
    'maitake boiled':               '08029',
    'maitake dried':                '08030',
    'shiitake':                     '08039',
    'shiitake fresh':               '08039',
    'shiitake raw':                 '08039',
    'shiitake boiled':              '08040',
    'shiitake dried':               '08013',

    # Daikon
    'daikon':                       '06134',
    'daikon raw':                   '06134',
    'daikon radish':                '06134',
    'daikon boiled':                '06135',

    # Seaweed
    'wakame':                       '09045',
    'wakame seaweed':               '09045',
    'wakame fresh':                 '09039',
    'kombu':                        '09015',
    'kombu dried':                  '09015',

    # Edamame / green soybeans
    'edamame':                      '06016',
    'edamame boiled':               '06016',
    'green soybeans':               '06016',
    'green soybeans raw':           '06015',

    # Adzuki
    'adzuki beans':                 '04002',
    'adzuki boiled':                '04002',
    'red beans':                    '04002',

    # Tempeh
    'tempeh':                       '04063',

    # Dashi
    'dashi':                        '17021',
    'katsuo dashi':                 '17019',
    'kombu dashi':                  '17020',
    'shiitake dashi':               '17022',

    # Other Japanese staples
    'sake':                         '16003',
    'mirin':                        '16025',
    'rice koji':                    '01116',
    'koji':                         '01116',
    'udon':                         '01039',
    'udon boiled':                  '01039',
    'udon dried boiled':            '01042',
    'buckwheat flour':              '01122',
}


def lookup_mext(query: str) -> Optional[str]:
    """Check curated MEXT lookup table first before doing fuzzy search.
    
    Returns item_no if found, None otherwise.
    """
    return MEXT_LOOKUP.get(query.lower().strip())
