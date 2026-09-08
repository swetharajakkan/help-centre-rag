import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
rows = {json.loads(l)["trace_id"]: json.loads(l)
        for l in open(os.path.join(HERE, "traces.jsonl")) if l.strip()}
for tid in sys.argv[1:]:
    t = rows[tid]
    r, g, res = t["request"], t["grounding"], t["result"]
    print("=" * 78)
    print(f"{tid}   template={t['template']}   k={r['k']} mode={r['mode']} "
          f"area={r['product_area']} rerank={r['rerank_resolved']}")
    print(f"Q: {t['question']}")
    print(f"grounding coverage={g['in_corpus_coverage'] if g else None} "
          f"uncovered={(g['uncovered_anchors'][:6] if g else None)}")
    if g and g["gate_refusal"]:
        print(f"GATE REFUSAL: {g['gate_refusal']}")
    print("retrieved:")
    for h in t["retrieval"]["hits"]:
        print(f"  #{h['rank']} {h['article_id']} [{h['section']}] "
              f"fused={h['score']} rr={h['rerank_score']} upd={h['last_updated']}")
        print(f"      {h['chunk_id'].split('::')[-1]}")
    print(f"ANSWERED: {res['answered']}")
    for c in res.get("claims", []):
        print(f"  CLAIM [{c['article_id']} / {c['section']}]")
        print(f"    {c['claim']}")
    if not res["answered"]:
        print(f"  REFUSAL: {res['refusal']}")
    if res.get("rejected_claims"):
        print(f"  REJECTED: {len(res['rejected_claims'])}")
