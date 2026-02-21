#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
# claude-code-langfuse installer (macOS / Linux)
# ─────────────────────────────────────────────

HOOK_NAME="langfuse_hook.py"
CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  claude-code-langfuse installer          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ──────────────────────────
step "Checking Python installation..."
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    error "Python not found. Please install Python 3.8+ first."
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Found $PYTHON ($PY_VERSION)"

# ── 2. Install langfuse SDK ──────────────────
step "Installing langfuse Python SDK..."
$PYTHON -m pip install --quiet --upgrade langfuse
info "langfuse SDK installed."

# ── 3. Copy hook script ─────────────────────
step "Copying hook script..."
mkdir -p "$HOOKS_DIR"
cp "$SCRIPT_DIR/$HOOK_NAME" "$HOOKS_DIR/$HOOK_NAME"
chmod +x "$HOOKS_DIR/$HOOK_NAME"
info "Hook script copied to $HOOKS_DIR/$HOOK_NAME"

# ── 4. Collect Langfuse credentials ─────────
echo ""
step "Configuring Langfuse credentials..."
echo "  Get your keys from https://cloud.langfuse.com (or your self-hosted instance)."
echo ""

read -rp "  Langfuse Public Key : " LF_PUBLIC_KEY
read -rp "  Langfuse Secret Key : " LF_SECRET_KEY
read -rp "  Langfuse Base URL   [https://cloud.langfuse.com]: " LF_BASE_URL
LF_BASE_URL="${LF_BASE_URL:-https://cloud.langfuse.com}"

read -rp "  User ID (for trace attribution) [claude-user]: " LF_USER_ID
LF_USER_ID="${LF_USER_ID:-claude-user}"

if [[ -z "$LF_PUBLIC_KEY" || -z "$LF_SECRET_KEY" ]]; then
    error "Public Key and Secret Key are required."
    exit 1
fi

# ── 5. Merge into settings.json ─────────────
step "Updating $SETTINGS_FILE..."
mkdir -p "$CLAUDE_DIR"

# Build the hook + env patch as JSON
PATCH=$(cat <<ENDJSON
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$PYTHON ~/.claude/hooks/langfuse_hook.py"
          }
        ]
      }
    ]
  },
  "env": {
    "TRACE_TO_LANGFUSE": "true",
    "LANGFUSE_PUBLIC_KEY": "$LF_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY": "$LF_SECRET_KEY",
    "LANGFUSE_BASE_URL": "$LF_BASE_URL",
    "LANGFUSE_USER_ID": "$LF_USER_ID"
  }
}
ENDJSON
)

# Merge using Python (works everywhere, no jq dependency)
$PYTHON - "$SETTINGS_FILE" "$PATCH" <<'PYEOF'
import json, sys, os

settings_path = sys.argv[1]
patch = json.loads(sys.argv[2])

# Load existing settings
if os.path.exists(settings_path):
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
else:
    settings = {}

# Deep merge: patch overwrites at the hook/env level
for key in patch:
    if key in settings and isinstance(settings[key], dict) and isinstance(patch[key], dict):
        settings[key].update(patch[key])
    else:
        settings[key] = patch[key]

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Settings written to {settings_path}")
PYEOF

# ── Done ─────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Installation complete!                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
info "Claude Code will now send traces to Langfuse on every Stop event."
info "Open your Langfuse dashboard to see traces appear."
echo ""
info "To disable, set TRACE_TO_LANGFUSE=false in $SETTINGS_FILE"
info "Logs: ~/.claude/state/langfuse_hook.log"
info "Debug: set CC_LANGFUSE_DEBUG=true in env section"
echo ""
