#!/usr/bin/env python3
"""AttentionOS MCP server — attention://state for your agents.

Zero-dependency MCP (Model Context Protocol) server over stdio.
Reads the same local SQLite the pet/CLI collector writes
(~/.attentionos/attn.db). Nothing leaves the machine: this server
only answers agents that YOU run on this machine.

Register with Claude Code:

    claude mcp add attention -- python3 /path/to/AttentionOS/mcp/attention_mcp.py

Then your agent can ask "check my attention state before interrupting"
— and mean it literally.

Tools:
  get_attention_state    live state: focused / calm / frazzled / away + advice
  get_attention_report   full daily metrics (METRICS.md)
  get_attention_profile  archetype + network scores from the 60s check-up

Resources:
  attention://state      same as get_attention_state
  attention://profile    same as get_attention_profile
"""
import json
import os
import sys
import time
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cli"))
import attn  # reuse the metric engine (focus_blocks, analyze, load_events)

PROTOCOL_VERSION = "2024-11-05"
SELF_NAMES = {"attentionos"}


# ---------------------------------------------------------------- data
def _recent_events(seconds):
    conn = attn.db()
    now = time.time()
    rows = conn.execute(
        "SELECT source, start, end FROM focus_events"
        " WHERE end >= ? AND lower(source) NOT IN ('attentionos') ORDER BY start",
        (now - seconds,),
    ).fetchall()
    return now, rows


def attention_state():
    now, rows = _recent_events(1800)
    switches = sum(1 for i in range(1, len(rows)) if rows[i][0] != rows[i - 1][0])
    tracked = sum(min(e, now) - max(s, now - 1800) for _, s, e in rows) / 60
    rate = switches * 60 / tracked if tracked > 1 else 0.0

    last_seen = max((e for _, _, e in rows), default=0)
    away = now - last_seen > 300

    events = [ev for ev in attn.load_events(datetime.date.today())
              if ev[0].lower() not in SELF_NAMES]
    blocks = attn.focus_blocks(events) if events else []
    current = next((b for b in blocks if now - b[2] < 120), None)
    in_deep = current is not None and (current[2] - current[1]) >= 600

    if away:
        state = "away"
    elif rate > 25:
        state = "frazzled"
    elif in_deep and rate < 8:
        state = "focused"
    else:
        state = "calm"

    advice = {
        "focused": "User is in a deep-focus block. Hold non-urgent questions and "
                   "batch them for when the block ends; do not interrupt.",
        "frazzled": "User's attention is already fragmented (high switch rate). "
                    "Consolidate your asks into one message instead of many.",
        "calm": "OK to interact normally.",
        "away": "User is away from the machine. Queue results; expect no response.",
    }[state]

    waiting = []
    try:
        waiting = [
            {"session": s[-8:] if s else "?", "waiting_min": round(w / 60, 1)}
            for s, w in attn.agents_waiting_now(attn.db())
        ]
    except Exception:
        pass

    return {
        "state": state,
        "advice": advice,
        "switches_per_hr": round(rate, 1),
        "tracked_min_last_30m": round(tracked),
        "in_deep_block": in_deep,
        "current_block_min": round((current[2] - current[1]) / 60) if current else 0,
        "current_app": rows[-1][0] if rows and not away else None,
        "agents_waiting_on_user": waiting,
        "as_of": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def attention_report(offset_days=0):
    date = datetime.date.today() - datetime.timedelta(days=int(offset_days))
    events = [ev for ev in attn.load_events(date) if ev[0].lower() not in SELF_NAMES]
    a = attn.analyze(events)
    if not a:
        return {"date": date.isoformat(), "no_data": True}
    return {
        "date": date.isoformat(),
        "focus_half_life_min": round(a["fhl"], 1),
        "longest_block_min": round(a["longest_block"]),
        "context_switches_per_hr": round(a["csr"], 1),
        "recovery_cost_min": round(a["recovery_min"]),
        "interrupt_load_pct": round(a["il"] * 100),
        "deep_focus_min": round(a["deep_focus_min"]),
        "active_hours": round(a["active_h"], 1),
        "top_sources_min": {k: round(v) for k, v in
                            sorted(a["per_source"].items(), key=lambda kv: -kv[1])[:5]},
        "top_interrupters": a["interrupt_counts"],
    }


def attention_profile():
    path = os.path.expanduser("~/.attentionos/profile.json")
    if not os.path.exists(path):
        return {"no_profile": True,
                "hint": "Take the 60s check-up and import the save code in the desktop pet."}
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- MCP plumbing
TOOLS = [
    {
        "name": "get_attention_state",
        "description": (
            "Live attention state of the human user (from the local AttentionOS "
            "collector). Call this BEFORE interrupting the user with questions or "
            "notifications: 'focused' means hold and batch non-urgent asks, "
            "'frazzled' means consolidate into one message, 'away' means queue "
            "results, 'calm' means normal interaction is fine."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_attention_report",
        "description": (
            "Daily attention metrics for the user: focus half-life, context switch "
            "rate, recovery cost, interrupt load, deep-focus minutes, top apps and "
            "top interrupters. offset_days=0 is today, 1 is yesterday."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"offset_days": {"type": "integer", "minimum": 0, "default": 0}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_attention_profile",
        "description": (
            "The user's attention profile from the 60-second check-up: archetype "
            "(cheetah/hawkeye/fortress/commander/balanced/wanderer) and the three "
            "network scores (alerting/orienting/executive)."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

RESOURCES = [
    {"uri": "attention://state", "name": "Live attention state",
     "description": "focused / calm / frazzled / away, with interruption advice",
     "mimeType": "application/json"},
    {"uri": "attention://profile", "name": "Attention profile",
     "description": "archetype + network scores from the 60s check-up",
     "mimeType": "application/json"},
]


def handle(req):
    method = req.get("method")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "attentionos", "version": "0.1.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "resources/list":
        return {"resources": RESOURCES}
    if method == "resources/read":
        uri = params.get("uri", "")
        data = {"attention://state": attention_state,
                "attention://profile": attention_profile}.get(uri)
        if data is None:
            raise ValueError(f"unknown resource: {uri}")
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                              "text": json.dumps(data(), ensure_ascii=False, indent=2)}]}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "get_attention_state":
            result = attention_state()
        elif name == "get_attention_report":
            result = attention_report(args.get("offset_days", 0))
        elif name == "get_attention_profile":
            result = attention_profile()
        else:
            raise ValueError(f"unknown tool: {name}")
        return {"content": [{"type": "text",
                             "text": json.dumps(result, ensure_ascii=False, indent=2)}]}
    raise ValueError(f"unknown method: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in req:          # notification — no response
            continue
        resp = {"jsonrpc": "2.0", "id": req["id"]}
        try:
            resp["result"] = handle(req)
        except Exception as e:  # noqa: BLE001 — every error becomes a JSON-RPC error
            resp["error"] = {"code": -32603, "message": str(e)}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
