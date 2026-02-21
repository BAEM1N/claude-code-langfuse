# ─────────────────────────────────────────────
# claude-code-langfuse installer (Windows)
# ─────────────────────────────────────────────
#Requires -Version 5.1

$ErrorActionPreference = "Stop"

$HookName     = "langfuse_hook.py"
$ClaudeDir    = Join-Path $env:USERPROFILE ".claude"
$HooksDir     = Join-Path $ClaudeDir "hooks"
$StateDir     = Join-Path $ClaudeDir "state"
$SettingsFile = Join-Path $ClaudeDir "settings.json"
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step  ($msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Info  ($msg) { Write-Host "[INFO] $msg" -ForegroundColor Green }
function Write-Warn  ($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================"
Write-Host "   claude-code-langfuse installer"
Write-Host "============================================"
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
$PyMajor   = & $Python -c "import sys; print(sys.version_info.major)"
$PyMinor   = & $Python -c "import sys; print(sys.version_info.minor)"

if ([int]$PyMajor -lt 3 -or ([int]$PyMajor -eq 3 -and [int]$PyMinor -lt 8)) {
    Write-Err "Python 3.8+ required, found $PyVersion"
    exit 1
}

Write-Info "Found $Python ($PyVersion)"

# ── 2. Install langfuse SDK ──────────────────
Write-Step "Installing langfuse Python SDK..."
& $Python -m pip install --quiet --upgrade langfuse
Write-Info "langfuse SDK installed."

# ── 3. Copy hook script ─────────────────────
Write-Step "Copying hook script..."
if (-not (Test-Path $HooksDir)) { New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null }
Copy-Item (Join-Path $ScriptDir $HookName) -Destination (Join-Path $HooksDir $HookName) -Force
Write-Info "Hook script installed: $HooksDir\$HookName"

# ── 4. Clean previous state (optional) ──────
$StateFile = Join-Path $StateDir "langfuse_state.json"
if (Test-Path $StateFile) {
    Write-Host ""
    $ResetState = Read-Host "  Previous state file found. Reset trace offsets? [y/N]"
    if ($ResetState -eq "y" -or $ResetState -eq "Y") {
        Remove-Item $StateFile -Force
        Write-Info "State file reset."
    }
}

# ── 5. Collect Langfuse credentials ─────────
Write-Host ""
Write-Step "Configuring Langfuse credentials..."
Write-Host "  Get your keys from https://cloud.langfuse.com (or your self-hosted instance)."
Write-Host ""

$LfPublicKey = Read-Host "  Langfuse Public Key "
$LfSecretKeySecure = Read-Host "  Langfuse Secret Key " -AsSecureString
$LfSecretKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($LfSecretKeySecure)
)

$LfBaseUrl = Read-Host "  Langfuse Base URL   [https://cloud.langfuse.com]"
if ([string]::IsNullOrWhiteSpace($LfBaseUrl)) { $LfBaseUrl = "https://cloud.langfuse.com" }

$LfUserId = Read-Host "  User ID (trace attribution) [claude-user]"
if ([string]::IsNullOrWhiteSpace($LfUserId)) { $LfUserId = "claude-user" }

if ([string]::IsNullOrWhiteSpace($LfPublicKey) -or [string]::IsNullOrWhiteSpace($LfSecretKey)) {
    Write-Err "Public Key and Secret Key are required."
    exit 1
}

# ── 6. Merge into settings.json ─────────────
Write-Step "Updating $SettingsFile..."
if (-not (Test-Path $ClaudeDir)) { New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null }

$HookCmd = "$Python ~/.claude/hooks/langfuse_hook.py"

# Smart merge: preserves existing hooks/env, only adds/updates langfuse entries
$MergeScript = @'
import json, sys, os

settings_path = sys.argv[1]
hook_command  = sys.argv[2]
public_key    = sys.argv[3]
secret_key    = sys.argv[4]
base_url      = sys.argv[5]
user_id       = sys.argv[6]

if os.path.exists(settings_path):
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
else:
    settings = {}

# Merge env (preserve existing keys)
if "env" not in settings or not isinstance(settings["env"], dict):
    settings["env"] = {}
settings["env"]["TRACE_TO_LANGFUSE"]  = "true"
settings["env"]["LANGFUSE_PUBLIC_KEY"] = public_key
settings["env"]["LANGFUSE_SECRET_KEY"] = secret_key
settings["env"]["LANGFUSE_BASE_URL"]   = base_url
settings["env"]["LANGFUSE_USER_ID"]    = user_id

# Merge hooks (preserve existing hooks)
if "hooks" not in settings or not isinstance(settings["hooks"], dict):
    settings["hooks"] = {}

langfuse_entry = {
    "hooks": [{"type": "command", "command": hook_command}]
}

def upsert_hook(settings, event_name, langfuse_entry):
    hook_list = settings["hooks"].get(event_name, [])
    if not isinstance(hook_list, list):
        hook_list = []
    replaced = False
    for i, entry in enumerate(hook_list):
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []):
            if isinstance(h, dict) and "langfuse_hook" in h.get("command", ""):
                hook_list[i] = langfuse_entry
                replaced = True
                break
        if replaced:
            break
    if not replaced:
        hook_list.append(langfuse_entry)
    settings["hooks"][event_name] = hook_list
    return len(hook_list), replaced

n_stop, stop_replaced = upsert_hook(settings, "Stop", langfuse_entry)
n_notif, notif_replaced = upsert_hook(settings, "Notification", langfuse_entry)

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Settings written to {settings_path}")
print(f"  Stop hooks: {n_stop} total ({'updated' if stop_replaced else 'added'} langfuse hook)")
print(f"  Notification hooks: {n_notif} total ({'updated' if notif_replaced else 'added'} langfuse hook)")
'@

& $Python -c $MergeScript $SettingsFile $HookCmd $LfPublicKey $LfSecretKey $LfBaseUrl $LfUserId

# ── 7. Verify ────────────────────────────────
Write-Step "Verifying installation..."
$ImportCheck = & $Python -c "import langfuse; print('ok')" 2>&1
if ($ImportCheck -eq "ok") {
    Write-Info "langfuse SDK: OK"
} else {
    Write-Warn "langfuse SDK import failed. Check your Python environment."
}

if (Test-Path (Join-Path $HooksDir $HookName)) {
    Write-Info "Hook script: OK"
} else {
    Write-Warn "Hook script not found."
}

# ── Done ─────────────────────────────────────
Write-Host ""
Write-Host "============================================"
Write-Host "   Installation complete!"
Write-Host "============================================"
Write-Host ""
Write-Info "Claude Code will now send traces to Langfuse on every Stop event."
Write-Info "Start (or restart) Claude Code to activate the hook."
Write-Host ""
Write-Host "  Dashboard : $LfBaseUrl"
Write-Host "  Logs      : ~/.claude/state/langfuse_hook.log"
Write-Host "  Debug     : set CC_LANGFUSE_DEBUG=true in settings.json env"
Write-Host "  Disable   : set TRACE_TO_LANGFUSE=false in settings.json env"
Write-Host ""
