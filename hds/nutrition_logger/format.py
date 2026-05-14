"""
nutrition_logger/format.py
===========================
Reply formatting. One consistent shape for both confirmations and query replies.

Slack/terminal:
    Logged: 2 eggs (140 kcal, 12g P), 1 slice toast (75 kcal, 3g P)
    Today: 290 kcal, 19g P, 8g C, 12g F

Voice (kokoro):
    Logged eggs, toast, and latte. Today so far: 290 calories, 19 grams protein.
"""

from typing import List


def _kcal(n):
    if n is None:
        return "?"
    return str(int(round(n)))

def _g(n):
    if n is None:
        return "?"
    return str(round(n, 1))


def item_line(food_name: str, kcal, protein_g) -> str:
    return f"{food_name} ({_kcal(kcal)} kcal, {_g(protein_g)}g P)"


def daily_total_line(totals: dict) -> str:
    return (
        f"Today: {_kcal(totals.get('energy_kcal'))} kcal, "
        f"{_g(totals.get('protein_g'))}g P, "
        f"{_g(totals.get('carbohydrate_g'))}g C, "
        f"{_g(totals.get('fat_total_g'))}g F"
    )


def confirmation_slack(logged_items: list, totals: dict) -> str:
    """
    Slack / terminal confirmation.
    logged_items: list of dicts with food_name_raw, energy_kcal, protein_g
    """
    if not logged_items:
        return "Nothing logged."
    parts = [item_line(
        i.get("food_name_raw", "item"),
        i.get("energy_kcal"),
        i.get("protein_g"),
    ) for i in logged_items]
    body = "Logged: " + ", ".join(parts)
    total = daily_total_line(totals)
    return f"{body}\n{total}"


def confirmation_voice(logged_items: list, totals: dict) -> str:
    """
    Kokoro TTS confirmation — no per-item breakdown, just confirm + totals.
    """
    if not logged_items:
        return "Nothing was logged."
    names = [i.get("food_name_raw", "item") for i in logged_items]
    if len(names) == 1:
        name_str = names[0]
    elif len(names) == 2:
        name_str = f"{names[0]} and {names[1]}"
    else:
        name_str = ", ".join(names[:-1]) + f", and {names[-1]}"
    kcal = _kcal(totals.get("energy_kcal"))
    prot = _g(totals.get("protein_g"))
    return (
        f"Logged {name_str}. "
        f"Today so far: {kcal} calories, {prot} grams protein."
    )


def confirmation(logged_items: list, totals: dict, channel: str) -> str:
    """
    Dispatch to correct format based on reply channel prefix.
    channel: "slack:<id>" | "voice:<session>" | "terminal" | "none"
    """
    if channel.startswith("voice"):
        return confirmation_voice(logged_items, totals)
    return confirmation_slack(logged_items, totals)


def query_reply_slack(rows: list, totals: dict, question: str = None) -> str:
    """
    Query reply in same shape as confirmation — consistent format.
    Used for 'what did I eat today?' and similar.
    """
    if not rows:
        return "No entries found."
    parts = [item_line(
        r.get("food_name_raw", "item"),
        r.get("energy_kcal"),
        r.get("protein_g"),
    ) for r in rows]
    body = "Eaten: " + ", ".join(parts)
    total = daily_total_line(totals)
    return f"{body}\n{total}"
