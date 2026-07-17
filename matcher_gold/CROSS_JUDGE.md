# Cross-judge agreement (matcher reliability)

Band pairs: 1031; decided by all 3 judges: 1031.

## Per-judge vs gold (oracle-derived labels)

| judge | agreement | κ vs gold |
|---|---|---|
| deepseek-v4-pro | 0.9952 | 0.9767 |
| opus-4.8 | 0.9971 | 0.9859 |
| gpt-5.5 | 0.9971 | 0.9857 |

## Inter-judge κ (pairwise, different families)

| judge A | judge B | κ |
|---|---|---|
| deepseek-v4-pro | opus-4.8 | 0.9814 |
| deepseek-v4-pro | gpt-5.5 | 0.9717 |
| opus-4.8 | gpt-5.5 | 0.9810 |

## Majority-vote matcher (3 judges, band)

| precision | recall | F1 | accuracy |
|---|---|---|---|
| 0.9989 | 0.9989 | 0.9989 | 0.9981 |

