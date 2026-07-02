# AttentionOS

> We spent billions teaching models to attend better.
> Your attention span is still about 47 seconds.
> The bottleneck isn't the model anymore — it's you.

**AttentionOS is an open-source observability layer for the human in the loop.**
It measures your attention the way you'd profile a system — context switches,
interrupts, scheduler pressure, thermal throttling — and gives you the tools to
defend it.

*Attention is all you need. Yours. Not the model's.*

---

## Why

Every layer of the AI stack is instrumented except one. We benchmark models,
trace agents, eval harnesses, and A/B test multi-agent topologies. Meanwhile the
human who reviews, decides, and context-switches between five agent sessions
runs completely unprofiled — and that human is now the scarcest resource in the
loop.

The result is predictable: as agents do more, your job becomes pure attention
allocation. And attention is being strip-mined — by notifications, by tab
sprawl, and increasingly by your own agents interrupting you mid-thought.

AttentionOS treats your attention like the operating system resource it is:

| OS concept | Your day |
|---|---|
| Process | A task, or an agent session you supervise |
| Context switch | Every window/task hop (and its recovery cost) |
| Interrupt | Notifications, Slack, "quick questions", agent pings |
| Scheduler | When deep work happens vs. when it gets preempted |
| Interrupt coalescing | Batching pings into your low-focus windows |
| Thermal throttling | Burnout — the system degrading to protect itself |

## What's here

This is an early prototype. Three pieces:

### 1. The Attention Check-up (browser, zero install, 中/EN)
A 60-second, 3-stage micro-game that profiles the three attentional networks
of Posner & Petersen — **alerting, orienting, executive** (ANT paradigm,
Fan et al. 2002) — with live per-response scoring, and ends in your
**attention type** (Cheetah / Hawkeye / Fortress / Commander…), a radar
profile, and a personalized attention-allocation prescription. Shareable
result card included. Open [`demo/index.html`](demo/index.html) in a browser.
No data leaves the page. Theory & honest limitations: [`docs/SCIENCE.md`](docs/SCIENCE.md).

### 2. `attn` — the collector & profiler (CLI)
A local-first attention profiler. Polls window focus, stores events in SQLite
on your machine, and renders an `htop`-for-your-brain daily report.

```sh
cd cli
python3 attn.py demo      # generate a synthetic workday (try it instantly)
python3 attn.py report    # render the attention report
python3 attn.py collect   # start the real macOS collector (local only)
```

### 3. The Metric Spec
Five named, open metrics — [`docs/METRICS.md`](docs/METRICS.md) — so every tool
can speak the same vocabulary:

1. **Focus Half-Life** — median length of an uninterrupted focus block
2. **Context Switch Rate** — switches per hour, with estimated recovery cost
3. **Interrupt Load** — external preemptions vs. self-inflicted switches
4. **Attention Budget** — deep-focus hours available, and what consumed them
5. **Recovery Debt** — trailing 7-day budget overdraw; the burnout early-warning

## Principles

- **Local-first, always.** Your attention data never leaves your machine by
  default. An attention tracker that phones home is surveillance.
- **No biometrics.** Window focus and input cadence only. No webcams, no
  wearables in core. (Optional plugins can add them for those who want it.)
- **Protective, not extractive.** This is not a productivity score to optimize
  for your manager. It's an audit of who is strip-mining your attention, so you
  can take it back. Scores are personal; sharing is opt-in bragging.
- **Anti-burnout by design.** Recovery Debt is a first-class metric. An OS that
  ignores thermal limits melts the chip.

## Roadmap

- [x] **Phase 0** — manifesto, metric spec v0.1, browser attention audit
- [ ] **Phase 1** — macOS menu-bar collector, `attn top` live view, share cards
- [ ] **Phase 2** — MCP server: agents query `attention://state` and batch
      their interrupts until you surface from deep focus
- [ ] **Phase 3** — plugin ecosystem (calendar, Slack, IDE), interrupt
      scheduling, Linux/Windows collectors

## Contributing

Phase 0 is a conversation starter. Open an issue with your sharpest take on the
metric spec — especially if you think a metric is wrong. The vocabulary is the
project.

MIT licensed.
