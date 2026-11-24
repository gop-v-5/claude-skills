# A/B Test Hypothesis Template

A good hypothesis forces you to be specific about what you're changing, what you expect to happen, why you expect it, and how you'll know. Vague hypotheses produce unlearnable tests.

## The core format

> **We believe** [changing X to Y]
> **will improve** [specific metric]
> **for** [specific audience / traffic segment]
> **because** [reason grounded in evidence]
> **We'll know we're right when** [primary success criterion]
> **We'll know we're wrong when** [primary failure criterion]

## Full hypothesis doc structure

For each of the top 3 PXL-ranked test ideas, output:

```markdown
### Test: [Short descriptive name]

**Hypothesis**
We believe [change] will improve [metric] for [audience] because [evidence-based reason].

**Control (A)**
[Describe current state — quote current headline/CTA/layout]

**Variant (B)**
[Describe proposed state — new headline/CTA/layout, ready to ship]

**Primary metric**
[One metric — e.g., signup conversion rate on this page]

**Secondary / guard metrics**
- [Guard metric 1 — e.g., bounce rate shouldn't increase]
- [Guard metric 2 — e.g., downstream activation shouldn't drop]

**Audience / segment**
[All traffic, or a specific segment like "paid social traffic" or "mobile visitors"]

**Success criteria**
- Win: a statistically significant positive result at 95% confidence whose lift meets or exceeds the minimum detectable effect you powered the test for (the MDE — your "≥X%" threshold) — ship the variant
- Inconclusive / no change: not statistically significant at 95% confidence, **or** a statistically significant movement in either direction whose absolute effect is below that same MDE (too small to be worth the added complexity) — no winner, keep control and move on
- Loss: a statistically significant negative result at 95% confidence whose drop meets or exceeds the MDE in magnitude — roll back and diagnose

**Required sample size**
[Estimate based on current conversion rate and minimum detectable effect. If unknown, note "TBD — needs MDE calc based on baseline CR"]

**Estimated test duration**
[Based on page traffic — e.g., "~2 weeks at current traffic of 8k sessions/week"]

**Evidence supporting this hypothesis**
- [GA4 data point]
- [GSC data point, heatmap, user research, or LIFT audit finding]
- [Any prior test, competitor pattern, or best-practice reference]

**What we'll learn either way**
[1–2 sentences on what the result teaches us about our audience, regardless of win/loss. If there's nothing to learn from a null result, the test isn't worth running.]
```

## Rules for good hypotheses

1. **One variable per test.** If you change both the headline and the CTA, you won't know which drove the lift.
2. **The "because" clause must reference evidence**, not a hunch. "Because we think users want X" is not a hypothesis — it's a guess.
3. **The metric must be specific and measurable in your analytics setup.** "Improve engagement" is not a metric; "increase signup conversion rate" is.
4. **Guard metrics prevent Pyrrhic wins.** A headline that boosts clicks but tanks downstream activation is a loss, not a win.
5. **If the hypothesis can't be wrong, it's not a hypothesis.** Every test idea should have a clear failure condition.
