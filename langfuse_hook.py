#!/usr/bin/env python3
"""
Claude Code -> Langfuse hook

Automatically traces Claude Code conversations to Langfuse.
Hooks into all available Claude Code events for comprehensive observability.

Captured data:
  - System prompts
  - User messages
  - Assistant text (all interleaved blocks, including thinking)
  - Tool calls with inputs and outputs (from transcript + real-time hooks)
  - Token usage (input, output, cache)
  - Stop reason
  - Session grouping
  - Real-time tool events (PreToolUse / PostToolUse)

Usage:
  Configure as hooks in ~/.claude/settings.json
  See README.md for full setup instructions.
"""

import json
import os
import socket
import sys
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Load .env file (fail-open, no dependencies) ---
def _load_dotenv() -> None:
    """Load user-level .env file from ~/.claude/.env into os.environ.

    Configuration hierarchy (highest priority first):
      1. os.environ (system env vars, settings.json env section)
      2. ~/.claude/.env (user-level credentials)

    Project-level config should use settings.json env section.
    Only sets variables that are NOT already set (env/json take priority).
    """
    env_path = Path.home() / ".claude" / ".env"
    try:
        if not env_path.exists():
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass

_load_dotenv()

# --- Langfuse import (fail-open) ---
try:
    from langfuse import Langfuse
except Exception:
    sys.exit(0)

# propagate_attributes: langfuse >= 3.12 (Python >= 3.10)
_HAS_PROPAGATE = False
try:
    from langfuse import propagate_attributes
    _HAS_PROPAGATE = True
except ImportError:
    pass

# --- Paths ---
STATE_DIR = Path.home() / ".claude" / "state"
LOG_FILE = STATE_DIR / "langfuse_hook.log"
STATE_FILE = STATE_DIR / "langfuse_state.json"
LOCK_FILE = STATE_DIR / "langfuse_state.lock"

DEBUG = os.environ.get("CC_LANGFUSE_DEBUG", "").lower() == "true"
MAX_CHARS = int(os.environ.get("CC_LANGFUSE_MAX_CHARS", "20000"))
BUFFER_FILE = STATE_DIR / "langfuse_tool_buffer.jsonl"

# ----------------- Logging -----------------
def _log(level: str, message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} [{level}] {message}\n")
    except Exception:
        pass

def debug(msg: str) -> None:
    if DEBUG:
        _log("DEBUG", msg)

def info(msg: str) -> None:
    _log("INFO", msg)

def warn(msg: str) -> None:
    _log("WARN", msg)

def error(msg: str) -> None:
    _log("ERROR", msg)

# ----------------- State locking (best-effort, cross-platform) -----------------
_IS_WIN = sys.platform == "win32"

class FileLock:
    def __init__(self, path: Path, timeout_s: float = 2.0):
        self.path = path
        self.timeout_s = timeout_s
        self._fh = None

    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+", encoding="utf-8")
        deadline = time.time() + self.timeout_s
        if _IS_WIN:
            try:
                import msvcrt
                while True:
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except (OSError, IOError):
                        if time.time() > deadline:
                            break
                        time.sleep(0.05)
            except Exception:
                pass
        else:
            try:
                import fcntl
                while True:
                    try:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.time() > deadline:
                            break
                        time.sleep(0.05)
            except Exception:
                pass
        return self

    def __exit__(self, exc_type, exc, tb):
        if _IS_WIN:
            try:
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        else:
            try:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            self._fh.close()
        except Exception:
            pass

def load_state() -> Dict[str, Any]:
    try:
        if not STATE_FILE.exists():
            return {}
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        debug(f"save_state failed: {e}")

def state_key(session_id: str, transcript_path: str) -> str:
    raw = f"{session_id}::{transcript_path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

# ----------------- Hook payload -----------------
def read_hook_payload() -> Dict[str, Any]:
    try:
        data = sys.stdin.read()
        if not data.strip():
            return {}
        return json.loads(data)
    except Exception:
        return {}

@dataclass
class SessionContext:
    session_id: Optional[str] = None
    transcript_path: Optional[Path] = None
    cwd: Optional[str] = None
    permission_mode: Optional[str] = None

def extract_session_context(payload: Dict[str, Any]) -> SessionContext:
    session_id = (
        payload.get("sessionId")
        or payload.get("session_id")
        or payload.get("session", {}).get("id")
    )
    transcript = (
        payload.get("transcriptPath")
        or payload.get("transcript_path")
        or payload.get("transcript", {}).get("path")
    )
    if transcript:
        try:
            transcript_path = Path(transcript).expanduser().resolve()
        except Exception:
            transcript_path = None
    else:
        transcript_path = None

    cwd = payload.get("cwd")
    permission_mode = payload.get("permission_mode")

    return SessionContext(
        session_id=session_id,
        transcript_path=transcript_path,
        cwd=cwd,
        permission_mode=permission_mode,
    )

# ----------------- Transcript parsing helpers -----------------
def get_content(msg: Dict[str, Any]) -> Any:
    if not isinstance(msg, dict):
        return None
    if "message" in msg and isinstance(msg.get("message"), dict):
        return msg["message"].get("content")
    return msg.get("content")

def get_role(msg: Dict[str, Any]) -> Optional[str]:
    t = msg.get("type")
    if t in ("user", "assistant", "system"):
        return t
    m = msg.get("message")
    if isinstance(m, dict):
        r = m.get("role")
        if r in ("user", "assistant", "system"):
            return r
    return None

def is_tool_result(msg: Dict[str, Any]) -> bool:
    role = get_role(msg)
    if role != "user":
        return False
    content = get_content(msg)
    if isinstance(content, list):
        return any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content)
    return False

def iter_tool_results(content: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if isinstance(content, list):
        for x in content:
            if isinstance(x, dict) and x.get("type") == "tool_result":
                out.append(x)
    return out

def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for x in content:
            if isinstance(x, dict) and x.get("type") == "text":
                parts.append(x.get("text", ""))
            elif isinstance(x, str):
                parts.append(x)
        return "\n".join([p for p in parts if p])
    return ""

def truncate_text(s: str, max_chars: int = MAX_CHARS) -> Tuple[str, Dict[str, Any]]:
    if s is None:
        return "", {"truncated": False, "orig_len": 0}
    orig_len = len(s)
    if orig_len <= max_chars:
        return s, {"truncated": False, "orig_len": orig_len}
    head = s[:max_chars]
    return head, {"truncated": True, "orig_len": orig_len, "kept_len": len(head), "sha256": hashlib.sha256(s.encode("utf-8")).hexdigest()}

def get_model(msg: Dict[str, Any]) -> str:
    m = msg.get("message")
    if isinstance(m, dict):
        return m.get("model") or "claude"
    return "claude"

def get_message_id(msg: Dict[str, Any]) -> Optional[str]:
    m = msg.get("message")
    if isinstance(m, dict):
        mid = m.get("id")
        if isinstance(mid, str) and mid:
            return mid
    return None

def get_usage(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    m = msg.get("message")
    if isinstance(m, dict):
        u = m.get("usage")
        if isinstance(u, dict):
            return u
    return None

def get_stop_reason(msg: Dict[str, Any]) -> Optional[str]:
    m = msg.get("message")
    if isinstance(m, dict):
        return m.get("stop_reason")
    return None

def aggregate_usage(assistant_msgs: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    def to_int(v: Any) -> int:
        if isinstance(v, bool):
            return 0
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            try:
                return int(float(v))
            except Exception:
                return 0
        return 0

    total_input = 0
    total_output = 0
    cache_creation = 0
    cache_read = 0
    reasoning = 0
    found = False
    for msg in assistant_msgs:
        usage = get_usage(msg)
        if usage:
            found = True
            total_input += to_int(usage.get("input_tokens"))
            total_output += to_int(usage.get("output_tokens"))
            cache_creation += to_int(usage.get("cache_creation_input_tokens"))
            cache_read += to_int(usage.get("cache_read_input_tokens"))
            # Future-proofing: include reasoning token fields when present
            reasoning += to_int(usage.get("reasoning_tokens")) or to_int(usage.get("reasoning_output_tokens"))
    if not found:
        return None
    result: Dict[str, int] = {
        "input": total_input,
        "output": total_output,
    }
    if cache_creation:
        result["input_cache_creation"] = cache_creation
    if cache_read:
        result["input_cache_read"] = cache_read
    if reasoning:
        result["reasoning"] = reasoning
    result["total"] = total_input + total_output
    return result

def extract_all_text(assistant_msgs: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for msg in assistant_msgs:
        t = extract_text(get_content(msg))
        if t:
            parts.append(t)
    return "\n".join(parts)

# ----------------- Incremental reader -----------------
@dataclass
class SessionState:
    offset: int = 0
    buffer: str = ""
    turn_count: int = 0

def load_session_state(global_state: Dict[str, Any], key: str) -> SessionState:
    s = global_state.get(key, {})
    return SessionState(
        offset=int(s.get("offset", 0)),
        buffer=str(s.get("buffer", "")),
        turn_count=int(s.get("turn_count", 0)),
    )

def write_session_state(global_state: Dict[str, Any], key: str, ss: SessionState) -> None:
    global_state[key] = {
        "offset": ss.offset,
        "buffer": ss.buffer,
        "turn_count": ss.turn_count,
        "updated": datetime.now(timezone.utc).isoformat(),
    }

def read_new_jsonl(transcript_path: Path, ss: SessionState) -> Tuple[List[Dict[str, Any]], SessionState]:
    if not transcript_path.exists():
        return [], ss
    try:
        with open(transcript_path, "rb") as f:
            f.seek(ss.offset)
            chunk = f.read()
            new_offset = f.tell()
    except Exception as e:
        debug(f"read_new_jsonl failed: {e}")
        return [], ss
    if not chunk:
        return [], ss
    try:
        text = chunk.decode("utf-8", errors="replace")
    except Exception:
        text = chunk.decode(errors="replace")
    combined = ss.buffer + text
    lines = combined.split("\n")
    ss.buffer = lines[-1]
    ss.offset = new_offset
    msgs: List[Dict[str, Any]] = []
    for line in lines[:-1]:
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line))
        except Exception:
            continue
    return msgs, ss

# ----------------- Turn assembly -----------------
@dataclass
class Turn:
    user_msg: Dict[str, Any]
    assistant_msgs: List[Dict[str, Any]]
    tool_results_by_id: Dict[str, Any]
    system_msgs: List[Dict[str, Any]] = field(default_factory=list)

def build_turns(messages: List[Dict[str, Any]]) -> List[Turn]:
    turns: List[Turn] = []
    current_user: Optional[Dict[str, Any]] = None
    assistant_order: List[str] = []
    assistant_latest: Dict[str, Dict[str, Any]] = {}
    tool_results_by_id: Dict[str, Any] = {}
    pending_system: List[Dict[str, Any]] = []
    system_for_turn: List[Dict[str, Any]] = []

    def flush_turn():
        nonlocal current_user, assistant_order, assistant_latest, tool_results_by_id, turns, system_for_turn
        if current_user is None:
            return
        assistants = [assistant_latest[mid] for mid in assistant_order if mid in assistant_latest]
        turns.append(Turn(
            user_msg=current_user,
            assistant_msgs=assistants,
            tool_results_by_id=dict(tool_results_by_id),
            system_msgs=list(system_for_turn),
        ))

    for msg in messages:
        role = get_role(msg)
        if role == "system":
            pending_system.append(msg)
            continue
        if is_tool_result(msg):
            for tr in iter_tool_results(get_content(msg)):
                tid = tr.get("tool_use_id")
                if tid:
                    tool_results_by_id[str(tid)] = tr.get("content")
            continue
        if role == "user":
            flush_turn()
            current_user = msg
            assistant_order = []
            assistant_latest = {}
            tool_results_by_id = {}
            system_for_turn = list(pending_system)
            pending_system = []
            continue
        if role == "assistant":
            if current_user is None:
                continue
            mid = get_message_id(msg) or f"noid:{len(assistant_order)}"
            if mid not in assistant_latest:
                assistant_order.append(mid)
            assistant_latest[mid] = msg
            continue

    flush_turn()
    return turns

# ----------------- Content sequence builder -----------------
def build_content_sequence(
    assistant_msgs: List[Dict[str, Any]],
    tool_results_by_id: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build ordered sequence of all content blocks (text, thinking, tool_use)."""
    sequence: List[Dict[str, Any]] = []
    for msg in assistant_msgs:
        content = get_content(msg)
        if isinstance(content, str):
            if content.strip():
                sequence.append({"type": "text", "text": content})
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                if isinstance(block, str) and block.strip():
                    sequence.append({"type": "text", "text": block})
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text.strip():
                    sequence.append({"type": "text", "text": text})
            elif btype == "thinking":
                thinking = block.get("thinking", "")
                if thinking.strip():
                    sequence.append({"type": "thinking", "text": thinking})
            elif btype == "tool_use":
                tid = str(block.get("id", ""))
                entry: Dict[str, Any] = {
                    "type": "tool_use",
                    "id": tid,
                    "name": block.get("name", "unknown"),
                    "input": block.get("input") if isinstance(block.get("input"), (dict, list, str, int, float, bool)) else {},
                }
                if tid and tid in tool_results_by_id:
                    out_raw = tool_results_by_id[tid]
                    out_str = out_raw if isinstance(out_raw, str) else json.dumps(out_raw, ensure_ascii=False)
                    out_trunc, out_meta = truncate_text(out_str)
                    entry["output"] = out_trunc
                    entry["output_meta"] = out_meta
                else:
                    entry["output"] = None
                    entry["output_meta"] = None
                sequence.append(entry)
    return sequence

# ----------------- Langfuse emit -----------------
def emit_turn(
    langfuse: Langfuse,
    session_id: str,
    turn_num: int,
    turn: Turn,
    transcript_path: Path,
    ctx: Optional[SessionContext] = None,
    hostname: str = "",
    hook_event_type: str = "Stop",
    hook_tool_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    # User text
    user_text_raw = extract_text(get_content(turn.user_msg))
    user_text, user_text_meta = truncate_text(user_text_raw)

    user_id = os.environ.get("CC_LANGFUSE_USER_ID") or os.environ.get("LANGFUSE_USER_ID") or "claude-user"

    # Incomplete turn (user message without assistant response, e.g. Ctrl+C)
    if not turn.assistant_msgs:
        debug(f"Incomplete turn {turn_num}: user message only (no assistant response)")
        trace_meta: Dict[str, Any] = {
            "source": "claude-code",
            "session_id": session_id,
            "turn_number": turn_num,
            "transcript_path": str(transcript_path),
            "cwd": ctx.cwd if ctx else None,
            "hostname": hostname,
            "incomplete": True,
            "user_text": user_text_meta,
        }
        if _HAS_PROPAGATE:
            with propagate_attributes(
                session_id=session_id,
                user_id=user_id,
                trace_name=f"Claude Code - Turn {turn_num} (incomplete)",
                tags=["claude-code", "incomplete", hostname],
            ):
                with langfuse.start_as_current_span(
                    name=f"Claude Code - Turn {turn_num} (incomplete)",
                    input={"role": "user", "content": user_text},
                    metadata=trace_meta,
                ) as span:
                    span.update(output={"status": "incomplete", "reason": "no assistant response"})
        else:
            with langfuse.start_as_current_span(
                name=f"Claude Code - Turn {turn_num} (incomplete)",
                input={"role": "user", "content": user_text},
                metadata=trace_meta,
            ) as span:
                langfuse.update_current_trace(
                    name=f"Claude Code - Turn {turn_num} (incomplete)",
                    session_id=session_id,
                    user_id=user_id,
                    tags=["claude-code", "incomplete", hostname],
                )
                span.update(output={"status": "incomplete", "reason": "no assistant response"})
        return

    # All assistant text (concatenated from all messages)
    assistant_text_raw = extract_all_text(turn.assistant_msgs)
    assistant_text, assistant_text_meta = truncate_text(assistant_text_raw)

    # System prompt
    system_text = ""
    if turn.system_msgs:
        system_parts: List[str] = []
        for sm in turn.system_msgs:
            st = extract_text(get_content(sm))
            if st:
                system_parts.append(st)
        system_text = "\n---\n".join(system_parts)
    system_text_trunc, system_text_meta = truncate_text(system_text) if system_text else ("", {"truncated": False, "orig_len": 0})

    # Content sequence (ordered: text, thinking, tool_use blocks)
    sequence = build_content_sequence(turn.assistant_msgs, turn.tool_results_by_id)

    # Model, usage, stop_reason
    model = get_model(turn.assistant_msgs[0])
    usage = aggregate_usage(turn.assistant_msgs)
    stop_reason = get_stop_reason(turn.assistant_msgs[-1])

    # Count block types
    n_text = sum(1 for s in sequence if s["type"] == "text")
    n_thinking = sum(1 for s in sequence if s["type"] == "thinking")
    n_tools = sum(1 for s in sequence if s["type"] == "tool_use")

    trace_meta = {
        "source": "claude-code",
        "product": "claude-code",
        "reconstruction": "hook-transcript-plus-tool-buffer",
        "session_id": session_id,
        "turn_number": turn_num,
        "transcript_path": str(transcript_path),
        "cwd": ctx.cwd if ctx else None,
        "hostname": hostname,
        "hook_event": hook_event_type,
        "permission_mode": ctx.permission_mode if ctx else None,
        "stop_reason": stop_reason,
        "has_system_prompt": bool(system_text),
        "content_blocks": len(sequence),
        "text_blocks": n_text,
        "thinking_blocks": n_thinking,
        "tool_blocks": n_tools,
        "user_text": user_text_meta,
        "hook_tool_events": len(hook_tool_events or []),
    }
    if usage:
        trace_meta["usage"] = usage

    if _HAS_PROPAGATE:
        _emit_modern(
            langfuse, session_id, user_id, turn_num,
            user_text, assistant_text, assistant_text_meta,
            model, usage, stop_reason,
            system_text_trunc, system_text_meta,
            sequence, trace_meta, hostname, hook_tool_events or [],
        )
    else:
        _emit_legacy(
            langfuse, session_id, user_id, turn_num,
            user_text, assistant_text, assistant_text_meta,
            model, usage, stop_reason,
            system_text_trunc, system_text_meta,
            sequence, trace_meta, hostname, hook_tool_events or [],
        )


def _emit_sequence_items_modern(
    langfuse, sequence: List[Dict[str, Any]], base_time: datetime, step: timedelta,
) -> None:
    """Emit interleaved content blocks as nested spans (modern SDK)."""
    text_idx = 0
    thinking_idx = 0
    for i, item in enumerate(sequence):
        t = base_time + step * i
        time.sleep(0.002)  # ensure distinct creation timestamps for ordering
        if item["type"] == "thinking":
            thinking_idx += 1
            text_trunc, text_meta = truncate_text(item["text"])
            with langfuse.start_as_current_span(
                name=f"Thinking [{thinking_idx}]",
                metadata={"type": "thinking", "text_meta": text_meta},
            ) as span:
                span.update(start_time=t, output=text_trunc)

        elif item["type"] == "text":
            text_idx += 1
            text_trunc, text_meta = truncate_text(item["text"])
            with langfuse.start_as_current_span(
                name=f"Text [{text_idx}]",
                metadata={"type": "text", "text_meta": text_meta},
            ) as span:
                span.update(start_time=t, output=text_trunc)

        elif item["type"] == "tool_use":
            in_obj = item["input"]
            in_meta = None
            if isinstance(in_obj, str):
                in_obj, in_meta = truncate_text(in_obj)

            with langfuse.start_as_current_observation(
                name=f"Tool: {item['name']}",
                as_type="tool",
                input=in_obj,
                metadata={
                    "tool_name": item["name"],
                    "tool_id": item["id"],
                    "input_meta": in_meta,
                    "output_meta": item.get("output_meta"),
                },
            ) as tool_obs:
                tool_obs.update(start_time=t, output=item.get("output"))


def _emit_hook_tool_events_modern(
    langfuse,
    hook_tool_events: List[Dict[str, Any]],
    base_time: datetime,
    step: timedelta,
) -> None:
    for i, ev in enumerate(hook_tool_events):
        t = base_time + step * i
        name = str(ev.get("tool_name") or "unknown")
        event = str(ev.get("event") or "tool")
        in_raw = ev.get("tool_input")
        out_raw = ev.get("tool_output")

        in_text = in_raw if isinstance(in_raw, str) else json.dumps(in_raw, ensure_ascii=False, default=str) if in_raw is not None else ""
        out_text = out_raw if isinstance(out_raw, str) else json.dumps(out_raw, ensure_ascii=False, default=str) if out_raw is not None else ""
        in_text, in_meta = truncate_text(in_text)
        out_text, out_meta = truncate_text(out_text)

        with langfuse.start_as_current_observation(
            name=f"Hook Tool [{i + 1}]: {name}",
            as_type="tool",
            input=in_text,
            metadata={
                "source": "claude-code-hook",
                "event": event,
                "tool_name": name,
                "timestamp": ev.get("timestamp"),
                "input_meta": in_meta,
                "output_meta": out_meta,
            },
        ) as tool_obs:
            tool_obs.update(start_time=t, output=out_text if out_text else None)


def _emit_modern(
    langfuse, session_id, user_id, turn_num,
    user_text, assistant_text, assistant_text_meta,
    model, usage, stop_reason,
    system_text, system_text_meta,
    sequence, trace_meta, hostname="", hook_tool_events=None,
):
    """langfuse >= 3.12: propagate_attributes + nested spans."""
    with propagate_attributes(
        session_id=session_id,
        user_id=user_id,
        trace_name=f"Claude Code - Turn {turn_num}",
        tags=["claude-code", hostname],
    ):
        step = timedelta(milliseconds=1)
        t0 = datetime.now(timezone.utc)

        with langfuse.start_as_current_span(
            name=f"Claude Code - Turn {turn_num}",
            input={"role": "user", "content": user_text},
            metadata=trace_meta,
        ) as trace_span:
            trace_span.update(start_time=t0)

            # System prompt span
            t_cursor = t0 + step
            if system_text:
                time.sleep(0.002)
                with langfuse.start_as_current_span(
                    name="System Prompt",
                    input={"role": "system"},
                    metadata={"system_text": system_text_meta},
                ) as sys_span:
                    sys_span.update(start_time=t_cursor, output={"role": "system", "content": system_text})
                t_cursor += step

            # Generation observation with usage
            gen_meta: Dict[str, Any] = {
                "assistant_text": assistant_text_meta,
                "stop_reason": stop_reason,
                "content_blocks": len(sequence),
            }
            time.sleep(0.002)
            with langfuse.start_as_current_observation(
                name="Claude Response",
                as_type="generation",
                model=model,
                input={"role": "user", "content": user_text},
                output={"role": "assistant", "content": assistant_text},
                metadata=gen_meta,
            ) as gen_obs:
                gen_obs.update(start_time=t_cursor)
                if usage:
                    gen_obs.update(usage=usage)
            t_cursor += step

            # Interleaved content sequence (text, thinking, tool spans in order)
            _emit_sequence_items_modern(langfuse, sequence, t_cursor, step)
            t_cursor = t_cursor + step * len(sequence)

            # Hook-level tool events (PreToolUse/PostToolUse) for deep reconstruction
            if hook_tool_events:
                _emit_hook_tool_events_modern(langfuse, hook_tool_events, t_cursor, step)

            trace_span.update(output={"role": "assistant", "content": assistant_text})


def _emit_legacy(
    langfuse, session_id, user_id, turn_num,
    user_text, assistant_text, assistant_text_meta,
    model, usage, stop_reason,
    system_text, system_text_meta,
    sequence, trace_meta, hostname="", hook_tool_events=None,
):
    """langfuse >= 3.x without propagate_attributes (e.g. 3.7+, Python < 3.10)."""
    step = timedelta(milliseconds=1)
    t0 = datetime.now(timezone.utc)

    with langfuse.start_as_current_span(
        name=f"Claude Code - Turn {turn_num}",
        input={"role": "user", "content": user_text},
        metadata=trace_meta,
    ) as trace_span:
        trace_span.update(start_time=t0)

        # Set trace-level attributes (session, user, tags)
        langfuse.update_current_trace(
            name=f"Claude Code - Turn {turn_num}",
            session_id=session_id,
            user_id=user_id,
            tags=["claude-code", hostname],
            input={"role": "user", "content": user_text},
            output={"role": "assistant", "content": assistant_text},
            metadata=trace_meta,
        )

        # System prompt span
        t_cursor = t0 + step
        if system_text:
            time.sleep(0.002)
            with langfuse.start_as_current_span(
                name="System Prompt",
                input={"role": "system"},
                metadata={"system_text": system_text_meta},
            ) as sys_span:
                sys_span.update(start_time=t_cursor, output={"role": "system", "content": system_text})
            t_cursor += step

        # Generation observation with usage
        gen_meta: Dict[str, Any] = {
            "assistant_text": assistant_text_meta,
            "stop_reason": stop_reason,
            "content_blocks": len(sequence),
        }
        time.sleep(0.002)
        with langfuse.start_as_current_observation(
            name="Claude Response",
            as_type="generation",
            model=model,
            input={"role": "user", "content": user_text},
            output={"role": "assistant", "content": assistant_text},
            metadata=gen_meta,
        ) as gen_obs:
            gen_obs.update(start_time=t_cursor)
            if usage:
                gen_obs.update(usage_details=usage)
        t_cursor += step

        # Interleaved content sequence
        _emit_sequence_items_legacy(langfuse, sequence, t_cursor, step)
        t_cursor = t_cursor + step * len(sequence)

        if hook_tool_events:
            _emit_hook_tool_events_legacy(langfuse, hook_tool_events, t_cursor, step)

        trace_span.update(output={"role": "assistant", "content": assistant_text})


def _emit_sequence_items_legacy(
    langfuse, sequence: List[Dict[str, Any]], base_time: datetime, step: timedelta,
) -> None:
    """Emit interleaved content blocks as nested spans (3.7+ SDK without propagate)."""
    text_idx = 0
    thinking_idx = 0
    for i, item in enumerate(sequence):
        t = base_time + step * i
        time.sleep(0.002)
        if item["type"] == "thinking":
            thinking_idx += 1
            text_trunc, text_meta = truncate_text(item["text"])
            with langfuse.start_as_current_span(
                name=f"Thinking [{thinking_idx}]",
                metadata={"type": "thinking", "text_meta": text_meta},
            ) as span:
                span.update(start_time=t, output=text_trunc)

        elif item["type"] == "text":
            text_idx += 1
            text_trunc, text_meta = truncate_text(item["text"])
            with langfuse.start_as_current_span(
                name=f"Text [{text_idx}]",
                metadata={"type": "text", "text_meta": text_meta},
            ) as span:
                span.update(start_time=t, output=text_trunc)

        elif item["type"] == "tool_use":
            in_obj = item["input"]
            in_meta = None
            if isinstance(in_obj, str):
                in_obj, in_meta = truncate_text(in_obj)

            with langfuse.start_as_current_observation(
                name=f"Tool: {item['name']}",
                as_type="tool",
                input=in_obj,
                metadata={
                    "tool_name": item["name"],
                    "tool_id": item["id"],
                    "input_meta": in_meta,
                    "output_meta": item.get("output_meta"),
                },
            ) as tool_obs:
                tool_obs.update(start_time=t, output=item.get("output"))


def _emit_hook_tool_events_legacy(
    langfuse,
    hook_tool_events: List[Dict[str, Any]],
    base_time: datetime,
    step: timedelta,
) -> None:
    for i, ev in enumerate(hook_tool_events):
        t = base_time + step * i
        name = str(ev.get("tool_name") or "unknown")
        event = str(ev.get("event") or "tool")
        in_raw = ev.get("tool_input")
        out_raw = ev.get("tool_output")

        in_text = in_raw if isinstance(in_raw, str) else json.dumps(in_raw, ensure_ascii=False, default=str) if in_raw is not None else ""
        out_text = out_raw if isinstance(out_raw, str) else json.dumps(out_raw, ensure_ascii=False, default=str) if out_raw is not None else ""
        in_text, in_meta = truncate_text(in_text)
        out_text, out_meta = truncate_text(out_text)

        with langfuse.start_as_current_observation(
            name=f"Hook Tool [{i + 1}]: {name}",
            as_type="tool",
            input=in_text,
            metadata={
                "source": "claude-code-hook",
                "event": event,
                "tool_name": name,
                "timestamp": ev.get("timestamp"),
                "input_meta": in_meta,
                "output_meta": out_meta,
            },
        ) as tool_obs:
            tool_obs.update(start_time=t, output=out_text if out_text else None)

# ----------------- Tool event buffer (PreToolUse / PostToolUse) -----------------
def append_tool_event(session_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Buffer a PreToolUse or PostToolUse event."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "event": event_type,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        with open(BUFFER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        debug(f"append_tool_event failed: {e}")

def read_tool_events(session_id: str) -> List[Dict[str, Any]]:
    """Read buffered tool events for a session (non-destructive)."""
    events: List[Dict[str, Any]] = []
    try:
        if not BUFFER_FILE.exists():
            return events
        with open(BUFFER_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("session_id") == session_id:
                        events.append(ev)
                except Exception:
                    continue
    except Exception as e:
        debug(f"read_tool_events failed: {e}")
    return events

def cleanup_tool_buffer(session_id: str) -> None:
    """Remove consumed events for a session from the buffer."""
    try:
        if not BUFFER_FILE.exists():
            return
        remaining: List[str] = []
        with open(BUFFER_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    ev = json.loads(line_s)
                    if ev.get("session_id") != session_id:
                        remaining.append(line_s)
                except Exception:
                    remaining.append(line_s)
        with open(BUFFER_FILE, "w", encoding="utf-8") as f:
            for r in remaining:
                f.write(r + "\n")
    except Exception as e:
        debug(f"cleanup_tool_buffer failed: {e}")


def estimate_turn_tool_call_count(turn: Turn) -> int:
    count = 0
    for msg in turn.assistant_msgs:
        content = get_content(msg)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                count += 1
    return count


def partition_tool_events_by_turn(turns: List[Turn], tool_events: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Best-effort allocation of buffered hook tool events to emitted turns.

    PreToolUse/PostToolUse events are sequential in practice. We estimate event count
    per turn from transcript tool_use blocks (roughly 2 events per tool call).
    Any remainder is attached to the last turn so no event is dropped.
    """
    buckets: List[List[Dict[str, Any]]] = [[] for _ in turns]
    if not turns or not tool_events:
        return buckets

    idx = 0
    for i, turn in enumerate(turns):
        n_tools = estimate_turn_tool_call_count(turn)
        if n_tools <= 0:
            continue
        expected = n_tools * 2
        chunk = tool_events[idx: idx + expected]
        if not chunk:
            break
        buckets[i].extend(chunk)
        idx += len(chunk)
        if idx >= len(tool_events):
            break

    if idx < len(tool_events):
        buckets[-1].extend(tool_events[idx:])
    return buckets


def emit_notification_event(
    langfuse: Langfuse,
    session_id: str,
    payload: Dict[str, Any],
    hostname: str = "",
) -> None:
    user_id = os.environ.get("CC_LANGFUSE_USER_ID") or os.environ.get("LANGFUSE_USER_ID") or "claude-user"
    name = "Claude Code - Notification"
    meta = {
        "source": "claude-code",
        "product": "claude-code",
        "event": "Notification",
        "session_id": session_id,
        "hostname": hostname,
        "notification_type": payload.get("notification_type"),
    }
    output = {
        "message": payload.get("message"),
        "details": payload.get("details"),
    }

    if _HAS_PROPAGATE:
        with propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            trace_name=name,
            tags=["claude-code", "notification", hostname],
        ):
            with langfuse.start_as_current_span(
                name=name,
                input={"event": "Notification"},
                metadata=meta,
            ) as span:
                span.update(output=output)
        return

    with langfuse.start_as_current_span(
        name=name,
        input={"event": "Notification"},
        metadata=meta,
    ) as span:
        langfuse.update_current_trace(
            name=name,
            session_id=session_id,
            user_id=user_id,
            tags=["claude-code", "notification", hostname],
        )
        span.update(output=output)

# ----------------- Event type detection -----------------
def detect_hook_event(payload: Dict[str, Any]) -> str:
    """Detect hook event type from payload structure.

    Claude Code payloads differ by event:
      - PreToolUse: has tool_name, tool_input, no tool_output
      - PostToolUse: has tool_name, tool_input, tool_output
      - Stop/Notification: has transcriptPath but no tool_name
    """
    declared = payload.get("hook_event_name") or payload.get("event")
    if isinstance(declared, str):
        d = declared.strip()
        if d in ("Stop", "Notification", "PreToolUse", "PostToolUse"):
            return d

    if "tool_name" in payload:
        if "tool_output" in payload:
            return "PostToolUse"
        return "PreToolUse"
    if "notification_type" in payload or "details" in payload:
        return "Notification"
    return "Stop"

# ----------------- Tool event emit -----------------
def emit_tool_event(
    langfuse: Langfuse,
    session_id: str,
    event_type: str,
    payload: Dict[str, Any],
    hostname: str = "",
) -> None:
    """Emit a PreToolUse or PostToolUse event as a Langfuse span."""
    user_id = os.environ.get("CC_LANGFUSE_USER_ID") or os.environ.get("LANGFUSE_USER_ID") or "claude-user"
    tool_name = payload.get("tool_name", "unknown")

    tool_input = payload.get("tool_input")
    in_str = tool_input if isinstance(tool_input, (dict, list)) else str(tool_input or "")
    in_meta = None
    if isinstance(in_str, str):
        in_str, in_meta = truncate_text(in_str)

    meta: Dict[str, Any] = {
        "source": "claude-code",
        "session_id": session_id,
        "event": event_type,
        "tool_name": tool_name,
        "hostname": hostname,
        "input_meta": in_meta,
    }

    if event_type == "PostToolUse":
        tool_output = payload.get("tool_output")
        out_str = tool_output if isinstance(tool_output, str) else json.dumps(tool_output, ensure_ascii=False, default=str) if tool_output is not None else ""
        out_str, out_meta = truncate_text(out_str)
        meta["output_meta"] = out_meta
    else:
        out_str = None

    span_name = f"{'Before' if event_type == 'PreToolUse' else 'After'} Tool: {tool_name}"

    if _HAS_PROPAGATE:
        with propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            trace_name=span_name,
            tags=["claude-code", event_type.lower(), hostname],
        ):
            with langfuse.start_as_current_span(
                name=span_name,
                input=in_str,
                metadata=meta,
            ) as span:
                if out_str is not None:
                    span.update(output=out_str)
    else:
        with langfuse.start_as_current_span(
            name=span_name,
            input=in_str,
            metadata=meta,
        ) as span:
            langfuse.update_current_trace(
                name=span_name,
                session_id=session_id,
                user_id=user_id,
                tags=["claude-code", event_type.lower(), hostname],
            )
            if out_str is not None:
                span.update(output=out_str)

# ----------------- Main -----------------
def main() -> int:
    start = time.time()
    debug("Hook started")

    if os.environ.get("TRACE_TO_LANGFUSE", "").lower() != "true":
        return 0

    public_key = os.environ.get("CC_LANGFUSE_PUBLIC_KEY") or os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("CC_LANGFUSE_SECRET_KEY") or os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("CC_LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    hostname = os.environ.get("CC_LANGFUSE_HOSTNAME") or socket.gethostname()

    if not public_key or not secret_key:
        return 0

    payload = read_hook_payload()
    event_type = detect_hook_event(payload)
    debug(f"Event type: {event_type}")

    ctx = extract_session_context(payload)

    if not ctx.session_id:
        debug("Missing session_id from hook payload; exiting.")
        return 0

    session_id = ctx.session_id

    # --- PreToolUse / PostToolUse: buffer only (included in turn trace via transcript) ---
    if event_type in ("PreToolUse", "PostToolUse"):
        append_tool_event(session_id, event_type, {
            "tool_name": payload.get("tool_name"),
            "tool_input": payload.get("tool_input"),
            "tool_output": payload.get("tool_output"),
        })
        debug(f"Buffered {event_type} for {payload.get('tool_name')}")
        return 0

    # --- Stop / Notification: transcript-based turn processing ---
    if not ctx.transcript_path:
        debug("Missing transcript_path from hook payload; exiting.")
        return 0

    transcript_path = ctx.transcript_path

    if not transcript_path.exists():
        debug(f"Transcript path does not exist: {transcript_path}")
        return 0

    try:
        langfuse = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception:
        return 0

    try:
        with FileLock(LOCK_FILE):
            state = load_state()
            key = state_key(session_id, str(transcript_path))
            ss = load_session_state(state, key)

            msgs, ss = read_new_jsonl(transcript_path, ss)
            if not msgs:
                write_session_state(state, key, ss)
                save_state(state)
                return 0

            turns = build_turns(msgs)
            if not turns:
                write_session_state(state, key, ss)
                save_state(state)
                return 0

            # Best-effort map of PreToolUse/PostToolUse events into each emitted turn.
            buffered_tool_events = read_tool_events(session_id)
            tool_event_buckets = partition_tool_events_by_turn(turns, buffered_tool_events)

            emitted = 0
            for i, t in enumerate(turns):
                emitted += 1
                turn_num = ss.turn_count + emitted
                try:
                    emit_turn(
                        langfuse,
                        session_id,
                        turn_num,
                        t,
                        transcript_path,
                        ctx,
                        hostname=hostname,
                        hook_event_type=event_type,
                        hook_tool_events=tool_event_buckets[i] if i < len(tool_event_buckets) else [],
                    )
                except Exception as e:
                    debug(f"emit_turn failed: {e}")

            ss.turn_count += emitted
            write_session_state(state, key, ss)
            save_state(state)

        if event_type == "Notification":
            try:
                emit_notification_event(langfuse, session_id, payload, hostname=hostname)
            except Exception as e:
                debug(f"emit_notification_event failed: {e}")

        # Cleanup consumed tool events for this session
        cleanup_tool_buffer(session_id)

        try:
            langfuse.flush()
        except Exception:
            pass

        dur = time.time() - start
        info(f"Processed {emitted} turns in {dur:.2f}s (session={session_id})")
        return 0

    except Exception as e:
        debug(f"Unexpected failure: {e}")
        return 0

    finally:
        try:
            langfuse.shutdown()
        except Exception:
            pass

if __name__ == "__main__":
    sys.exit(main())
