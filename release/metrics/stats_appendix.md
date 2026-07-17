### Appendix A — All inferential tests, effect sizes, and multiplicity control

We declare a **confirmatory** family (memory raises correct-convergence and improves the dynamics metrics, mem-vs-nomem, plus the two other replicated memory arms) and an **exploratory** family (mechanism contrasts, the precision/recall cost, the single-batch and second-reviewer replications). The table lists every reported test with its effect size, 95% CI, raw *p*, and **Holm-Bonferroni-adjusted *p*** across all 16 tests. Regime rates use per-artifact-majority labels (exact McNemar on discordant artifacts); continuous metrics use the paired sign test over per-artifact means. The three primary memory-vs-nomem McNemar results, all mem/ledger/structured dynamics tests, and the precision-cost survive Holm correction; the mechanism nulls, the recall test, the single-batch replication, and the second-reviewer (GPT-5.5) replication do not survive correction (the last is significant only uncorrected, Holm *p* = 0.27), consistent with the in-text reporting.

| family | comparison | effect (95% CI) | disc. | raw *p* | Holm *p* | survives |
|---|---|---|---|---:|---:|:--:|
| conf | mem vs nomem: correct-convergence (McNemar) | +0.283 [+0.152, +0.415] | 19/2 | <0.001 | 0.0024 | yes |
| conf | mem vs nomem: mean churn (sign) | -0.086 [-0.109, -0.064] | 5/46/9 | <0.001 | <0.001 | yes |
| conf | mem vs nomem: oscillation (sign) | -0.444 [-0.585, -0.304] | 4/35/21 | <0.001 | <0.001 | yes |
| conf | mem vs nomem: stabilized round (sign) | -1.194 [-1.576, -0.813] | 9/40/11 | <0.001 | <0.001 | yes |
| conf | ledger vs nomem: correct-convergence (McNemar) | +0.250 [+0.114, +0.386] | 18/3 | 0.0015 | 0.0149 | yes |
| conf | structured vs nomem: correct-convergence (McNemar) | +0.217 [+0.094, +0.340] | 15/2 | 0.0023 | 0.0211 | yes |
| conf | ledger vs nomem: mean churn (sign) | -0.087 [-0.115, -0.058] | 9/42/9 | <0.001 | <0.001 | yes |
| conf | structured vs nomem: mean churn (sign) | -0.092 [-0.117, -0.067] | 5/43/12 | <0.001 | <0.001 | yes |
| expl | ledger vs mem: correct-convergence (McNemar) | -0.033 [-0.136, +0.070] | 4/6 | 0.7539 | 1.0000 | no |
| expl | ledger vs structured: correct-convergence (McNemar) | +0.033 [-0.070, +0.136] | 6/4 | 0.7539 | 1.0000 | no |
| expl | mem vs structured: correct-convergence (McNemar) | +0.067 [-0.035, +0.169] | 7/3 | 0.3438 | 1.0000 | no |
| expl | mem vs nomem: terminal precision (sign) | -0.034 [-0.055, -0.012] | 6/21/33 | 0.0059 | 0.0474 | yes |
| expl | mem vs nomem: terminal recall (sign) | +0.019 [-0.004, +0.043] | 12/5/43 | 0.1435 | 0.7173 | no |
| expl | mem vs structured: stabilized round (sign) | +0.317 [-0.042, +0.675] | 28/14/18 | 0.0436 | 0.2700 | no |
| expl | single-mem vs single-nomem: correct-convergence (McNemar) | +0.083 [-0.050, +0.216] | 11/6 | 0.3323 | 1.0000 | no |
| expl | GPT-5.5 reviewer: mem vs nomem correct-convergence (McNemar) | +0.133 [+0.025, +0.241] | 10/2 | 0.0386 | 0.2700 | no |

*Multiplicity policy.* Holm-Bonferroni over all 16 tests at alpha = 0.05. 9 of 16 survive. The headline (mem > nomem correct-convergence) and every dynamics contrast for the three replicated memory arms survive; no null (mechanism-invariance, recall) is claimed as significant. The precision-cost survives (Holm *p* = 0.047); the second-reviewer (GPT-5.5) replication is significant only **uncorrected** (*p* = 0.039, Holm *p* = 0.27) and is reported as such in-text.
