# Matcher threshold sensitivity

Headline P/R recomputed across a grid of the deterministic matcher's decision boundary (`tau_mid`, the lexical-fallback threshold that decides every pair not resolved by the auto-same/auto-different shortcuts). The curve is the precision/recall trade-off; a broad F1 plateau is the evidence that conclusions do not hinge on a knob choice.

| tau_mid | precision | recall | F1 | accuracy |
|---|---|---|---|---|
| 0.3 | 0.893 | 0.6018 | 0.7191 | 0.7649 |
| 0.35 | 0.9104 | 0.5126 | 0.6559 | 0.7311 |
| 0.4 | 0.9245 | 0.4523 | 0.6074 | 0.7077 |
| 0.42 | 0.9276 | 0.4505 | 0.6064 | 0.7077 |
| 0.45 | 0.9225 | 0.3541 | 0.5117 | 0.6622 |
| 0.5 | 0.9282 | 0.291 | 0.4431 | 0.6342 |
| 0.55 | 0.9321 | 0.2225 | 0.3593 | 0.6032 |

- F1 range: 0.3593 – 0.7191 (spread 0.3598)
- precision range: 0.893 – 0.9321
- recall range: 0.2225 – 0.6018

