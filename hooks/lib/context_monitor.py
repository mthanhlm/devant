#!/usr/bin/env python3
"""devant context monitor (dec-018) — declared in monitors/monitors.json.

Runs for the session lifetime: every ~30s it reads the newest Claude Code transcript's
last usage block, computes context %, and writes it to .devant/state/context.pct for the
PreCompact gate. Every stdout line becomes a model notification, so it prints ONLY on
zone transitions: the floor crossed while the phase gate holds (a boundary compact is
now pending) and the 85% safety line. Stdlib only; exits/idles quietly on any gap.
"""
import json
import os
import sys
import time

POLL_SECONDS = 30
SAFETY_PCT = 85


def transcript_dir(proj):
    """Claude Code stores transcripts under ~/.claude/projects/<munged-project-path>/."""
    name = proj.replace("/", "-").replace(".", "-")
    return os.path.expanduser(os.path.join("~", ".claude", "projects", name))


def session_transcript(state):
    """The transcript path SessionStart persisted for THIS session — beats guessing by
    newest-mtime, which tracks the wrong session when two run in one repo."""
    try:
        with open(os.path.join(state, "transcript.path")) as fh:
            p = fh.read().strip()
        return p if p and os.path.exists(p) else None
    except OSError:
        return None


def fallback_window(model):
    """Window guess when no env is set: 1M-family models vs the 200K default."""
    m = (model or "").lower()
    return 500000 if any(k in m for k in ("fable", "opus-4", "sonnet-5", "[1m]")) else 200000


def latest_transcript(tdir):
    try:
        files = [os.path.join(tdir, f) for f in os.listdir(tdir) if f.endswith(".jsonl")]
    except OSError:
        return None
    return max(files, key=os.path.getmtime) if files else None


def last_usage_tokens(path, tail_bytes=262144):
    """Context tokens of the most recent assistant message: input + cache read/create.
    Reads only the file tail — transcripts grow to many MB and this runs every poll."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            lines = fh.read().split(b"\n")
    except OSError:
        return None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if isinstance(usage, dict):
            return (int(usage.get("input_tokens") or 0)
                    + int(usage.get("cache_read_input_tokens") or 0)
                    + int(usage.get("cache_creation_input_tokens") or 0))
    return None


def pct(used, window):
    if not window or window <= 0:
        return 0
    return min(100, int(round(100.0 * used / window)))


def phase_gate(proj):
    try:
        with open(os.path.join(proj, ".devant", "state", "phase")) as fh:
            return json.load(fh).get("gate", "open")
    except (OSError, ValueError):
        return "open"


def zone(p, floor, gate):
    if p >= SAFETY_PCT:
        return "high"
    if p >= floor and gate == "hold":
        return "pending"
    return "low"


def _env_int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def main():
    if (os.environ.get("CLAUDE_PLUGIN_OPTION_SMART_COMPACT", "true").lower()
            in ("false", "0", "off")):
        return 0
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    state = os.path.join(proj, ".devant", "state")
    try:
        with open(os.path.join(state, "model")) as fh:
            model = fh.read().strip()
    except OSError:
        model = ""
    # No env at all -> model-aware guess (1M family vs 200K); overestimating pct only
    # relaxes the gate, so the small default stays the safe unknown-model choice.
    window = _env_int("CLAUDE_CODE_AUTO_COMPACT_WINDOW",
                      _env_int("CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS",
                               fallback_window(model)))
    floor = _env_int("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
                     _env_int("CLAUDE_PLUGIN_OPTION_COMPACT_FLOOR_PCT", 50))
    tdir = transcript_dir(proj)
    last_zone = None
    while True:
        t = session_transcript(state) or latest_transcript(tdir)
        used = last_usage_tokens(t) if t else None
        if used:
            p = pct(used, window)
            try:
                os.makedirs(state, exist_ok=True)
                with open(os.path.join(state, "context.pct"), "w") as fh:
                    fh.write(str(p))
            except OSError:
                pass
            z = zone(p, floor, phase_gate(proj))
            if z != last_zone:
                if z == "pending":
                    print("[devant] context ~%d%% — auto-compact pending, will land at the "
                          "next phase boundary" % p, flush=True)
                elif z == "high":
                    print("[devant] context ~%d%% — compaction imminent" % p, flush=True)
                last_zone = z
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
