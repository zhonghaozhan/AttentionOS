#!/usr/bin/env python3
"""attn — AttentionOS prototype profiler.

Local-first attention profiler. Focus events go into SQLite on your machine
and nowhere else. See docs/METRICS.md for the metric definitions.

Usage:
  attn.py demo               seed the database with a synthetic workday
  attn.py collect [secs]     start the macOS collector (polls frontmost app)
  attn.py report [YYYY-MM-DD]  render the attention report
  attn.py pet                one-line ASCII pet reflecting your last 30 min
  attn.py agent-event STATE  record an agent state change (working|waiting|notify)
                             — wire into Claude Code hooks, see docs/AGENTS.md
  attn.py statusline         one-line status for the Claude Code statusline
  attn.py wipe               delete all local data
"""
import datetime
import math
import os
import random
import sqlite3
import statistics
import subprocess
import sys
import time

DB_PATH = os.path.expanduser("~/.attentionos/attn.db")

GRACE_S = 30          # glance-away tolerance inside a focus block (METRICS.md §1)
MIN_BLOCK_S = 60      # blocks under a minute are noise
DEEP_BLOCK_S = 300    # a switch ending a >=5min block is a deep preemption
RECOVERY_MIN = 9.5    # resumption lag estimate, Mark et al. CHI 2008
INTERRUPTERS = {"Slack", "Messages", "Mail", "Discord", "WeChat", "Telegram"}

BOLD, DIM, RED, GREEN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS focus_events ("
        " source TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL)"
    )
    return conn


# ---------------------------------------------------------------- collect
def collect(interval=5):
    """Poll the frontmost macOS app and record focus transitions. Local only."""
    script = 'tell application "System Events" to get name of first process whose frontmost is true'
    conn = db()
    current, started = None, None
    print(f"{BOLD}attn collect{RESET} — polling every {interval}s, ctrl-c to stop. "
          f"Data stays in {DB_PATH}")
    try:
        while True:
            try:
                name = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=4,
                ).stdout.strip() or "unknown"
            except subprocess.TimeoutExpired:
                name = current or "unknown"
            now = time.time()
            if name != current:
                if current is not None:
                    conn.execute("INSERT INTO focus_events VALUES (?,?,?)",
                                 (current, started, now))
                    conn.commit()
                    print(f"{DIM}{datetime.datetime.now():%H:%M:%S}{RESET} "
                          f"{current} → {BOLD}{name}{RESET}")
                current, started = name, now
            time.sleep(interval)
    except KeyboardInterrupt:
        if current is not None:
            conn.execute("INSERT INTO focus_events VALUES (?,?,?)",
                         (current, started, time.time()))
            conn.commit()
        print("\nstopped. run `attn.py report` to see the damage.")


# ---------------------------------------------------------------- demo data
def seed_demo():
    """Synthesize a believable workday: morning deep work, slack-shredded
    midday, a recovered afternoon block, doomscroll tail."""
    rng = random.Random(7)
    conn = db()
    conn.execute("DELETE FROM focus_events")
    day = datetime.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    t = day.timestamp()
    events = []

    def add(source, minutes):
        nonlocal t
        end = t + minutes * 60
        events.append((source, t, end))
        t = end

    # 9:00 morning deep block, lightly grazed
    for _ in range(3):
        add("VS Code", rng.uniform(22, 38))
        add("Chrome", rng.uniform(0.3, 0.45))      # doc glance (within grace)
    add("Slack", 4)
    # 10:45 the shredder: slack/email ping-pong
    for _ in range(14):
        add(rng.choice(["Slack", "Mail", "Chrome"]), rng.uniform(1, 4))
        add("VS Code", rng.uniform(2, 6))
    add("Zoom", 47)
    # 13:30 lunch gap (idle)
    t += 40 * 60
    # 14:10 afternoon recovery block supervising agent sessions
    for _ in range(2):
        add("Claude Code", rng.uniform(25, 41))
        add("Chrome", rng.uniform(0.3, 0.5))
    for _ in range(9):
        add(rng.choice(["Slack", "Messages"]), rng.uniform(0.8, 3))
        add("Claude Code", rng.uniform(3, 9))
    # 17:00 doomscroll tail
    for _ in range(10):
        add(rng.choice(["Chrome", "Messages", "Mail"]), rng.uniform(0.7, 2.5))

    conn.executemany("INSERT INTO focus_events VALUES (?,?,?)", events)
    conn.commit()
    print(f"seeded {len(events)} focus events for {day:%Y-%m-%d} → {DB_PATH}")
    print("now run:  python3 attn.py report")


# ---------------------------------------------------------------- metrics
def load_events(date):
    conn = db()
    d0 = datetime.datetime.combine(date, datetime.time.min).timestamp()
    d1 = d0 + 86400
    rows = conn.execute(
        "SELECT source, start, end FROM focus_events"
        " WHERE start >= ? AND start < ? ORDER BY start", (d0, d1)).fetchall()
    return [(s, a, b) for s, a, b in rows if b - a > 1]


def focus_blocks(events):
    """Merge events into focus blocks per METRICS.md §1: dwells away from the
    anchor shorter than GRACE_S don't break the block."""
    blocks = []  # (anchor, start, end)
    i = 0
    while i < len(events):
        anchor, start, end = events[i]
        j = i + 1
        while j < len(events):
            src, s, e = events[j]
            if src == anchor and s - end <= GRACE_S:
                end = e
            elif src != anchor and (e - s) < GRACE_S and j + 1 < len(events) \
                    and events[j + 1][0] == anchor:
                pass  # tolerated glance; continuation handled next iteration
            else:
                break
            j += 1
        blocks.append((anchor, start, end))
        i = j
    return [(a, s, e) for a, s, e in blocks if e - s >= MIN_BLOCK_S]


def analyze(events):
    if not events:
        return None
    switches = [(events[k - 1], events[k]) for k in range(1, len(events))
                if events[k][0] != events[k - 1][0]]
    # active hours: total span minus idle gaps > 5 min
    span = events[-1][2] - events[0][1]
    idle = sum(max(0, events[k][1] - events[k - 1][2]) for k in range(1, len(events))
               if events[k][1] - events[k - 1][2] > 300)
    active_h = max((span - idle) / 3600, 0.1)

    blocks = focus_blocks(events)
    block_mins = sorted((e - s) / 60 for _, s, e in blocks)
    fhl = statistics.median(block_mins) if block_mins else 0.0

    deep_preempts = sum(1 for prev, _ in switches if prev[2] - prev[1] >= DEEP_BLOCK_S)
    external = sum(1 for _, gained in switches if gained[0] in INTERRUPTERS)
    il = external / len(switches) if switches else 0.0

    deep_focus_min = sum((e - s) / 60 for _, s, e in blocks if e - s >= 600)
    per_source = {}
    for src, s, e in events:
        per_source[src] = per_source.get(src, 0) + (e - s) / 60
    interrupt_counts = {}
    for _, gained in switches:
        if gained[0] in INTERRUPTERS:
            interrupt_counts[gained[0]] = interrupt_counts.get(gained[0], 0) + 1

    return dict(
        active_h=active_h,
        fhl=fhl,
        longest_block=block_mins[-1] if block_mins else 0,
        csr=len(switches) / active_h,
        recovery_min=deep_preempts * RECOVERY_MIN,
        il=il, n_switches=len(switches),
        deep_focus_min=deep_focus_min,
        per_source=per_source,
        interrupt_counts=interrupt_counts,
        events=events, blocks=blocks,
    )


# ---------------------------------------------------------------- report
def bar(mins, scale=2.2, width=28):
    n = min(width, max(1, round(mins / scale)))
    return "█" * n


def timeline(events, width=72):
    """One char per slice of the day; deep-block time inked solid."""
    t0, t1 = events[0][1], events[-1][2]
    slot = (t1 - t0) / width
    blocks = focus_blocks(events)
    out = []
    for w in range(width):
        a, b = t0 + w * slot, t0 + (w + 1) * slot
        covered = sum(max(0, min(e, b) - max(s, a)) for _, s, e in events)
        in_block = any(s < b and e > a for _, s, e in blocks if e - s >= 600)
        if covered < slot * 0.3:
            out.append(" ")
        elif in_block:
            out.append(f"{GREEN}█{RESET}")
        else:
            out.append(f"{RED}▒{RESET}")
    return "".join(out)


def report(date):
    events = load_events(date)
    a = analyze(events)
    if not a:
        print("no focus events for that day. run `attn.py demo` or `attn.py collect`.")
        return

    fhl_c = GREEN if a["fhl"] >= 15 else YELLOW if a["fhl"] >= 7 else RED
    il_pct = round(a["il"] * 100)
    self_pct = 100 - il_pct

    print(f"\n{BOLD}ATTENTION{RED}OS{RESET}{BOLD} · daily report · {date}{RESET}")
    print("─" * 72)
    print(f"  {'Focus Half-Life':<22}{fhl_c}{BOLD}{a['fhl']:>6.1f} min{RESET}"
          f"   {DIM}longest block {a['longest_block']:.0f} min{RESET}")
    print(f"  {'Context Switch Rate':<22}{BOLD}{a['csr']:>6.1f} /hr{RESET}"
          f"   {DIM}{a['n_switches']} switches over {a['active_h']:.1f} active hrs{RESET}")
    print(f"  {'Recovery Cost':<22}{RED}{BOLD}{a['recovery_min']:>6.0f} min{RESET}"
          f"   {DIM}est. re-immersion lost to deep preemptions{RESET}")
    print(f"  {'Interrupt Load':<22}{BOLD}{il_pct:>5d} %{RESET}"
          f"   {DIM}external · {self_pct}% self-inflicted{RESET}")
    print(f"  {'Attention Budget':<22}{BOLD}{a['deep_focus_min']:>6.0f} min{RESET}"
          f"   {DIM}deep focus banked today{RESET}")
    aw = agent_wait_today(db())
    if aw >= 1:
        print(f"  {'Agent-Wait Cost':<22}{YELLOW}{BOLD}{aw:>6.0f} min{RESET}"
              f"   {DIM}agents sat waiting for your input today{RESET}")

    print(f"\n  {BOLD}timeline{RESET}  {DIM}{GREEN}█{RESET}{DIM} deep focus"
          f"  {RED}▒{RESET}{DIM} shallow/shredded  ␣ idle{RESET}")
    print(f"  {timeline(events)}")

    print(f"\n  {BOLD}where it went{RESET}")
    for src, mins in sorted(a["per_source"].items(), key=lambda kv: -kv[1])[:6]:
        print(f"    {src:<14}{DIM}{mins:>6.0f} min{RESET}  {bar(mins)}")

    if a["interrupt_counts"]:
        print(f"\n  {BOLD}top interrupters{RESET}")
        for src, n in sorted(a["interrupt_counts"].items(), key=lambda kv: -kv[1]):
            print(f"    {src:<14}{RED}{n:>3d} preemptions{RESET}")
    print("─" * 72)
    verdict = ("defended" if a["fhl"] >= 15 else
               "leaking" if a["fhl"] >= 7 else "strip-mined")
    print(f"  verdict: attention {BOLD}{verdict}{RESET} · "
          f"data local at {DIM}{DB_PATH}{RESET}\n")


# ---------------------------------------------------------------- agents
def agent_events_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_events ("
        " session TEXT NOT NULL, state TEXT NOT NULL, ts REAL NOT NULL)"
    )


def agent_event(state):
    """Record a coding-agent state change. Fed by Claude Code hooks:
    UserPromptSubmit -> working, Stop -> waiting, Notification -> notify.
    This turns the human-only timeline into a JOINT attention timeline:
    switches while the agent works are supervision, not fragmentation;
    minutes the agent spends waiting for you are a cost worth seeing."""
    import json as _json
    payload = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                payload = _json.loads(raw)
    except Exception:
        payload = {}
    conn = db()
    agent_events_table(conn)
    conn.execute(
        "INSERT INTO agent_events VALUES (?, ?, ?)",
        (payload.get("session_id", ""), state, time.time()),
    )
    conn.commit()


def agent_wait_today(conn):
    """Total minutes agents sat in 'waiting' before your next prompt today
    (per session, capped at 30 min per stretch — beyond that you left)."""
    agent_events_table(conn)
    d0 = datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp()
    rows = conn.execute(
        "SELECT session, state, ts FROM agent_events WHERE ts >= ? ORDER BY ts", (d0,)
    ).fetchall()
    total, open_wait = 0.0, {}
    for session, state, ts in rows:
        if state == "waiting":
            open_wait.setdefault(session, ts)
        elif state == "working" and session in open_wait:
            total += min(ts - open_wait.pop(session), 1800)
    now = time.time()
    for ts in open_wait.values():
        total += min(now - ts, 1800)
    return total / 60


def agents_waiting_now(conn, within=1800):
    """Sessions currently stopped and waiting on the human."""
    agent_events_table(conn)
    rows = conn.execute(
        "SELECT session, state, ts FROM agent_events WHERE ts >= ? ORDER BY ts",
        (time.time() - within,),
    ).fetchall()
    last = {}
    for session, state, ts in rows:
        last[session] = (state, ts)
    return [(s, time.time() - ts) for s, (st, ts) in last.items() if st == "waiting"]


def statusline():
    """One line for the Claude Code statusline: pet face + focus + agent-wait."""
    now = time.time()
    conn = db()
    rows = conn.execute(
        "SELECT source, start, end FROM focus_events WHERE end >= ?"
        " AND lower(source) NOT IN ('attentionos') ORDER BY start", (now - 1800,)
    ).fetchall()
    switches = sum(1 for i in range(1, len(rows)) if rows[i][0] != rows[i - 1][0])
    tracked = sum(min(e, now) - max(s, now - 1800) for _, s, e in rows) / 60
    rate = switches * 60 / tracked if tracked > 1 else 0
    events = load_events(datetime.date.today())
    blocks = focus_blocks(events) if events else []
    deep = sum((e - s) / 60 for _, s, e in blocks if e - s >= 600)
    in_block = any(now - e < 120 for _, s, e in blocks)

    if tracked < 2:
        face = "(=∪ω∪=)zZ"
    elif rate > 25:
        face = "(=>д<=)!!"
    elif in_block and rate < 8:
        face = "(=˃ᴗ˂=)✧"
    else:
        face = "(=˘ᴗ˘=)"
    parts = [face, f"专注{deep:.0f}m"]
    waits = agents_waiting_now(conn)
    if waits:
        longest = max(w for _, w in waits)
        parts.append(f"⏳等你{longest/60:.0f}m" if longest >= 60 else "⏳待命")
    print(" · ".join(parts))


# ---------------------------------------------------------------- pet
def pet():
    """One-line ASCII pet — the Pro-tier mascot. Same mood engine as the
    desktop pet, terminal-native and non-invasive (prints once and exits;
    wire it into your shell prompt or statusline if you want it living)."""
    now = time.time()
    conn = db()
    rows = conn.execute(
        "SELECT source, start, end FROM focus_events WHERE end >= ? ORDER BY start",
        (now - 1800,)).fetchall()
    switches = sum(1 for i in range(1, len(rows)) if rows[i][0] != rows[i - 1][0])
    tracked = sum(min(e, now) - max(s, now - 1800) for _, s, e in rows) / 60
    rate = switches * 60 / tracked if tracked > 1 else 0
    events = load_events(datetime.date.today())
    blocks = focus_blocks(events) if events else []
    in_block = any(now - e < 120 for _, s, e in blocks)

    if tracked < 2:
        face, word = "(=∪ ω ∪=) zZ", "睡着了 · 你不在，我也歇会儿"
    elif rate > 25:
        face, word = "(=> д <=)!!", f"被切碎了 · {rate:.0f} 次/小时的切换"
    elif in_block and rate < 8:
        face, word = "(=๑ ˃̵ᴗ˂̵=) ✧", "心流中 · 我不吵你"
    else:
        face, word = "(=˘ ᴗ ˘=)", f"平静 · 切换 {rate:.0f}/hr"
    print(f"{BOLD}{face}{RESET}  {DIM}{word}{RESET}")


# ---------------------------------------------------------------- main
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "report"
    if cmd == "demo":
        seed_demo()
    elif cmd == "collect":
        collect(int(argv[2]) if len(argv) > 2 else 5)
    elif cmd == "report":
        date = (datetime.date.fromisoformat(argv[2]) if len(argv) > 2
                else datetime.date.today())
        report(date)
    elif cmd == "pet":
        pet()
    elif cmd == "agent-event":
        agent_event(argv[2] if len(argv) > 2 else "working")
    elif cmd == "statusline":
        statusline()
    elif cmd == "wipe":
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        print("all local attention data deleted.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
