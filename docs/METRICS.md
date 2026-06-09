# AttentionOS Metric Spec — v0.1 (draft)

Five metrics, named and defined precisely enough that independent tools can
compute compatible numbers. All metrics are computed locally from a single
primitive: the **focus event**.

```
FocusEvent = { source: string, start: timestamp, end: timestamp, kind: "app" | "tab" | "agent-session" }
```

A focus event is a contiguous interval during which one source held the user's
foreground focus. Collectors may differ (window manager hooks, browser
extensions, IDE plugins) but must emit this shape.

Terminology below: a **dwell** is one focus event's duration. A **switch** is
the boundary between two consecutive focus events with different sources.

---

## 1. Focus Half-Life (FHL)

*The median length of an uninterrupted focus block.*

A **focus block** is a maximal run of consecutive focus events where every
switch within the run returns to the anchor source within `GRACE = 30s`
(a quick reference glance does not break a block), and every dwell away from
the anchor is shorter than `GRACE`.

```
FHL = median(duration of all focus blocks ≥ MIN_BLOCK)
MIN_BLOCK = 60s   # sub-minute blocks are noise, not focus
```

Report in minutes. A knowledge worker's raw FHL is typically 3–12 min;
defended deep-work FHL can exceed 40 min.

## 2. Context Switch Rate (CSR)

*Switches per active hour, with estimated recovery cost.*

```
CSR = count(switches) / active_hours
RecoveryCost = count(deep_preemptions) × RECOVERY_PENALTY
deep_preemption = a switch that terminates a focus block ≥ 5 min
RECOVERY_PENALTY = 9.5 min   # empirical resumption-lag estimate (Mark et al., CHI 2008)
```

`active_hours` excludes idle gaps > 5 min. Report CSR as a rate and
RecoveryCost as minutes/day of estimated lost re-immersion time.

## 3. Interrupt Load (IL)

*What fraction of your switches were done TO you, vs. BY you.*

Classify each switch:

- **External interrupt** — preceded within 5s by a notification, or the gained
  source is a communication app (configurable interrupter list).
- **Self-inflicted switch** — everything else (you wandered).

```
IL = external_interrupts / total_switches
SelfSwitchRate = 1 - IL
```

The IL/self split is the single most actionable number in the spec: high IL
means your environment is the problem; high self-switch rate means the
interrupts have trained you to interrupt yourself.

## 4. Attention Budget (AB)

*Deep-focus hours available per day, and what consumed them.*

```
AB_capacity = rolling 28-day p75 of daily deep-focus minutes
deep_focus  = total time in focus blocks ≥ 10 min
AB_spent    = today's deep-focus minutes
AB_burn     = AB_spent / AB_capacity
```

Budget consumers are attributed per-source: which apps/sessions sat inside deep
blocks vs. which ones terminated them.

## 5. Recovery Debt (RD)

*The burnout early-warning. An OS that ignores thermal limits melts the chip.*

```
RD = Σ over last 7 days of max(0, AB_burn_day - 1.0)
```

Sustained `AB_burn > 1.0` means spending above capacity. Thresholds:

- `RD < 0.5` — sustainable
- `0.5 ≤ RD < 1.5` — borrowed time; schedule recovery
- `RD ≥ 1.5` — throttling predicted: error rate up, FHL down, mood down

RD is deliberately asymmetric: under-spending never builds "credit". Rest is
maintenance, not currency.

---

## The Attention Audit (browser test)

The zero-install test measures a different, complementary thing: **sustained
attention under monotony**, via a 60-second SART (Sustained Attention to
Response Task — respond to every digit except 3).

Reported sub-metrics:

| Metric | Meaning |
|---|---|
| Lapses (omissions) | Zoned out — missed a go-trial |
| Impulses (commissions) | Autopilot — responded to the no-go digit |
| RT stability (1 − CV) | Consistency of reaction time |
| Vigilance drift | 2nd-half degradation vs. 1st half |
| Tab escapes | Times you left the tab during a 60s test |

Composite score (0–100):

```
score = clamp(100 − 9·impulses − 5·lapses − 120·max(0, CV − 0.10) − 25·max(0, drift) − 10·tab_escapes)
```

Grades: ≥90 **Laser-locked** · ≥75 **Steady** · ≥60 **Flickering** ·
≥40 **Drifting** · else **Strip-mined**.

The audit is a snapshot for virality and self-comparison; the collector metrics
above are the longitudinal truth. Don't confuse the two.

---

## Privacy requirements (normative)

Implementations MUST: store events locally by default; require explicit opt-in
per destination for any export; never capture content (titles optional and
off by default — source app/domain is enough); provide one-command data wipe.
