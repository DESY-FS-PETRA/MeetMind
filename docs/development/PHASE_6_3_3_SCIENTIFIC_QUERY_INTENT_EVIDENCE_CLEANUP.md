# Phase 6.3.3 — Scientific Query Intent & Evidence Cleanup

This patch fixes three regressions observed in real Chat testing after Phase 6.3.2.

## 1. Formula / equation / definition requests no longer become archive-only follow-ups

A self-contained scientific request such as:

- `tell me the Otsu formula`
- `what is the Fourier transform?`
- `define phase retrieval`
- `explain Otsu segmentation`

now defaults to the general/hybrid knowledge route even when the immediately preceding answer contained meeting citations.

Explicit archive scoping still wins. For example:

- `What Otsu formula was discussed in the meeting?`
- `What equation did Shahin show in the presentation?`

remain strict meeting-RAG questions.

## 2. Deterministic Otsu scientific guard

Otsu was producing an unsafe local-LLM explanation that could invert the optimization criterion or invent an equation. Phase 6.3.3 adds a canonical guard for Otsu questions.

The app now keeps these facts fixed:

- maximize between-class variance;
- equivalently minimize weighted within-class variance;
- do not describe Otsu as minimizing between/inter-class variance;
- do not claim that fitting a two-Gaussian mixture is required.

For an explicit Otsu formula request, the general part is generated deterministically as display LaTeX:

```latex
$$
\sigma_B^2(t)=\omega_0(t)\,\omega_1(t)\left[\mu_0(t)-\mu_1(t)\right]^2
$$

$$
t^*=\operatorname*{arg\,max}_{t}\;\sigma_B^2(t)
$$
```

When related meeting evidence exists, Ollama is only asked to write the grounded `From your meetings:` paragraph. It cannot rewrite the canonical general formula.

## 3. Closing-slide suppression for overview questions

For overview/goal questions such as:

`what is the shahin's talk about?`

the answer evidence is compacted and closing-only sources are removed when stronger sources exist. `Thank you`, presentation-concluded and Q&A-boundary slides are therefore not offered as evidence for the topic of the talk.

Questions explicitly asking about the final slide, closing, Q&A, or post-talk discussion are not filtered.

## Regression tests

Seven new tests cover:

- formula request after a citation-bearing answer routes to knowledge/hybrid;
- explicitly meeting-scoped formula stays strict RAG;
- canonical Otsu formula and LaTeX;
- Otsu criterion wording and Gaussian-mixture guard;
- overview closing-slide removal;
- hybrid Otsu formula with grounded meeting context;
- end-to-end talk overview without a closing source.

Full backend suite after this patch:

```text
Ran 118 tests
OK
```

No database migration or RAG re-index is required.
