# ─────────────────────────────────────────────
# claude-code-langfuse installer (Windows)
# ─────────────────────────────────────────────
#Requires -Version 5.1

$ErrorActionPreference = "Stop"

$HookName     = "langfuse_hook.py"
$ClaudeDir    = Join-Path $env:USERPROFILE ".claude"
$HooksDir     = Join-Path $ClaudeDir "hooks"
$SettingsFile = Join-Path $ClaudeDir "settings.json"
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step  ($msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Info  ($msg) { Write-Host "[INFO] $msg" -ForegroundColor Green }
function Write-Warn  ($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗"
Write-Host "║  claude-code-langfuse installer          ║"
Write-Host "╚══════════════════════════════════════════╝"
Write-Host ""

# ── 1. Check Python ──────────────────────────
Write-Step "Checking Python installation..."
$Python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $Python = "python3"
} else {
    Write-Err "Python not found. Please install Python 3.8+ first."
    exit 1
}

$PyVersion = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Info "Found $Python ($PyVersion)"

# ── 2. Install langfuse SDK ──────────────────
Write-Step "Installing langfuse Python SDK..."
& $Python -m pip install --quiet --upgrade langfuse
Write-Info "langfuse SDK installed."

# ── 3. Copy hook script ─────────────────────
Write-Step "Copying hook script..."
if (-not (Test-Path $HooksDir)) { New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null }
Copy-Item (Join-Path $ScriptDir $HookName) -Destination (Join-Path $HooksDir $HookName) -Force
Write-Info "Hook script copied to $HooksDir\$HookName"

# ── 4. Collect Langfuse credentials ─────────
Write-Host ""
Write-Step "Configuring Langfuse credentials..."
Write-Host "  Get your keys from https://cloud.langfuse.com (or your self-hosted instance)."
Write-Host ""

$LfPublicKey = Read-Host "  Langfuse Public Key "
$LfSecretKey = Read-Host "  Langfuse Secret Key "
$LfBaseUrl   = Read-Host "  Langfuse Base URL   [https://cloud.langfuse.com]"
if ([string]::IsNullOrWhiteSpace($LfBaseUrl)) { $LfBaseUrl = "https://cloud.langfuse.com" }

$LfUserId = Read-Host "  User ID (for trace attribution) [claude-user]"
if ([string]::IsNullOrWhiteSpace($LfUserId)) { $LfUserId = "claude-user" }

if ([string]::IsNullOrWhiteSpace($LfPublicKey) -or [string]::IsNullOrWhiteSpace($LfSecretKey)) {
    Write-Err "Public Key and Secret Key are required."
    exit 1
}

# ── 5. Merge into settings.json ─────────────
Write-Step "Updating $SettingsFile..."
if (-not (Test-Path $ClaudeDir)) { New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null }

$PatchJson = @"
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$Python ~/.claude/hooks/langfuse_hook.py"
          }
        ]
      }
    ]
  },
  "env": {
    "TRACE_TO_LANGFUSE": "true",
    "LANGFUSE_PUBLIC_KEY": "$LfPublicKey",
    "LANGFUSE_SECRET_KEY": "$LfSecretKey",
    "LANGFUSE_BASE_URL": "$LfBaseUrl",
    "LANGFUSE_USER_ID": "$LfUserId"
  }
}
"@

$MergeScript = @'
import json, sys, os

settings_path = sys.argv[1]
patch = json.loads(sys.argv[2])

if os.path.exists(settings_path):
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
else:
    settings = {}

for key in patch:
    if key in settings and isinstance(settings[key], dict) and isinstance(patch[key], dict):
        settings[key].update(patch[key])
    else:
        settings[key] = patch[key]

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Settings written to {settings_path}")
'@

& $Python -c $MergeScript $SettingsFile $PatchJson

# ── Done ─────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════╗"
Write-Host "║  Installation complete!                  ║"
Write-Host "╚══════════════════════════════════════════╝"
Write-Host ""
Write-Info "Claude Code will now send traces to Langfuse on every Stop event."
Write-Info "Open your Langfuse dashboard to see traces appear."
Write-Host ""
Write-Info "To disable, set TRACE_TO_LANGFUSE=false in $SettingsFile"
Write-Info "Logs: ~/.claude/state/langfuse_hook.log"
Write-Info "Debug: set CC_LANGFUSE_DEBUG=true in env section"
Write-Host ""
