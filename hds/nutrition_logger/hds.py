"""
nutrition_logger/hds.py
========================
HDS sync seam. Writes food_intake_event proposals to the HDS queue.

Contract:
- Write typed JSON to ~/projects/hdsystem/inputs/proposals/pending/
- Fire-and-forget — never atomic with SQLite, never raise on failure
- In test mode (NUTRITION_LOGGER_ENV=test): no-op entirely
- Schema: proposal_type = "food_intake_event" (HDS-side type, pending registration)
"""

import os
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone

log = logging.getLogger(__name__)

IS_TEST = os.environ.get("NUTRITION_LOGGER_ENV", "prod").lower() == "test"

HDS_QUEUE_DIR = Path("~/projects/hdsystem/inputs/proposals/pending").expanduser()


def _queue_dir() -> Path:
    override = os.environ.get("HDS_PROPOSAL_QUEUE_DIR")
    if override:
        return Path(override).expanduser()
    return HDS_QUEUE_DIR


def write_food_intake_event(
    user_id: str,
    log_date: str,
    meal_time: str,
    meal_category: str,
    food_name_raw: str,
    food_name_matched: str,
    quantity_g: float,
    nutrients: dict,
    db_row_id: int,
    shorthand_matched: bool = False,
    parse_confidence: float = 1.0,
    ambiguity_note: str = None,
    source: str = "nutrition-logger",
    command_id: str = None,
) -> bool:
    """
    Write a food_intake_event proposal to the HDS queue.

    Returns True if written successfully, False otherwise.
    In test mode: always returns True without writing anything.

    Caller should not raise on False — the sidecar reconciler handles retries.
    """
    if IS_TEST:
        log.debug("HDS queue write skipped (test mode)")
        return True

    proposal = {
        "proposal_type": "food_intake_event",
        "proposal_id": str(uuid.uuid4()),
        "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "command_id": command_id,
        "payload": {
            "user_id": user_id,
            "log_date": log_date,
            "meal_time": meal_time,
            "meal_category": meal_category,
            "food_name_raw": food_name_raw,
            "food_name_matched": food_name_matched,
            "quantity_g": quantity_g,
            "shorthand_matched": shorthand_matched,
            "parse_confidence": parse_confidence,
            "ambiguity_note": ambiguity_note,
            "nutrients": nutrients,
            "db_row_id": db_row_id,
        }
    }

    try:
        queue_dir = _queue_dir()
        queue_dir.mkdir(parents=True, exist_ok=True)
        filename = f"food_intake_{proposal['proposal_id']}.json"
        path = queue_dir / filename
        with open(path, "w") as f:
            json.dump(proposal, f, indent=2, default=str)
        log.debug(f"HDS proposal written: {filename}")
        return True
    except Exception as e:
        log.warning(f"HDS queue write failed (non-fatal): {e}")
        return False
