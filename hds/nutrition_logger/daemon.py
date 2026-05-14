"""
nutrition_logger/daemon.py
===========================
Inbox watcher daemon. Runs as a launchd service.

Watches ~/InboxRouter/nutrition-inbox/ for .txt drop files.
Each file has a header block followed by the verbatim transcript.

Drop file format:
    # command-id: <uuid>
    # user_id: gabriel
    # source: voice | slack | terminal
    # reply_channel: slack:<dm_id> | voice:<session> | terminal | none
    # queued_at_utc: <iso>

    <verbatim transcript>

On receipt:
    1. Parse header
    2. Call core.log()
    3. Format reply for reply_channel
    4. Dispatch reply
    5. Move file to processed/
"""

import os
import sys
import time
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from . import core
from .format import confirmation

log = logging.getLogger(__name__)

INBOX_DIR     = Path("~/InboxRouter/nutrition-inbox").expanduser()
PROCESSED_DIR = INBOX_DIR / "processed"
POLL_SECONDS  = 2


# ── Drop file parsing ─────────────────────────────────────────────────────────

def parse_drop_file(path: Path) -> dict:
    """
    Parse a drop file into header dict + transcript body.
    Returns:
    {
        "command_id": str,
        "user_id": str,
        "source": str,
        "reply_channel": str,
        "queued_at_utc": str,
        "transcript": str,
    }
    """
    with open(path) as f:
        raw = f.read()

    header = {}
    body_lines = []
    in_body = False

    for line in raw.splitlines():
        if in_body:
            body_lines.append(line)
        elif line.startswith("#"):
            # Parse header line: "# key: value"
            stripped = line.lstrip("#").strip()
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                header[k.strip()] = v.strip()
        elif line.strip() == "":
            if header:  # blank line after headers = start of body
                in_body = True
        else:
            body_lines.append(line)
            in_body = True

    return {
        "command_id":    header.get("command-id", ""),
        "user_id":       header.get("user_id", "gabriel"),
        "source":        header.get("source", "voice"),
        "reply_channel": header.get("reply_channel", "none"),
        "queued_at_utc": header.get("queued_at_utc", ""),
        "transcript":    "\n".join(body_lines).strip(),
    }


# ── Reply dispatch ────────────────────────────────────────────────────────────

def dispatch_reply(reply_text: str, channel: str, command_id: str = ""):
    """
    Send the reply to the appropriate channel.
    channel format: "slack:<dm_id>" | "voice:<session>" | "terminal" | "none"
    """
    if channel == "none" or not channel:
        log.debug(f"[{command_id}] Silent log (reply_channel=none)")
        return

    if channel == "terminal":
        print(reply_text)
        return

    if channel.startswith("slack:"):
        dm_id = channel.split(":", 1)[1]
        _send_slack(dm_id, reply_text, command_id)
        return

    if channel.startswith("voice:"):
        session = channel.split(":", 1)[1]
        _send_voice(session, reply_text, command_id)
        return

    log.warning(f"[{command_id}] Unknown reply_channel: {channel}")


def _send_slack(dm_id: str, text: str, command_id: str):
    """
    Post reply to Slack DM via inbox-router outbound.
    Writes a reply event file that the router picks up.
    """
    try:
        reply_dir = Path("~/InboxRouter/outbound").expanduser()
        reply_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "command_id": command_id,
            "channel": f"slack:{dm_id}",
            "text": text,
            "sent_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        import json
        reply_file = reply_dir / f"reply_{command_id}.json"
        with open(reply_file, "w") as f:
            json.dump(payload, f)
        log.info(f"[{command_id}] Slack reply queued → {dm_id}")
    except Exception as e:
        log.error(f"[{command_id}] Slack dispatch failed: {e}")


def _send_voice(session: str, text: str, command_id: str):
    """
    Send reply to kokoro TTS via vlive.
    Writes a .tts file that vlive picks up.
    """
    try:
        tts_dir = Path("~/projects/voice/tts-queue").expanduser()
        tts_dir.mkdir(parents=True, exist_ok=True)
        tts_file = tts_dir / f"tts_{command_id}.txt"
        with open(tts_file, "w") as f:
            f.write(text)
        log.info(f"[{command_id}] Voice reply queued → {session}")
    except Exception as e:
        log.error(f"[{command_id}] Voice dispatch failed: {e}")


# ── File processing ───────────────────────────────────────────────────────────

def process_file(path: Path):
    """Process a single drop file."""
    log.info(f"Processing: {path.name}")

    try:
        drop = parse_drop_file(path)
    except Exception as e:
        log.error(f"Failed to parse drop file {path.name}: {e}")
        _move_to_processed(path, error=True)
        return

    transcript = drop["transcript"]
    if not transcript:
        log.warning(f"Empty transcript in {path.name}")
        _move_to_processed(path)
        return

    try:
        result = core.log(
            text=transcript,
            user_id=drop["user_id"],
            source=drop["source"],
            command_id=drop["command_id"],
        )
    except Exception as e:
        log.error(f"core.log() failed for {path.name}: {e}")
        _move_to_processed(path, error=True)
        return

    # Format reply for channel
    channel = drop["reply_channel"]
    reply_text = confirmation(
        result["logged"],
        result["totals"],
        channel,
    )

    dispatch_reply(reply_text, channel, drop["command_id"])
    _move_to_processed(path)
    log.info(f"Done: {path.name} — {len(result['logged'])} items logged")


def _move_to_processed(path: Path, error: bool = False):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".error" if error else ""
    dest = PROCESSED_DIR / (path.name + suffix)
    shutil.move(str(path), str(dest))


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    """
    Main daemon loop. Polls INBOX_DIR every POLL_SECONDS.
    Restart-safe — picks up any unprocessed files on start.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [nutrition-daemon] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    log.info(f"Nutrition logger daemon started. Watching: {INBOX_DIR}")
    log.info(f"ENV: {os.environ.get('NUTRITION_LOGGER_ENV', 'prod')}")

    while True:
        try:
            txt_files = sorted(INBOX_DIR.glob("*.txt"))
            for f in txt_files:
                try:
                    process_file(f)
                except Exception as e:
                    log.error(f"Unhandled error processing {f.name}: {e}")
                    _move_to_processed(f, error=True)
        except Exception as e:
            log.error(f"Inbox scan error: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
