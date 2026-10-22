# Race: triage squad vs single agent

Cases (same 10 Week-6 eval cases, judge `judge_v2.txt` + 4 SP-001 assertions): C-01, C-02, C-04, C-05, C-06, C-07, C-08, C-09, C-10, C-11

| Metric | Single agent | Single + parallel tools | Triage squad |
|---|---|---|---|
| Pass rate | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) |
| Latency p50 / p99 | 1.33s / 2.44s | 1.33s / 2.85s | 2.19s / 3.81s |
| Total tokens | 28,231 | 28,291 | 31,903 |
| Cost per ticket (claude-opus-5-5) | $0.0151 | $0.0152 | $0.0203 |

Context re-send multiplier: 31,903 / 28,231 = 1.1x — largest share: orchestrator -> policy worker resend (ticket + triage + full SP-001, sent again with the chunks), 70% of all squad tokens

## Per case

| Case | Single | Single + parallel | Squad | Single tokens | Parallel tokens | Squad tokens |
|---|---|---|---|---|---|---|
| C-01 | PASS | PASS | PASS | 3,130 | 3,155 | 3,558 |
| C-02 | PASS | PASS | PASS | 2,591 | 2,592 | 2,927 |
| C-04 | PASS | PASS | PASS | 2,612 | 2,613 | 3,006 |
| C-05 | PASS | PASS | PASS | 3,060 | 3,090 | 3,511 |
| C-06 | PASS | PASS | PASS | 2,607 | 2,607 | 2,974 |
| C-07 | PASS | PASS | PASS | 2,433 | 2,434 | 2,775 |
| C-08 | PASS | PASS | PASS | 3,318 | 3,319 | 3,506 |
| C-09 | PASS | PASS | PASS | 2,592 | 2,592 | 2,925 |
| C-10 | PASS | PASS | PASS | 3,320 | 3,321 | 3,794 |
| C-11 | PASS | PASS | PASS | 2,568 | 2,568 | 2,927 |
