# nutrition-logger — Installation (Gabriel's system)

## Directory layout

```
~/projects/nutrition-logger/
├── nutrition_logger/       ← package
│   ├── __init__.py
│   ├── core.py
│   ├── db.py
│   ├── lookup.py
│   ├── lookup_tables.py
│   ├── shorthand.py
│   ├── hds.py
│   ├── daemon.py
│   └── format.py
├── bin/
│   ├── log                 ← CLI wrapper
│   └── query               ← CLI wrapper
├── data/
│   ├── gabriel_shorthand.yaml   ← written by HDS sync script
│   ├── cofid.db                 ← CoFID 2021 database
│   ├── nutrition_log.db         ← prod SQLite (auto-created)
│   └── nutrition_log_test.db    ← test SQLite (auto-created)
├── logs/                   ← daemon stdout/stderr
├── com.nutrition-logger.daemon.plist
└── INSTALL.md
```

## Dependencies

```bash
pip install anthropic requests pyyaml pypdf pymupdf pandas openpyxl
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `NUTRITION_LOGGER_ENV` | `prod` | Set to `test` for test runs |
| `ANTHROPIC_API_KEY` | — | Or set in `config.py` |
| `USDA_API_KEY` | — | Or set in `config.py` |
| `NUTRITION_SHORTHAND_REGISTRY` | auto-detected | Override YAML path |
| `NUTRITION_LOGGER_DB_DIR` | `~/projects/nutrition-logger/data/` | Override DB dir |
| `HDS_PROPOSAL_QUEUE_DIR` | `~/projects/hdsystem/inputs/proposals/pending/` | Override HDS queue |

## Daemon setup

```bash
# Create log dir
mkdir -p ~/projects/nutrition-logger/logs

# Install launchd plist
cp com.nutrition-logger.daemon.plist ~/Library/LaunchAgents/

# Load (starts immediately, restarts on crash)
launchctl load ~/Library/LaunchAgents/com.nutrition-logger.daemon.plist

# Check it's running
launchctl list | grep nutrition

# Tail logs
tail -f ~/projects/nutrition-logger/logs/daemon.log
```

## Test run (isolated — never touches prod DB or HDS)

```bash
NUTRITION_LOGGER_ENV=test python3 -c "
from nutrition_logger.core import log
result = log('two eggs and toast', user_id='gabriel')
print(result['reply'])
"
```

## CLI usage

```bash
# Log food
bin/log "espresso latte, two eggs scrambled, sourdough toast"

# With explicit date
bin/log --date 2026-05-12 "natto 100g, white rice 180g"

# Via stdin (from voice classifier drop)
echo "had a latte" | bin/log

# Query
bin/query "what did I eat today?"
bin/query --days 7 "average protein this week"

# Structured output for scientists/agents
bin/query --structured "what did I eat today?" | jq .totals
```

## Drop file format (voice/Slack inbox)

```
# command-id: <uuid>
# user_id: gabriel
# source: voice
# reply_channel: slack:<dm_id>
# queued_at_utc: 2026-05-13T08:30:00Z

espresso latte, two eggs scrambled
```

Drop the file into `~/InboxRouter/nutrition-inbox/` — the daemon picks it up
within 2 seconds, logs the items, and posts the confirmation to `reply_channel`.

## Shorthand registry

The registry at `data/gabriel_shorthand.yaml` is owned by HDS and written
by the sync script at `~/projects/hdsystem/scripts/export_shorthand.py`.
Do not edit it manually. When Eleonora confirms carton macros, HDS updates
the source table and re-exports — the daemon picks up the new YAML on next
restart (or call `nutrition_logger.shorthand.reload()` without restarting).

## HDS integration

In prod mode, each logged food row emits a `food_intake_event` proposal to
`~/projects/hdsystem/inputs/proposals/pending/`. The HDS applier daemon drains
this queue and commits to Postgres. `nutrition-logger` never writes Postgres
directly. If the queue write fails, the SQLite write still succeeds — the
sidecar reconciler handles retries.

In test mode (`NUTRITION_LOGGER_ENV=test`), HDS queue writes are skipped
entirely. Test logs never touch HDS truth.
