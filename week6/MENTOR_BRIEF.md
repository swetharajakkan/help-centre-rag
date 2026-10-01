# Week 6 — mentor brief

How to explain this week's work, what number proves each claim, and the two
topics on the syllabus that are **not** in the code.

---

## The story in four sentences

Support leadership was about to make staffing decisions from a
resolution-quality score that came entirely out of an LLM judge nobody had
ever checked against a person. I checked it: it agrees with me **88%** of the
time — but on a set where 22 of 25 replies are genuinely bad, a judge that
just says "bad" every time also scores 88%, so I report Cohen's kappa beside
it, and kappa was **0.336**. I then took four of the judge's six criteria away
from it entirely, because they were decidable by a rule and didn't need a
model, and fed the judge its own two mistakes as examples. Agreement went to
**92%** and kappa to **0.706** — and the iteration broke a case I hadn't
predicted, which turned out to be the most interesting finding of the week.

**The one-liner:** *the number leadership was about to trust was mostly the
judge guessing the majority class, and I can now prove it moved.*

---

## The six things I was meant to learn

### 1. Building a set of test cases — real questions with a way to score them

27 cases in `week6/eval_set.jsonl`, each anchored to a real trace from Week 5,
each tagged with one of the six Week-5 failure modes. Every case is a support
ticket: a real customer question plus the ticket metadata a reply has to
honour (ticket ID, tier, purchase date, refund request).

**Say:** "The questions aren't invented. Every one is a question the system
actually got, pulled from the 182 traces I logged in Week 5, and each is
tagged with the failure mode it exhibited so I can score per problem type."

### 2. Turning last week's failures into permanent tests

Three cases — `R-01`, `R-02`, `R-03` — are replayed **verbatim**. The reply
text is the model output recorded in the trace file, copied out and hashed,
never regenerated. They are frozen evidence of three Week-5 failures.

**Say:** "These three can't silently come back, because they never left. The
reply is the recorded output, hashed, and it's in the eval set forever. All
three still fail, which is correct — they're the bug, not the fix."

### 3. Cheap rule checks first, because they're free

Judge v0 scored **six criteria on a 1–10 scale**. Four of them were decidable
by reading the reply and the ticket record — no taste involved — so they're
code now (`week6/assertions.py`) and **deleted from the judge prompt**.

| check | result on 27 replies |
| --- | --- |
| ticket ID echoed | **11 FAIL** |
| refund amount is a figure | **2 FAIL** |
| escalation tag when tier is Priority | **5 FAIL** |
| no refund promised past day 30 | **7 FAIL, 0 PASS** |

**Say:** "The 30-day check is zero pass, seven fail. The drafter has no date
check at all — it promised a refund on a day-61 purchase. That's a compliance
bug, it costs nothing to catch, and the LLM judge had never flagged it in any
run. That's the argument for doing rules first."

### 4. An AI judge for the part a rule can't do

What's left after the rules take their share is one genuinely judgemental
question: **does this reply resolve the customer's problem?** A rule can't
decide whether "the correct fix is in there, buried under two fixes for errors
you never reported" counts as resolving. That's the judge's whole job now.

**Say:** "One criterion, not six. The judge only gets the thing a rule can't
decide."

### 5. Checking the judge agrees with me before trusting it

I hand-labelled 25 replies blind against the judge's single criterion and
**committed the labels before the judge had ever been run**. The commit chain
is the proof:

```
62b06f5  harness, judge prompts      <- no labels, no judge run
6b46965  labels_25.json              <- 25 hand labels
8101810  judge v1 run, agreement 88% <- FIRST judge output
7361019  prediction.txt              <- before judge_v2 existed
ab11f49  judge v2, agreement 92%
```

**Say:** "`git log --diff-filter=A -- 'week6/judge_run_*.json'` shows the first
judge output landing one commit *after* the labels. I couldn't have tuned the
labels to the judge, and the history would show it if I had."

### 6. Measuring a change before/after, per problem type

```
agreement   88.0%  ->  92.0%
kappa       0.336  ->  0.706

pass rate by mode (one command, week6/run_week6.py):
  mode_1  filter hid the answer        0/8
  mode_2  fixes nobody asked for       0/7
  mode_3  refused on wording           0/4
  mode_4  confident, off-topic         0/2
  mode_5  instruction, wrong article   1/1   <- see below
  no_failure                           2/5
  OVERALL                              3/27
```

**Say:** "Read the one green cell as a warning. mode_5 is 100% because it's a
single case, and it passes only because the judge got it wrong. A pass rate
computed from a judge inherits that judge's blind spots, which is exactly why
the agreement figure is printed directly underneath it."

---

## Topic checklist

| topic | covered | evidence |
| --- | --- | --- |
| Eval sets | yes | `eval_set.jsonl`, 27 cases, 6 modes |
| Regression tests from failures | yes | `R-01/02/03`, replayed verbatim + hashed |
| Assertion checks | yes | `assertions.py`, 4 rules, 25 failures found |
| LLM-as-judge | yes | `judge_v0/v1/v2.txt`, `judge.py` |
| **G-Eval** | **no** | see gaps below |
| Binary vs 1–10 scoring | yes | v0 was 6 criteria × 1–10; v1 is binary, with the reason written into the prompt |
| Judge validation (human agreement) | yes | 88% → 92%, kappa 0.336 → 0.706, 25 blind labels |
| RAGAS faithfulness | yes | mean 1.000 across 4 policy-backed cases |
| RAGAS answer relevancy | yes | 0.47 / 0.33 / 0.11 per case in `ragas_report.json` |
| RAGAS context precision | yes | 1.00 / 0.50 / 0.50 / 0.00 |
| **RAGAS context recall** | **no** | see gaps below |
| Before/after deltas | yes | agreement, kappa, and pass rate per mode |

### Why binary and not 1–10 — expect this question

**Say:** "I can't hand-label the difference between a 6 and a 7 twice running.
If my own labels aren't repeatable, the agreement number I measure against
them is meaningless. Binary is the widest scale I could label consistently,
and the whole point of this week was to get a trustworthy agreement number.
The reasoning is written into the top of `judge_v1.txt`, not just in my head."

### The RAGAS finding — this is the strongest thing to show

Case `C-10` scores **1.00 faithfulness and 1.00 context precision** while
quoting the policy section *"The refund window is thirty days"* into a ticket
about an expired **tax exemption certificate**.

**Say:** "Faithfulness asks 'did you make this up?' — no, the sentence really
is in a retrieved chunk. Context precision asks 'did retrieval find the right
chunks?' — yes, it did. Both metrics are satisfied and the reply is unusable,
because neither one asks 'is this the customer's question?'. And mean
faithfulness is *exactly* 1.000 across all four cases — the extractive
generator only ever emits verbatim quotes, so the metric is pinned at the
ceiling with zero variance. An average over a constant can't flag anything,
however many replies you add to it. The finding is in the per-case row or it's
nowhere."

---

## The two gaps — say these before you're asked

**G-Eval is not implemented.** G-Eval is the technique where you hand the model
the criterion, have it *generate its own evaluation steps* via chain-of-thought,
then fill in a form, and you weight the score by output token probabilities to
get a continuous score instead of a lumpy integer. My judge is a plain
form-filling judge: fixed criterion, fixed rules, one binary verdict, no
generated steps and no token-probability weighting.

**Say:** "I did LLM-as-judge but not G-Eval specifically. I went the other
direction on purpose — G-Eval exists to make 1–10 scoring less arbitrary, and
I'd already decided a scale I couldn't hand-label was the thing to get rid of.
The honest gap is that I never tried generated evaluation steps, and that's
what I'd add next."

**RAGAS context recall is not implemented.** I built faithfulness, answer
relevancy and context precision. Recall asks the opposite question to
precision: *of everything needed to answer, how much did retrieval bring back?*
It needs a ground-truth answer per question to measure against, which the eval
set doesn't carry yet.

**Say:** "Precision without recall is a half-measurement — I can see that the
chunks I retrieved were relevant, but not whether I missed one. It needs
ground-truth answers on each case, which is a half-day of labelling I haven't
done."

---

## Questions your mentor will probably ask

**"Isn't 88% already good?"**
No — and that's the main finding. 22 of my 25 labels are NOT_RESOLVED, so a
judge that answers NOT_RESOLVED blindly scores 88% without measuring anything.
Of the three replies I called RESOLVED, v1 found one. Kappa corrects for
exactly that, which is why 0.336 → 0.706 is the number I'd defend, not 88 → 92.

**"You labelled your own system's output — isn't that biased?"**
Yes, one labeller, no inter-annotator agreement, and I say so in §9 of
`results_week6.md`. What I could control, I did: labels committed before the
judge ran, written from the reply text with the envelope stripped, each with a
written reason, never revised. I also disclose that I'd written the judge's
rule executor before labelling — never run it, but it was in my head.

**"Your prediction was wrong. Doesn't that look bad?"**
The mechanism was right and the number was wrong: I said 96%, got 92%. I
predicted the two false negatives would flip — they did — and that C-19 would
stay broken — it did. What I missed is that the fix would break `C-10`, a case
I'd already banked. I only counted what the fix would repair and never asked
what else that rule was holding up. **That miss is the best thing in the
week**: at v1 the judge agreed with me on C-10 *for a completely different
reason than mine* — it objected to an error code, I objected to an internal
refund-policy sentence pasted at a customer. The agreement was a coincidence,
and my "fix" removed the coincidence while leaving the real defect untouched.
Two verdicts matching is not two verdicts matching for the same reason, and an
agreement percentage cannot see the difference.

**"What's still broken?"**
The drafter has no refund-date check (7 fails). The judge has no rule for
internal text leaking into a customer reply (C-10) and none for a correct
answer with a wrong closing instruction (C-19). And adding the policy article
to the index this week is what *caused* the leak in three replies — a defect
this week introduced and this week's own eval caught. All of it is in §9 of
`results_week6.md`, unfixed and written down.

**"Which engine ran the judge?"**
There's no `ANTHROPIC_API_KEY` in the environment, so `judge.py` fell back to
an offline executor that applies exactly the `[rule:]` tags in the prompt file.
Every number is from that engine and it says so in each `judge_run_*.json`.
The protocol and the before/after mechanics are real; the specific percentages
are about this judge, not about Claude. Nothing about the judge's behaviour
lives outside the prompt file, so v1 → v2 is genuinely a prompt experiment.

---

## Five-minute demo

1. `.venv-test/bin/python week6/run_week6.py` — one command, pass rate by mode,
   assertion counts, agreement at the bottom.
2. `git log --oneline` — the commit chain, labels before judge.
3. `diff week6/judge_v0.txt week6/judge_v1.txt` — four criteria deleted.
4. `diff week6/judge_v1.txt week6/judge_v2.txt` — the two disagreements added
   as examples, nothing else changed.
5. `.venv-test/bin/python week6/ragas_lite.py` — C-10 at 1.00 / 1.00.
6. The **Evals** tab in the UI — all 27 questions, human vs judge v1 vs judge
   v2 side by side, filtered to "judge disagrees with human".
