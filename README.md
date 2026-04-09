# Claude Code Cost Monitor

> **macOS only** — requires macOS 12+

A lightweight macOS menu bar app that tracks your [Claude Code](https://claude.ai/code) spending and token usage in real time — by reading local logs from `~/.claude/projects/`. No API keys required.

<p align="center">
  <img src="screenshot.png" alt="Claude Monitor menu bar app" width="400">
</p>

## Install

```bash
brew install --cask alexisbianchi18/tap/claude-monitor
```

Update:

```bash
brew upgrade claude-monitor
```

Alternatively, download the `.dmg` or `.zip` from the [latest release](https://github.com/AlexisBianchi18/claude-monitor/releases/latest).

## Features

- **Real-time cost tracking** — displays `C $0.42` in the macOS menu bar, auto-refreshes every 30 seconds
- **Subscription mode** — switch to `C 45%` to track token usage against your plan limits (Pro, Max 5x, Max 20x)
- **Extra usage tracking** — monitor spending beyond plan limits with configurable budgets
- **Per-project breakdown** — see which projects are costing you the most
- **Weekly summary** — 7-day history with daily averages
- **Cost alerts** — native macOS notifications when spending exceeds your threshold
- **Auto-update** — checks for new versions every 24h, one-click update from the menu
- **Privacy-first** — only reads numeric fields (token counts, timestamps, model names). Never reads prompt content
- **API integration (optional)** — connect an Anthropic API key to see rate limit usage and actual billing costs
- **Fully offline by default** — everything computed locally, no account or API key needed

## How It Works

The app reads Claude Code's local JSONL session files, extracts token usage data, and calculates costs using current model pricing. It runs quietly in your menu bar next to WiFi and battery, updating every 30 seconds.

## License

MIT
