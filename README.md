# Claude Code Cost Monitor

A lightweight macOS menu bar app that tracks your [Claude Code](https://claude.ai/code) spending and token usage in real time — by reading local logs from `~/.claude/projects/`. No API keys required.

## Screenshot

<p align="center">
  <img src="screenshot.png" alt="Claude Monitor menu bar app" width="400">
</p>

## Features

- **Real-time cost tracking** — displays `C $X.XX` in the macOS menu bar, auto-refreshes every 30 seconds
- **Per-project breakdown** — see which projects are costing you the most
- **Weekly summary** — 7-day history with daily averages
- **Cost alerts** — native macOS notification when spending exceeds a configurable threshold (default: $5.00), title changes to `⚠ $X.XX`
- **Daily reset** — reset the counter to $0.00 without losing data
- **CLI report** — formatted terminal output for quick checks
- **Standalone .app** — package as a native macOS app (~22 MB), no Dock icon
- **Privacy-first** — only reads numeric fields (`usage`, `costUSD`, `timestamp`, `model`). Never reads prompt content.
- **Fully offline** — no network calls, everything is computed locally

## Requirements

- macOS 12+
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/claude-monitor.git
cd claude-monitor

# Create virtual environment and install dependencies
uv venv
uv pip install rumps

# (Optional) Install dev dependencies
uv pip install pytest
```

## Usage

### Menu Bar App

```bash
.venv/bin/python -m claude_monitor.app
```

The menu shows:

| Item | Description |
|------|-------------|
| Today's total | Cost, API calls, and token count |
| Project list | Up to 10 projects sorted by cost |
| Weekly summary | 7-day total with daily average |
| Refresh Now | Force an immediate update |
| Reset Daily Counter | Zero out today's display (preserves actual data) |
| Preferences | Open `config.json` in TextEdit |
| Quit | Exit the app |

### CLI Report

```bash
.venv/bin/python -m claude_monitor.cli
```

```
============================================================
  Claude Code Cost Report — Wednesday, April 08, 2026
============================================================

  Today's total:  $35.8810
  Total tokens:   11,898,884
  API calls:      337

  Project                              Cost    Calls
  ------------------------------ ---------- -------
  contextual-url-learning          $18.4755      197
  claude-monitor                   $17.4055      140

  Last 7 days:
    Mon 04/06  $20.6719
    Tue 04/07  $2.4660
    Wed 04/08  $35.8810 <-- today
                 --------
         Week  $59.0189  (avg $8.4313/day)
```

### Build Standalone .app

```bash
uv pip install pyinstaller

.venv/bin/python setup.py

open dist/Claude\ Monitor.app
```

The packaged app:
- Runs standalone (bundles Python and all dependencies)
- Doesn't appear in the Dock (`LSUIElement: true`)
- Can be copied to `/Applications/`

## Configuration

Settings are stored in `~/.claude-monitor/config.json` (created automatically with defaults on first run):

```json
{
  "refresh_interval_seconds": 30,
  "cost_alert_threshold_usd": 5.0,
  "max_projects_in_menu": 10
}
```

Edit via the Preferences menu item or manually.

## Supported Models & Pricing

| Model | Input ($/M tokens) | Output ($/M tokens) | Cache Read ($/M) | Cache Create ($/M) |
|-------|-------------------:|--------------------:|------------------:|--------------------:|
| claude-opus-4-6 | 15.00 | 75.00 | 1.50 | 18.75 |
| claude-sonnet-4-6 | 3.00 | 15.00 | 0.30 | 3.75 |
| claude-haiku-4-5-20251001 | 0.80 | 4.00 | 0.08 | 1.00 |

Prices can be updated in [config.py](claude_monitor/config.py). When a log entry includes `costUSD`, that value is used directly; otherwise cost is estimated from token counts.

## Project Structure

```
claude-monitor/
├── claude_monitor/
│   ├── __init__.py
│   ├── __main__.py        # python -m claude_monitor
│   ├── models.py          # Dataclasses: TokenUsage, CostEntry, ProjectStats, DailyReport
│   ├── config.py          # Model pricing, constants, ConfigManager
│   ├── log_parser.py      # ClaudeLogParser: JSONL reading and parsing
│   ├── cli.py             # Formatted terminal report
│   └── app.py             # Menu bar app (rumps) with alerts and reset
├── tests/
│   ├── test_models.py
│   ├── test_parser.py
│   ├── test_config.py
│   └── fixtures/
│       ├── sample_session.jsonl
│       ├── sample_subagent.jsonl
│       ├── malformed.jsonl
│       └── empty.jsonl
├── run_app.py             # Entry point for PyInstaller
├── setup.py               # Build script (PyInstaller → .app)
├── requirements.txt
├── CLAUDE.md              # Project specification
└── README.md
```

## Tests

```bash
# Run all tests (50 tests)
.venv/bin/python -m pytest tests/ -v
```

Test coverage includes:
- Missing log directory returns empty report without errors
- Malformed JSON lines and empty files are skipped gracefully
- Non-assistant message types (`user`, `queue-operation`, `attachment`, `ai-title`) are ignored
- Synthetic model entries are ignored
- Deduplication by `message.id` (only the latest counts)
- Correct cost calculation for Opus, Sonnet, and Haiku
- Unknown models default to $0.00
- Date filtering (yesterday excluded, today included)
- UTC timestamp parsing with `Z` and offset formats
- Subagent sessions from `<session>/subagents/*.jsonl`
- Project name extraction from `cwd` field with directory name fallback
- Config creation, corruption recovery, and merge behavior
- Daily offset and alert tracking persistence

## How It Works

1. **Reads** JSONL session files from `~/.claude/projects/` (including subagent logs)
2. **Parses** only numeric fields — token counts, costs, timestamps, and model names
3. **Deduplicates** streaming messages by `message.id`
4. **Groups** entries by project (extracted from `cwd` in the logs)
5. **Displays** the running total in the menu bar, updated every 30 seconds

## License

MIT
