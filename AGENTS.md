# Agent Setup Guide

This file helps AI coding agents (Claude Code, Gemini CLI, Cursor, etc.) automatically set up langfuse-claude-code for the user.

## Project Overview

**langfuse-claude-code** traces Claude Code conversations to Langfuse. It hooks into all 4 Claude Code events (Stop, Notification, PreToolUse, PostToolUse) and sends structured traces including turns, tool calls, thinking blocks, and token usage.

## Automated Setup Procedure

When a user asks to set up this project, follow these steps:

### Step 1: Check Prerequisites

```bash
# Python 3.8+
python3 --version

# pip available
python3 -m pip --version

# langfuse SDK
python3 -c "import langfuse; print(langfuse.__version__)" 2>/dev/null || echo "Not installed"
```

If langfuse is not installed:
```bash
python3 -m pip install --upgrade langfuse
```

### Step 2: Interview User for Langfuse Credentials

Ask the user for these values. Do NOT guess or use placeholder values.

| Key | Question to Ask | Example Format |
|-----|-----------------|----------------|
| `LANGFUSE_PUBLIC_KEY` | "Langfuse Public Key를 알려주세요" | `pk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `LANGFUSE_SECRET_KEY` | "Langfuse Secret Key를 알려주세요" | `sk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `LANGFUSE_BASE_URL` | "Langfuse URL을 알려주세요 (기본값: https://cloud.langfuse.com)" | `https://cloud.langfuse.com` or self-hosted URL |
| `LANGFUSE_USER_ID` | "트레이스에 표시할 사용자 ID를 알려주세요 (기본값: claude-user)" | Any string |

Get keys from: https://cloud.langfuse.com → Project Settings → API Keys

### Step 3: Install Hook Script

```bash
mkdir -p ~/.claude/hooks ~/.claude/state
cp langfuse_hook.py ~/.claude/hooks/langfuse_hook.py
chmod +x ~/.claude/hooks/langfuse_hook.py
```

### Step 4: Configure settings.json

Read the existing `~/.claude/settings.json` first, then merge (do NOT overwrite existing settings):

**Add to `env`** (preserve existing env vars):
```json
{
  "TRACE_TO_LANGFUSE": "true",
  "LANGFUSE_PUBLIC_KEY": "<from interview>",
  "LANGFUSE_SECRET_KEY": "<from interview>",
  "LANGFUSE_BASE_URL": "<from interview>",
  "LANGFUSE_USER_ID": "<from interview>"
}
```

**Add to `hooks`** (preserve existing hooks):
```json
{
  "Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}],
  "Notification": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}],
  "PreToolUse": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}],
  "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}]
}
```

### Step 5: Verify

```bash
# Check hook file exists
ls -la ~/.claude/hooks/langfuse_hook.py

# Check langfuse import works
python3 -c "import langfuse; print('OK')"

# Dry-run test (should exit silently)
echo '{}' | python3 ~/.claude/hooks/langfuse_hook.py
```

### Step 6: Inform User

Tell the user:
- Restart Claude Code to activate the hooks
- Dashboard: the LANGFUSE_BASE_URL they provided
- Logs: `~/.claude/state/langfuse_hook.log`
- Debug mode: set `CC_LANGFUSE_DEBUG` to `"true"` in env
- Disable: set `TRACE_TO_LANGFUSE` to `"false"` in env

## File Paths

| File | Path | Purpose |
|------|------|---------|
| Hook script (source) | `./langfuse_hook.py` | Main hook implementation |
| Hook script (installed) | `~/.claude/hooks/langfuse_hook.py` | Active hook |
| Settings | `~/.claude/settings.json` | Hook registration + env vars |
| State | `~/.claude/state/langfuse_state.json` | Incremental processing offsets |
| Tool buffer | `~/.claude/state/langfuse_tool_buffer.jsonl` | PreToolUse/PostToolUse event buffer |
| Log | `~/.claude/state/langfuse_hook.log` | Hook execution log |

## Troubleshooting

- **No traces**: Check `TRACE_TO_LANGFUSE=true` and API keys are correct
- **Hook not firing**: Verify hooks are in settings.json under all 4 event keys
- **Import error**: Run `python3 -m pip install langfuse`
- **Duplicate traces**: Delete `~/.claude/state/langfuse_state.json` for fresh start
