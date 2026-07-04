# The science behind the Attention Check-up

The browser demo is a playful, 60-second adaptation of established attention
paradigms — not a clinical instrument. This page documents what each stage
measures, where the norms come from, and where we deliberately traded rigor
for shareability.

## The three-network model

Posner & Petersen (1990) decompose attention into three anatomically and
pharmacologically distinct networks:

| Network | Function | Neuromodulator | Our stage |
|---|---|---|---|
| **Alerting** | achieving & maintaining readiness | norepinephrine | Stage 1 — speeded simple reaction |
| **Orienting** | selecting among sensory inputs | acetylcholine | Stage 2 — visual search |
| **Executive** | resolving conflict among responses | dopamine | Stage 3 — flanker conflict |

The canonical measurement is the **Attention Network Test (ANT)** of
Fan, McCandliss, Sommer, Raz & Posner (2002), which derives all three network
efficiencies from one flanker-based task (~30 min). We split the networks into
three distinct micro-games instead — worse psychometrics, far better game feel.

## What each stage computes

- **Stage 1 (Alerting)** — median simple RT over 5 trials, false starts
  penalized. Adult simple RT norms center around 250–350 ms.
- **Stage 2 (Orienting)** — median search time to find a rotated **L** among
  rotated **T**s (12 items). T-vs-L is the classic *serial* (inefficient)
  search task (Wolfe, 1998): the target does not "pop out", so finding it
  demands active orienting. Wrong taps add a 300 ms penalty.
- **Stage 3 (Executive)** — Eriksen flanker (Eriksen & Eriksen, 1974) with 4
  congruent / 4 incongruent trials. The score is driven by **conflict cost** =
  median(incongruent RT) − median(congruent RT), the ANT's executive measure.
  Fan et al. (2002) report mean conflict costs around 84–120 ms in healthy
  adults; errors multiply the score down.

## Scoring

Each raw measure maps to a 0–100 score through a logistic centered on
published adult norms:

```
score = 100 / (1 + exp((x - mid) / k))
alerting:  mid = 330 ms,  k = 50     (simple RT)
orienting: mid = 1350 ms, k = 340    (12-item T/L search)
executive: mid = 115 ms,  k = 42     (conflict cost) × accuracy multiplier
overall  = 0.3·A + 0.3·O + 0.4·E
```

Calibration note (v0.2.1): early testers clustered into the alerting/
orienting archetypes, so those two curves were tightened and the
executive error penalty relaxed (×0.10 per error, floor 0.4) to even
out the archetype distribution. Ambient "ghost drifters" now float
across the screen during the test — a deliberate, theme-consistent
distraction load that keeps ceiling scores honest.

Because the logistic is centered on the norm median, a score of *S* reads
approximately as "ahead of ~*S*% of the norm sample" — that is the claim the
UI makes, and it is labeled as an approximation everywhere it appears.

## Honest limitations

5–8 trials per network is far below research-grade reliability (the ANT uses
288). Browser/display latency adds 10–50 ms of noise. Norms vary with age and
device. The check-up is a **conversation starter and a self-comparison
baseline** — retake it at different times of day and the *relative* changes
are more meaningful than the absolute score. For longitudinal truth, use the
`attn` collector and the metrics in [METRICS.md](METRICS.md).

## References

- Posner, M. I., & Petersen, S. E. (1990). The attention system of the human
  brain. *Annual Review of Neuroscience, 13*, 25–42.
- Fan, J., McCandliss, B. D., Sommer, T., Raz, A., & Posner, M. I. (2002).
  Testing the efficiency and independence of attentional networks.
  *Journal of Cognitive Neuroscience, 14*(3), 340–347.
- Eriksen, B. A., & Eriksen, C. W. (1974). Effects of noise letters upon the
  identification of a target letter in a nonsearch task.
  *Perception & Psychophysics, 16*, 143–149.
- Wolfe, J. M. (1998). Visual search. In H. Pashler (Ed.), *Attention*.
- Robertson, I. H., et al. (1997). 'Oops!': Performance correlates of everyday
  attentional failures (SART). *Neuropsychologia, 35*(6), 747–758. (Used by
  the earlier audit variant and the CLI's vigilance framing.)
- Mark, G., Gudith, D., & Klocke, U. (2008). The cost of interrupted work:
  More speed and stress. *CHI 2008*. (Recovery-cost estimate in the CLI.)
