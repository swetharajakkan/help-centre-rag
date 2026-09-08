# Week 5 prediction — written 2026-09-07, to be tested by 2026-09-14

Written after open-coding 20 randomly sampled traces and **before any fix
exists**. Nothing in `backend/` has been touched. `git log` shows this commit
landing before any change to the assistant.

## The one mode I will attack

**"Tells the agent the answer isn't documented, when the product-area filter
is what hid it."** 7 of the 20 sampled traces (35%). Example: `T-0090`.

## The specific change

1. In `backend/app/store.py`, when `Index.search` is called with a `where`
   filter and the resulting answer is a refusal, re-run the search once with
   `where=None` and answer from the unfiltered result.
2. In `backend/app/generation.py`, change the two refusal strings so that
   neither says "The indexed articles do not cover this" while a filter was
   active. The refusal must name the filter instead.

Nothing else changes: no chunker, no embedding model, no fusion weight, no
reranker, no `GROUNDING_FLOOR`, no `MAX_CLAIMS`.

## The numbers I expect to move

Metric `M1`, computed by `week5/metric.py`, is mechanical: of the traces whose
question names an `ERR-` code that is written in the corpus, the fraction the
assistant refused. No labelling, no judgement.

| Measurement | Baseline (2026-09-07) | Predicted after the change |
| --- | --- | --- |
| Refusal rate, filtered questions naming a documented code | **88.5% (23/26)** | **under 35% (≤9/26)** |
| `M1` overall, all 182 traces | **47.4% (37/78)** | **under 32% (≤25/78)** |
| This mode's share of a fresh seeded sample of 20 | **35% (7/20)** | **under 15% (≤3/20)** |

Point estimate for `M1`: **26.9%**, which is the rate unfiltered questions
already achieve (14/52). The change cannot beat that, because all it does is
make a filtered question behave like an unfiltered one. If `M1` lands below
25% the prediction was wrong in the optimistic direction and something other
than the filter also moved.

## Guards, so I cannot win by breaking refusals

A change that simply stops refusing would move every number above. These must
all still hold afterwards:

- Out-of-scope questions (`template=out_of_scope`, n=13) still refuse at
  **≥ 8/13**, the current rate.
- Total refusals across the 182 traces stay **≥ 40** (currently 67; the fix
  should remove roughly 20, not 60).
- The padding mode ("prints fixes for error codes the customer never
  reported") stays **≤ 30%** on the fresh sample of 20 (currently 25%).

## How it gets falsified

Re-run `week5/run_traces.py` over the same frozen `population.jsonl`, then
`week5/metric.py`. Same questions, same seed, same corpus hash. If the filtered
refusal rate is still above 35%, or any guard fails, this prediction was wrong
and it says so in the numbers rather than in a paragraph.
