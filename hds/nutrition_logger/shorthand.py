"""
nutrition_logger/shorthand.py
==============================
Loads Gabriel's shorthand registry from YAML and expands known phrases.

YAML schema (HDS canonical — do not change field names here without updating
~/projects/hdsystem/src/hdsystem/composition/table.py):
    families[].patterns          : list of case-insensitive substring triggers
    families[].negative_patterns : if ANY present in transcript, rule skips
    families[].emits             : list of food items with direct macros
      .label / .dose_ml / .kcal / .protein_g / .fat_g / .carbs_g / .sugar_g / .sodium_mg
      .verification              : provenance note
    special_cases.eaten_out      : dict with triggers / flags / coffee_exception
    parsing_rules[]              : parse-time behaviour rules (not expansions)
"""

import os
import re
import yaml
from pathlib import Path
from functools import lru_cache
from typing import Optional


def get_registry_path() -> Optional[Path]:
    override = os.environ.get("NUTRITION_SHORTHAND_REGISTRY")
    if override:
        return Path(override).expanduser()
    candidates = [
        Path("~/projects/nutrition-logger/data/gabriel_shorthand.yaml").expanduser(),
        Path(__file__).parent.parent / "data" / "gabriel_shorthand.yaml",
        Path("data/gabriel_shorthand.yaml"),
        Path("gabriel_shorthand.yaml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


@lru_cache(maxsize=1)
def _load() -> dict:
    path = get_registry_path()
    if not path or not path.exists():
        return {"families": [], "special_cases": {}, "parsing_rules": []}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def reload():
    """Force reload — call after HDS re-exports the YAML without restarting daemon."""
    _load.cache_clear()


# ── Shorthand expansion ───────────────────────────────────────────────────────

def expand(transcript: str) -> Optional[dict]:
    """
    Match transcript against shorthand families.

    Matching:
    - Any pattern is a case-insensitive substring match anywhere in transcript
    - If ANY negative_pattern appears, the family does not fire
    - Rules are additive — caller emits extra rows alongside literal items
    - First matching family wins (more-specific families listed first in YAML)

    Returns:
    {
        "family":          str,
        "matched_pattern": str,
        "items":           list of emit dicts from YAML,
        "confidence":      1.0,
    }
    or None.
    """
    data = _load()
    t = transcript.lower().strip()

    for family in data.get("families", []):
        patterns      = family.get("patterns", [])
        neg_patterns  = family.get("negative_patterns", [])

        if any(neg.lower() in t for neg in neg_patterns):
            continue

        matched = next((p for p in patterns if p.lower() in t), None)
        if matched:
            return {
                "family":          family.get("family", ""),
                "matched_pattern": matched,
                "items":           family.get("emits", []),
                "confidence":      1.0,
            }
    return None


def check_special_cases(transcript: str) -> Optional[dict]:
    """
    Check for special-case flags (e.g. eaten_out).

    Returns:
    {
        "name": str,
        "flags": dict,
        "coffee_exception": bool,
    }
    or None.
    """
    data = _load()
    t = transcript.lower().strip()

    # special_cases is a dict keyed by case name
    special_cases = data.get("special_cases", {})
    if isinstance(special_cases, list):
        items = [(c.get("name", ""), c) for c in special_cases]
    else:
        items = special_cases.items()
    for name, case in items:
        triggers = case.get("triggers", [])
        if any(tr.lower() in t for tr in triggers):
            return {
                "name":             name,
                "flags":            case.get("flags", {}),
                "coffee_exception": case.get("coffee_exception", False),
            }
    return None


# ── Parsing rule helpers ──────────────────────────────────────────────────────

def extract_shot_weight_g(transcript: str) -> Optional[float]:
    """
    Return explicit gram weight for an espresso shot if stated, else None.
    "28g of the blend espresso" → 28.0
    """
    patterns = [
        r'(\d+(?:\.\d+)?)\s*g\s+(?:of\s+)?(?:the\s+)?(?:\w+\s+){0,3}espresso',
        r'espresso\s+(?:shot\s+)?(?:of\s+)?(\d+(?:\.\d+)?)\s*g',
    ]
    for pat in patterns:
        m = re.search(pat, transcript.lower())
        if m:
            return float(m.group(1))
    return None


def extract_bean_origin(transcript: str) -> Optional[str]:
    """
    Return bean origin phrase if named before 'espresso', else None.
    Preserved verbatim — never collapsed to generic.
    """
    m = re.search(
        r'(costa rica|ethiopia|kenya|colombia|brazil|brasil|guatemala|'
        r'honduras|peru|panama|rwanda|burundi|tanzania|yemen|'
        r'italia blend|italian blend|blend)\s+espresso',
        transcript.lower()
    )
    return m.group(1).title() if m else None


# ── Macro conversion ──────────────────────────────────────────────────────────

def item_to_nutrients(item: dict) -> dict:
    """
    Convert a shorthand emit dict to our standard nutrient column format.
    Nulls are preserved — do not substitute DB values for null fields.
    """
    field_map = {
        "kcal":       "energy_kcal",
        "protein_g":  "protein_g",
        "fat_g":      "fat_total_g",
        "carbs_g":    "carbohydrate_g",
        "sugar_g":    "sugars_g",
        "sodium_mg":  "sodium_mg",
    }
    # Explicitly include nulls — null means "not yet verified", not "zero"
    return {col: item.get(yaml_key) for yaml_key, col in field_map.items()}


def is_shorthand(phrase: str) -> bool:
    return expand(phrase) is not None


def list_families() -> list:
    data = _load()
    return [
        {"family": f.get("family", ""), "patterns": f.get("patterns", [])}
        for f in data.get("families", [])
    ]
