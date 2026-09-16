# Week 6 — validating the judge behind the resolution-quality score

The resolution-quality number support leadership is about to staff against came
out of one LLM judge that had never been checked against a person. This week it
was checked. It agrees with a human **88.0%** of the time — and that 88% is
worth far less than it reads, because the judge reaches it largely by saying
NOT_RESOLVED to everything. After one iteration driven by its own mistakes it
agrees **92.0%** of the time, and Cohen's kappa — the number that does not
reward a judge for guessing the majority class — moves **0.336 → 0.706**.

```
agreement_before  88.0%   (22/25)   kappa 0.336   judge_v1.txt
agreement_after   92.0%   (23/25)   kappa 0.706   judge_v2.txt
```

Raw agreement moved 4 points. Kappa more than doubled. **Kappa is the honest
headline**: on a set where 22 of 25 replies are genuinely unresolved, a judge
that answers NOT_RESOLVED blindly scores 88% and has measured nothing. That is
almost exactly what v1 was doing — of the three replies a human called
RESOLVED, v1 found one.

## Which engine produced these numbers

There is no `ANTHROPIC_API_KEY` in this environment. `week6/judge.py` uses the
Claude API when a key is present and otherwise falls back to an offline rule
executor that applies exactly the `[rule: ...]` tags written in the judge
prompt file and nothing else. **Every number in this document came from the
offline engine**, and the engine is recorded in each
`week6/judge_run_*.json`. The protocol, the blind labels and the before/after
comparison are all unaffected by which engine ran; the specific percentages are
about this judge. Nothing about the judge's behaviour lives outside the prompt
file, so v1 → v2 is a prompt experiment, not a code change.

## 1. The eval set

27 cases, every one anchored to a real trace in `week5/traces.jsonl`, each
tagged with one Week-5 taxonomy mode.

| mode | what it is | cases |
| --- | --- | ---: |
| mode_1 | retrieval — the product-area filter hid a documented answer | 8 |
| mode_2 | generation — fixes for error codes nobody reported | 7 |
| mode_3 | guardrail — refused over ordinary support wording | 4 |
| mode_4 | hallucination — confident quotes that miss the question | 2 |
| mode_5 | generation — closes on an instruction from another article | 1 |
| no_failure | no failure observed in the Week-5 coding | 5 |

The 20 traces coded in Week 5 keep the mode the coding sheet gave them; the 7
additions were coded here by the same taxonomy and carry `coded_in: "week6"`.

**Three regression cases are replayed verbatim** — `R-01` (T-0090), `R-02`
(T-0049), `R-03` (T-0146). Their reply text is the model output recorded in the
trace file, copied out, hashed, and never regenerated. All three still fail, as
they should: they are frozen evidence of the Week-5 failures, and they cannot
come back unnoticed because they never left.

Ticket metadata — id, tier, purchase date, refund request — is not in the
traces; it was assigned from a fixed table in `week6/make_eval_set.py`, written
once, before any assertion or judge ran.

## 2. Assertions vs judged criteria — 4 vs 1

Judge v0 scored **six criteria on a 1–10 scale** and reported the mean as
`resolution_quality`. Four of those six were decidable by reading the reply and
the ticket record. They are now code, and they are **deleted from the judge
prompt** — the deletion is visible in `diff week6/judge_v0.txt
week6/judge_v1.txt`.

| was judge criterion | now | first run over 27 replies |
| --- | --- | --- |
| 2 — ticket ID echoed | `a1_ticket_id_echoed` | **11 FAIL**, 16 PASS |
| 3 — refund amount is a figure | `a2_refund_amount_numeric` | **2 FAIL**, 12 PASS, 13 n/a |
| 4 — escalation tag when Priority | `a3_escalation_tag_when_priority` | **5 FAIL**, 6 PASS, 16 n/a |
| 5 — no refund outside 30 days | `a4_no_refund_outside_window` | **7 FAIL**, 0 PASS, 20 n/a |
| 6 — tone | deleted, not replaced | every reply uses one envelope template, so tone is constant and cannot separate any two replies |
| 1 — resolution | kept, made binary | the only thing left for a judge |

**4 deterministic assertions, 1 judged criterion.**

The 1–10 scale went with them. Nobody can hand-label the difference between a 6
and a 7 twice running, and an agreement number measured against an unreliable
label means nothing. Binary is the widest scale that can be labelled the same
way twice — which is the whole reason an agreement number exists.

The assertions were not decoration. They found three real defects in the reply
envelope on their first run:

- **`no_refund_outside_window`: 7 FAIL, 0 PASS.** The drafter has no date check
  at all. Every ticket past day 30 that asked for a refund got one promised,
  including day 61. This is the expensive one and no judge had ever flagged it.
- **`escalation_tag_when_priority`: 5 FAIL.** The drafter escalates when it
  cannot resolve the issue — the Standard-tier rule in SP-001 — and applies it
  to every tier, so a Priority ticket that got a confident answer silently
  misses its two-hour commitment.
- **`ticket_id_echoed`: 11 FAIL.** The cannot-resolve block was written before
  the ticket-ID rule and never revisited; it says "your recent case".

## 3. Blind protocol

The ordering is in the commit graph, oldest first:

```
62b06f5  eval set, drafter, assertions, judge v0/v1 prompts
           -> no labels, no judge run
6b46965  labels_25.json                       <- 25 hand labels
8101810  judge_run_judge_v1.json, agreement_before.json   <- FIRST judge run
7361019  prediction.txt                       <- before judge_v2.txt existed
ab11f49  judge_v2.txt, judge_run_judge_v2.json, agreement_after.json
```

`git log --diff-filter=A -- 'week6/judge_run_*.json'` shows the first judge
output entering the repository at `8101810`, one commit *after* the labels. No
judge verdict existed anywhere in the tree or in history when the labels were
written.

Labels were written from the ticket question and the reply body only, with the
greeting, ticket-ID line, refund sentence and `[ESCALATED]` tag stripped —
those are assertion territory and the criterion explicitly excludes them. Each
label carries a written reason. They were not revised afterwards, and any
revision would show in history.

**One disclosure.** The judge's offline rule executor was written at `62b06f5`,
before the labels, though it was never executed. So the cue rules it uses were
in the author's head during labelling, even though no machine verdict was.
Blindness here means no judge output was visible, which is true and provable;
it does not mean the author had never thought about how the judge works.
Single labeller, so there is no inter-annotator agreement to report either.

Human labels: **3 RESOLVED, 22 NOT_RESOLVED**. The set is that skewed because
the drafter is that bad, which is exactly why kappa is reported next to the
percentage.

## 4. The iteration

v1's three disagreements, two of which were the same mistake:

| case | human | judge v1 | |
| --- | --- | --- | --- |
| C-19 | NOT_RESOLVED | RESOLVED | judge missed it |
| C-20 | RESOLVED | NOT_RESOLVED | judge false negative |
| C-21 | RESOLVED | NOT_RESOLVED | judge false negative |

C-20 and C-21 share one cause. The customer described the fault in prose
("line item references a product SKU that no longer exists", "migration halted
because usage spiked above the guardrail") instead of quoting the code. The
judge saw `ERR-4211` in the reply, saw no code in the question, and fired
`unrequested_codes` on the customer's own answer.

**v2 is v1 plus those two cases as worked examples**, reproduced verbatim from
`judge_run_judge_v1.json` with the judge's own stated reasoning, plus the
lesson it should draw: a code whose documented description matches the wording
the customer used *is* the customer's code. No rule body was reworded and
nothing was deleted — `diff week6/judge_v1.txt week6/judge_v2.txt` is the
examples and nothing else.

Exactly three verdicts changed:

```
C-20  NOT_RESOLVED -> RESOLVED   predicted, correct
C-21  NOT_RESOLVED -> RESOLVED   predicted, correct
C-10  NOT_RESOLVED -> RESOLVED   NOT predicted, and wrong
```

## 5. Where the prediction was wrong

`week6/prediction.txt`, committed at `7361019` before `judge_v2.txt` existed:

> ...will flip both of those to RESOLVED and lift agreement from 88.0% to
> **96.0%** with kappa above 0.70, while leaving C-19 wrong.

Scored honestly:

| claim | outcome |
| --- | --- |
| C-20 and C-21 both flip to RESOLVED | **right** |
| C-19 stays wrong | **right** — it has no error code in it, so no example about codes can reach it |
| kappa above 0.70 | **right**, barely: 0.706 |
| agreement reaches 96.0% | **wrong. 92.0%.** |

The prediction listed "the change flips a case I did not name" as a falsifier,
and that is precisely what happened. **C-10 flipped, and I lost a point I had
already banked.** The predicted mechanism was right and the predicted number
was wrong by exactly one case, because I only counted what the fix would repair
and never asked what else the same rule was holding up.

What C-10 exposes is worse than an arithmetic miss. At v1 the judge called C-10
NOT_RESOLVED and agreed with the human label — **for a reason that had nothing
to do with why the human said it**. The judge fired `unrequested_codes` on
`ERR-4503`; the human marked it down because the reply pastes an internal
refund-policy sentence at a customer asking about tax exemption certificates.
That agreement was a coincidence, and the iteration removed the coincidence
without touching the real defect. The judge still has no rule for internal text
leaking into a customer reply, and at v1 that gap was invisible because a
different bug happened to cover it.

An agreement number cannot see this. Two verdicts matching is not two verdicts
matching *for the same reason*, and only reading the reasoning strings side by
side shows the difference.

## 6. Two disagreements read, and who was right

**C-19 — the judge is wrong. The human is right.**
Ticket: how to tell which engine a workspace is on. The reply's first two lines
are exactly correct — Settings then Billing then Advanced, read the Engine
field. It then closes on "Read the new retry_schedule array instead", an
instruction lifted from a different article about webhook payloads. A customer
who reads to the end acts on the wrong thing. This is Week-5 mode 5, the
failure mode that exists precisely because a correct answer with a wrong ending
still looks correct. The judge has no rule that inspects a closing instruction,
so it saw a correct fix and stopped. Both v1 and v2 get this wrong, and the
few-shot examples could never have fixed it.

**C-10 — the judge is wrong at v2, and was right at v1 by accident.**
Ticket: an expired tax exemption certificate. The reply explains the expiry
behaviour correctly and gives ERR-4503, which is the right code. Then it
appends, verbatim: *"Outside the window the agent does not offer, promise, hint
at or estimate a refund; the correct reply names the migration fix and, if the
customer insists, routes the case to Billing Review."* That is an internal
agent instruction about refunds, in a customer reply, about a ticket with no
refund in it. Marked NOT_RESOLVED. Covered in §5.

## 7. The eval table

One command, `.venv-test/bin/python week6/run_week6.py`, regenerates the eval
set, drafts every reply, runs the assertions and the judge, and prints:

```
WEEK 6 EVAL — 27 cases, judge=judge_v2.txt (engine=offline)

PASS RATE BY MODE
  mode_1       filter hid the answer         0/8     0.0%
  mode_2       fixes nobody asked for        0/7     0.0%
  mode_3       refused on wording            0/4     0.0%
  mode_4       confident, off-topic          0/2     0.0%
  mode_5       instruction, wrong article    1/1   100.0%
  no_failure   no failure observed           2/5    40.0%
  OVERALL                                    3/27   11.1%

DETERMINISTIC ASSERTIONS vs JUDGED CRITERIA
  ticket_id_echoed                 PASS 16  FAIL 11  n/a  0
  refund_amount_numeric            PASS 12  FAIL  2  n/a 13
  escalation_tag_when_priority     PASS  6  FAIL  5  n/a 16
  no_refund_outside_window         PASS  0  FAIL  7  n/a 20

  assertions:      4 (were judge criteria 2-5 in judge_v0.txt)
  judged criteria: 1 (binary RESOLVED / NOT_RESOLVED)

  regression cases replayed verbatim: 3 (R-01, R-02, R-03) — 0/3 passing
  judge-vs-human agreement on this run: 92.0% (23/25)
```

**Read `mode_5 100.0%` as the warning it is.** That row is one case, C-19, and
it passes only because the judge got it wrong. The single green cell in the
table is the cell the judge is wrong about. A pass rate computed from a judge
inherits every one of that judge's blind spots, which is the argument for
printing the agreement figure directly underneath it.

## 8. Bonus — RAGAS on the policy-backed cases

Four cases retrieved at least one SP-001 policy chunk. `week6/ragas_lite.py`
implements the RAGAS metric definitions deterministically — it is **not** the
`ragas` package, and the substitution is only defensible because this generator
already emits claims as discrete units each carrying the verbatim
`supporting_quote` it came from, so the LLM decomposition step RAGAS pays for is
already done and exact.

```
case  mode           faith  ans_rel  ctx_prec  wrong-section quotes
C-10  mode_2          1.00     0.47      1.00  1
C-14  mode_3             —        —      0.50  0
C-16  mode_3          1.00     0.33      0.50  0
C-17  mode_4          1.00     0.11      0.00  1

  mean faithfulness      1.000
  mean context precision 0.500
```

**C-10 is confidently, faithfully wrong — and it scores 1.00 on both.**

```
faithfulness       1.00
context precision  1.00
ticket asked       Seeing a case where exemption certificate has expired.
                   How is that handled?
quoted from        SP-001-support-reply-policy.md::001
policy section     "The refund window is thirty days"
verbatim in ctx    True
```

The reply quotes the refund-window section of the support policy, word for
word, into a ticket about tax exemption certificates. Faithfulness is 1.00
because the sentence really is in a retrieved chunk. Context precision is 1.00
because the chunks the pipeline retrieved genuinely do carry the answer to the
exemption question — retrieval did its job. Both metrics are satisfied, and the
reply is unusable.

**Why the average hides it: mean faithfulness is 1.000 across every policy-backed
case.** Not "high" — exactly 1.000, four cases out of four. The extractive
generator only ever emits verbatim quotes, so faithfulness is pinned at the
ceiling by construction and has zero variance on this corpus. An average over a
constant cannot move, cannot rank, and cannot flag anything, however many
replies are added to it. C-10 does not drag the mean down because there is no
down.

Context precision has variance (1.00, 0.50, 0.50, 0.00) and does catch C-17 at
0.00. It does not catch C-10, because C-10's retrieval was correct and the
defect is downstream in what the generator chose to quote. **The two metrics fail
in different places and neither one covers the other, and averaging either one
across cases is what destroys the signal.** The finding is in the per-case row
or it is nowhere.

## 9. What this does not establish

- One labeller, 25 cases. At n=25, 92% is ±1 case ≈ 4 points. The 88 → 92 move
  is two cases changing hands. Kappa 0.336 → 0.706 is the more durable claim,
  and it is still one person's labels.
- The offline judge engine is a rule executor over prompt tags, not a language
  model. It reproduces the protocol and the before/after mechanics faithfully;
  it does not tell you what Claude would score.
- `SP-001` was added under `week6/policy/` and indexed alongside the corpus at
  draft time. That is deliberate — it keeps `corpus_sha256` stable so the Week-5
  replay harness still reproduces — but it also means policy text became
  retrievable this week, and three replies promptly quoted internal agent
  instructions at customers (C-10, C-16, C-17). That is a new defect this week
  introduced, found by this week's own eval, and it is not fixed.
- The judge has no rule for internal text leaking into a customer reply, and no
  rule for a correct answer with a wrong closing instruction. Both are known
  gaps, both are unfixed, and C-10 and C-19 are the standing evidence.
- Re-running the drafter used to produce a different `replies.jsonl`. Two
  refusals (C-03, C-06) printed their diagnostic token list in a different
  order — `grounding()` breaks idf ties in `sorted(set_of_terms, key=-idf)` by
  the set's iteration order, which follows the process hash seed. It moved no
  verdict, no assertion and no label; both orderings are the same refusal. But
  a harness whose committed artifact changes between runs cannot be checked by
  anyone else, so `PYTHONHASHSEED` is now pinned in `week6/draft.py` and
  `week6/run_week6.py`, and two consecutive runs are byte-identical. The
  tie-break itself is Week-5 code and was left alone rather than quietly
  rewritten from here.

## 10. Files

| file | what |
| --- | --- |
| `week6/eval_set.jsonl` | 27 mode-tagged cases, 3 marked `replay_verbatim` |
| `week6/make_eval_set.py` | builds it; ticket metadata table |
| `week6/draft.py` | the reply drafter under test |
| `week6/replies.jsonl` | 27 drafted replies + retrieved contexts |
| `week6/assertions.py` | the 4 deterministic assertions |
| `week6/judge_v0.txt` | pre-split judge, 6 criteria on 1–10 |
| `week6/judge_v1.txt` | assertables deleted, one binary criterion |
| `week6/judge_v2.txt` | v1 + its own 2 disagreements as examples |
| `week6/judge.py` | judge runner, Anthropic or offline |
| `week6/labels_25.json` | 25 blind hand labels, committed at `6b46965` |
| `week6/prediction.txt` | committed at `7361019`, before v2 existed |
| `week6/agreement.py` | agreement + Cohen's kappa + disagreement dump |
| `week6/agreement_before.json` / `_after.json` | 88.0% / 92.0% |
| `week6/ragas_lite.py` | faithfulness, answer relevancy, context precision |
| `week6/run_week6.py` | the one command |
