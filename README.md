# langfuse-claude-code

[English](README.md) | [한국어](README.ko.md)

Automatic [Langfuse](https://langfuse.com) tracing for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Every conversation turn, tool call, and model response is captured as structured traces in your Langfuse dashboard -- zero code changes required.

## Status (February 25, 2026)

- ✅ Hook pipeline verified on real Claude Code runs
- ✅ Turn traces, tool spans, and token usage confirmed in Langfuse
- ✅ Repository cleanup completed (no unnecessary tracked files found)
- ✅ `v0.0.1` release/tag refreshed with final docs sync
- ✅ LCC (`langfuse-claude-code`) aligned with companion repos:
  - `langfuse-oh-my-codex`
  - `langfuse-gemini-cli`
  - `langfuse-opencode`
- Progress docs: [English](./PROGRESS.md) | [한국어](./PROGRESS.ko.md)

## Features

- **Full event coverage** -- all 4 Claude Code hook events are captured (Stop, Notification, PreToolUse, PostToolUse)
- **Per-turn tracing** -- each user prompt + assistant response becomes a Langfuse trace
- **Real-time tool events** -- PreToolUse and PostToolUse hooks capture tool calls as they happen with precise timing
- **System prompt capture** -- system messages are recorded as dedicated spans
- **Full assistant content** -- all text blocks between tool calls are preserved in order (no content lost)
- **Thinking blocks** -- Claude's internal reasoning (`thinking`) is captured as separate spans
- **Tool call tracking** -- every tool use (Read, Write, Bash, etc.) is captured with inputs and outputs
- **Token usage** -- input/output/cache token counts are recorded on each generation
- **Stop reason** -- `end_turn`, `tool_use`, etc. tracked in metadata
- **Session grouping** -- traces are grouped by Claude Code session ID
- **Incremental processing** -- only new transcript entries are sent (no duplicates)
- **Incomplete turn capture** -- if the session exits before a response, user messages are still recorded
- **Fail-open design** -- if anything goes wrong the hook exits silently; Claude Code is never blocked
- **Cross-platform** -- works on macOS, Linux, and Windows
- **Dual SDK support** -- works with both langfuse `>= 3.12` (nested spans) and older versions (flat traces)

## Prerequisites

- **Claude Code** -- installed and working ([install guide](https://docs.anthropic.com/en/docs/claude-code))
- **Python 3.8+** -- with `pip` available (`python3 -m pip --version` to verify)
- **Langfuse account** -- [cloud.langfuse.com](https://cloud.langfuse.com) (free tier available) or a self-hosted instance

## Quick Start

```bash
# Clone and run the installer
git clone https://github.com/BAEM1N/langfuse-claude-code.git
cd langfuse-claude-code
bash install.sh
```

On Windows (PowerShell):

```powershell
git clone https://github.com/BAEM1N/langfuse-claude-code.git
cd langfuse-claude-code
.\install.ps1
```

The installer will:
1. Check Python 3.8+ is available
2. Install the `langfuse` Python package
3. Copy the hook script to `~/.claude/hooks/`
4. Prompt you for your Langfuse credentials:
   - Public Key (`pk-lf-...`)
   - Secret Key (`sk-lf-...`, masked input)
   - Base URL (defaults to `https://cloud.langfuse.com`)
   - User ID (defaults to `claude-user`)
5. Merge the hook + env into `~/.claude/settings.json` (preserves your existing settings)
6. Verify the installation

## Manual Setup

### 1. Install the langfuse SDK

```bash
pip install langfuse
```

### 2. Copy the hook script

```bash
mkdir -p ~/.claude/hooks
cp langfuse_hook.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/langfuse_hook.py
```

### 3. Configure `~/.claude/settings.json`

Add (or merge) the following into your settings file:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/langfuse_hook.py"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/langfuse_hook.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/langfuse_hook.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/langfuse_hook.py"
          }
        ]
      }
    ]
  },
  "env": {
    "TRACE_TO_LANGFUSE": "true",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-...",
    "LANGFUSE_SECRET_KEY": "sk-lf-...",
    "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
    "LANGFUSE_USER_ID": "your-username"
  }
}
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRACE_TO_LANGFUSE` | Yes | - | Set to `"true"` to enable tracing |
| `LANGFUSE_PUBLIC_KEY` | Yes | - | Langfuse public key (or `CC_LANGFUSE_PUBLIC_KEY`) |
| `LANGFUSE_SECRET_KEY` | Yes | - | Langfuse secret key (or `CC_LANGFUSE_SECRET_KEY`) |
| `LANGFUSE_BASE_URL` | No | `https://cloud.langfuse.com` | Langfuse host URL (or `CC_LANGFUSE_BASE_URL`) |
| `LANGFUSE_USER_ID` | No | `claude-user` | User ID for trace attribution (or `CC_LANGFUSE_USER_ID`) |
| `CC_LANGFUSE_DEBUG` | No | `false` | Set to `"true"` for verbose logging |
| `CC_LANGFUSE_MAX_CHARS` | No | `20000` | Max characters per text field before truncation |

All `LANGFUSE_*` variables also accept a `CC_LANGFUSE_*` prefix (which takes priority).

### Self-hosted Langfuse

Set `LANGFUSE_BASE_URL` to your instance URL:

```json
"LANGFUSE_BASE_URL": "https://langfuse.your-company.com"
```

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Code                          │
│                                                         │
│  User prompt ──► Model response ──► Tool calls ──► ...  │
│       │                                                 │
│       ▼                                                 │
│  Transcript file (.jsonl)                               │
│       │                                                 │
│       │  ┌──── Stop Hook ────┐                          │
│       └─►│ langfuse_hook.py  │                          │
│          │                   │                           │
│          │ 1. Read new JSONL │                           │
│          │ 2. Build turns    │                           │
│          │ 3. Emit traces    │                           │
│          └───────┬───────────┘                           │
│                  │                                       │
└──────────────────┼───────────────────────────────────────┘
                   │
                   ▼
          ┌─────────────────────┐
          │      Langfuse        │
          │                      │
          │  Trace (Turn 1)      │
          │  ├─ System Prompt    │
          │  ├─ Generation       │
          │  │   ├─ model        │
          │  │   ├─ usage tokens │
          │  │   └─ stop_reason  │
          │  ├─ Thinking [1]     │
          │  ├─ Text [1]         │
          │  ├─ Tool: Read       │
          │  ├─ Text [2]         │
          │  ├─ Tool: Write      │
          │  └─ Text [3]         │
          │                      │
          │  Session: abc123     │
          └─────────────────────┘
```

**Flow:**

1. Claude Code writes conversation data to a JSONL transcript file
2. On every **Stop** event (after each model response) and **Notification** event, the hook reads the transcript
3. On **PreToolUse** and **PostToolUse** events, the hook emits real-time tool spans independently
4. The hook reads only **new** lines from the transcript (using a file offset saved in state)
5. New messages are grouped into user-assistant **turns**
6. Each turn is emitted as a Langfuse **trace** with:
   - A **system prompt** span (if present)
   - A **generation** observation (with model, token usage, stop reason)
   - Ordered content spans preserving the full assistant flow:
     - **Thinking** spans for internal reasoning blocks
     - **Text** spans for assistant text between tool calls
     - **Tool** spans for each tool call (with input/output)
   - Real-time **Before Tool** / **After Tool** spans (from PreToolUse/PostToolUse)
7. All traces share the same `session_id` for grouping

## Compatibility

| Component | Version |
|-----------|---------|
| Python | 3.8+ |
| langfuse SDK | 2.0+ (flat traces), 3.12+ (nested spans) |
| Claude Code | Any version with hooks support |
| OS | macOS, Linux, Windows |

## Troubleshooting

### Traces not appearing

1. Verify `TRACE_TO_LANGFUSE` is set to `"true"` in your settings
2. Check that your API keys are correct
3. Enable debug logging: set `CC_LANGFUSE_DEBUG` to `"true"`
4. Check the log file: `~/.claude/state/langfuse_hook.log`

### Hook not firing

1. Confirm the hooks are in `~/.claude/settings.json` under `hooks.Stop`, `hooks.Notification`, `hooks.PreToolUse`, and `hooks.PostToolUse`
2. Verify the Python path in the command is correct (`python3` vs `python`)
3. Test manually: `echo '{}' | python3 ~/.claude/hooks/langfuse_hook.py`

### Duplicate traces

The hook tracks file offsets in `~/.claude/state/langfuse_state.json`. If this file is deleted, previously-sent turns will be re-sent on the next invocation. Delete the state file only if you want a fresh start.

### Large text truncation

By default, text fields are truncated at 20,000 characters. Adjust with `CC_LANGFUSE_MAX_CHARS`:

```json
"CC_LANGFUSE_MAX_CHARS": "50000"
```

## Uninstall

1. Remove the hook entries from `~/.claude/settings.json` (delete the `Stop` hook, `Notification` hook, and the `env` keys)
2. Delete the hook script: `rm ~/.claude/hooks/langfuse_hook.py`
3. Optionally remove state: `rm ~/.claude/state/langfuse_state.json`

## License

[MIT](LICENSE)
