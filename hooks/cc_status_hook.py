#!/usr/bin/env python3
"""Clawdometer CC status hook.

Registered on Claude Code's UserPromptSubmit / PreToolUse / Notification / Stop
hooks. On each event it writes ~/.clawd/cc_status.json:

    {"state": "working" | "needs-you" | "question" | "done",
     "message": "<short>", "ts": <epoch>}

The Clawdometer Mac daemon reads that file every ~5s and rides the state through
to the e-paper device over BLE (fields cc/ccm/cct), which draws a status banner.

"question" = Claude ended its turn by asking the user something: either the
AskUserQuestion tool fired, or the final reply text ends with a question mark
(read from the session transcript the Stop hook points at).

Stdlib only; always exits 0 so it can never block a tool call or a turn.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

CC_DIR = Path.home() / ".clawd"
CC_FILE = CC_DIR / "cc_status.json"
SESS_DIR = CC_DIR / "sessions"
SESSION_STALE_SECS = 30 * 60  # matches the daemon's CC_STALE_SECS

# The device draws the question in a small ~10px font across 180px — about 34
# chars. Isolate the final question sentence and trim it to fit.
BANNER_MSG_MAX = 34


def shorten_question(q):
    import re
    q = " ".join(q.split())
    sentences = re.findall(r"[^.!?]*\?", q)
    if sentences:
        q = sentences[-1].strip()
    if len(q) > BANNER_MSG_MAX:
        cut = q[: BANNER_MSG_MAX - 4].rsplit(" ", 1)[0].rstrip(",;:- ")
        q = cut + "...?"
    return q


def ends_question(t):
    """True when text ends in a question mark: ASCII, real Greek erotimatiko
    (U+037E), fullwidth (U+FF1F) -- or an ASCII ';' when the surrounding text
    is actually Greek (Greek keyboards type ';' for the question mark)."""
    if t.endswith("?") or t.endswith("\u037e") or t.endswith("\uff1f"):
        return True
    if t.endswith(";") and any("\u0370" <= c <= "\u03ff" for c in t[-80:]):
        return True
    return False


def last_reply_question(transcript_path):
    """If the session's final assistant text ends with a question, return that
    question line (for the banner's context message); else None. Reads only the
    tail of the transcript so big sessions stay cheap."""
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - 262_144))
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    for line in reversed(chunk.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        texts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        if not texts:
            continue  # tool-use-only entry; keep scanning back for real text
        raw = texts[-1].rstrip()
        cands = [raw]
        # a trailing aside must not hide the question: "flash? (plug cable)"
        if raw.endswith(")") and "(" in raw:
            cands.append(raw[: raw.rfind("(")].rstrip())
        for cand in cands:
            cand = cand.rstrip("*_`\"') ")  # markdown / quote trailers
            if ends_question(cand):
                last_line = cand.rsplit("\n", 1)[-1].strip().lstrip("#>-*_` ")
                return shorten_question(last_line)
        return None  # last reply exists and is not a question
    return None


def main() -> int:
    try:
        # Read bytes: on Windows, text-mode stdin decodes as cp1252, not UTF-8.
        # utf-8-sig also drops the BOM PowerShell prepends when piping.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", "replace"))
    except Exception:
        data = {}

    event = data.get("hook_event_name", "")
    tool = str(data.get("tool_name", "") or "")

    if os.environ.get("CLAWD_HOOK_DEBUG") or (CC_DIR / "hook_debug").exists():
        try:  # one line per event, to see what the host actually sends
            with open(CC_DIR / "hook_events.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "ev": event,
                                    "tool": tool, "ntype": data.get("notification_type"),
                                    "msg": str(data.get("message", ""))[:60],
                                    "sid": str(data.get("session_id", ""))[:8]}) + "\n")
        except OSError:
            pass
    if event == "PreToolUse" and tool == "AskUserQuestion":
        # Claude is explicitly asking the user to choose something — show the
        # first question's text (shortened) under the banner.
        q = ""
        try:
            qs = (data.get("tool_input") or {}).get("questions") or []
            if qs and isinstance(qs[0], dict):
                q = shorten_question(str(qs[0].get("question", "") or ""))
        except Exception:
            q = ""
        state, message = "question", q
    elif event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
        # PostToolUse: clears a needs-you as soon as an approved tool finishes.
        # "working" — message hints at what (the tool about to run, if any).
        state, message = "working", tool
    elif event == "Notification" and data.get("notification_type") == "idle_prompt":
        # "waiting for your input" after a finished turn: the session is already
        # done/question. As needs-you it would outrank everything for 30 min.
        return 0
    elif event == "Notification":
        # The key one: permission asks / idle-waiting. message has the reason.
        state, message = "needs-you", str(data.get("message", "") or "")
    elif event == "Stop":
        # Finished — but if the reply ends with a question, the ball is in the
        # user's court: surface it as "question" instead of "done".
        q = None
        try:
            tp = str(data.get("transcript_path", "") or "")
            if tp:
                q = last_reply_question(tp)
        except Exception:
            q = None  # heuristics must never break the hook
        state, message = ("question", q) if q else ("done", "")
    elif event == "SessionEnd":
        state, message = None, ""  # drop this session's entry
    else:
        return 0  # unknown event — leave the file untouched

    payload = None
    if state:
        payload = {"state": state, "message": message[:80], "ts": int(time.time())}
    try:
        write_status(payload, str(data.get("session_id", "") or "default"))
    except OSError:
        pass  # best-effort; never fail the hook

    return 0


def _atomic_write(path, obj):
    # Atomic so the daemon never reads a half-written file.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, str(path))


def write_status(payload, session_id):
    """Record this session's status (None = session ended), then rebuild
    CC_FILE from every live session. Each session owns its own file, so
    concurrent hooks can't drop each other's state; the daemon picks which
    session to show. Top-level fields stay the latest event for older daemons."""
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    sid = "".join(c for c in session_id if c.isalnum() or c == "-")[:64] or "default"
    own = SESS_DIR / (sid + ".json")
    if payload:
        _atomic_write(own, payload)
    else:
        try:
            own.unlink()
        except OSError:
            pass
    now = time.time()
    sessions = {}
    for p in SESS_DIR.glob("*.json"):
        try:
            if now - p.stat().st_mtime > SESSION_STALE_SECS:
                p.unlink()  # crashed / abandoned session
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            sessions[p.stem[:8]] = d
    top = payload or max(sessions.values(), key=lambda d: d.get("ts", 0),
                         default={"state": "done", "message": "", "ts": int(now)})
    _atomic_write(CC_FILE, dict(top, sessions=sessions))


if __name__ == "__main__":
    sys.exit(main())
