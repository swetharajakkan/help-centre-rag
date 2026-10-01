"""mem0: the same long-term memory as memory.py, from a library.

    .venv/bin/python week7/mem0_demo.py write     # process 1: store memories
    .venv/bin/python week7/mem0_demo.py recall    # process 2: a fresh process
    .venv/bin/python week7/mem0_demo.py reset     # delete week7/.mem0/

memory.py hand-builds a vector memory in 40 lines. mem0 is that, packaged:
an embedder, a vector store, scoping by user_id, metadata, a change history
per memory, and (with an LLM) fact extraction and de-duplication on add.

Configuration here, all local, no API key:
  embedder      fastembed BAAI/bge-small-en-v1.5 (the model the RAG backend uses)
  vector store  Qdrant in embedded mode on disk, week7/.mem0/qdrant
  history       SQLite, week7/.mem0/history.db
  infer=False   memories are stored verbatim. With infer=True mem0 first asks
                an LLM to extract facts ("tier is priority") and decides
                ADD / UPDATE / DELETE against what it already holds -- that
                needs a model key, and it is also where a code like
                MGR-AUTH-8821 can be paraphrased away, the same failure as
                the rolling summary.

`write` and `recall` are separate commands on purpose: run them as two
processes and the recall proves the memory outlived the process.
"""
from __future__ import annotations

import os
import shutil
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

os.environ.setdefault("MEM0_TELEMETRY", "False")
warnings.filterwarnings("ignore", category=UserWarning)
os.environ.setdefault("FASTEMBED_CACHE_PATH", os.path.join(ROOT, ".fastembed_cache"))

from bonus import LONG_THREADS  # noqa: E402

DATA = os.path.join(HERE, ".mem0")
CONFIG = {
    "embedder": {"provider": "fastembed",
                 "config": {"model": "BAAI/bge-small-en-v1.5",
                            "embedding_dims": 384}},
    "vector_store": {"provider": "qdrant",
                     "config": {"collection_name": "support_memory",
                                "path": os.path.join(DATA, "qdrant"),
                                "embedding_model_dims": 384,
                                "on_disk": True}},
    # Constructed but never called: every add below uses infer=False.
    "llm": {"provider": "anthropic",
            "config": {"model": "claude-sonnet-5",
                       "api_key": os.environ.get("ANTHROPIC_API_KEY", "unused")}},
    "history_db_path": os.path.join(DATA, "history.db"),
}


def memory():
    import logging
    logging.disable(logging.WARNING)  # mem0 warns that spaCy is not installed
    from mem0 import Memory
    return Memory.from_config(CONFIG)


def write() -> None:
    m = memory()
    for tid, th in LONG_THREADS.items():
        user = th["customer_id"]
        # A fact, tagged so it can be filtered on later.
        m.add(f"Customer {user} is on the {th['customer_tier']} tier.",
              user_id=user, metadata={"kind": "tier"}, infer=False)
        # Every customer turn, verbatim.
        turns = [t for r, t in th["turns"] if r == "user"]
        for t in turns:
            m.add(t, user_id=user, metadata={"kind": "turn", "ticket": tid},
                  infer=False)
        print(f"{tid}  {user}: stored tier + {len(turns)} turns")
    print(f"\nwritten to {DATA}. Now run:  week7/mem0_demo.py recall")


def recall() -> None:
    if not os.path.exists(DATA):
        sys.exit("nothing stored yet: run `week7/mem0_demo.py write` first")
    m = memory()
    print(f"fresh process (pid {os.getpid()}), reading {DATA}\n")

    for tid, th in LONG_THREADS.items():
        user = th["customer_id"]
        tier = m.search("what tier is this customer on",
                        filters={"user_id": user, "kind": "tier"}, top_k=1)
        print(f"{tid}  {user}  tier memory: "
              f"{tier['results'][0]['memory'] if tier['results'] else '-'}")

    th = LONG_THREADS["TCK-LONG-03"]
    q = (f"manager authorization or waiver code approving the refund on "
         f"{th['order_id']} without escalation")
    print(f"\nsearch(user_id={th['customer_id']}): {q!r}")
    for r in m.search(q, filters={"user_id": th["customer_id"]},
                      top_k=3)["results"]:
        print(f"  {r['score']:.3f}  {r['memory'][:95]}")

    # Scoping: the same question for a different customer must not see it.
    other = m.search(q, filters={"user_id": "CUST-901"}, top_k=3)["results"]
    leaked = any("MGR-AUTH" in r["memory"] for r in other)
    print(f"\nsame query as CUST-901 returns the waiver? {leaked}")

    n = len(m.get_all(filters={"user_id": th["customer_id"]})["results"])
    print(f"memories held for {th['customer_id']}: {n}")


def main() -> None:
    cmd = (sys.argv[1:] or ["recall"])[0]
    if cmd == "reset":
        shutil.rmtree(DATA, ignore_errors=True)
        print("deleted", DATA)
    elif cmd == "write":
        write()
    elif cmd == "recall":
        recall()
    else:
        sys.exit("usage: mem0_demo.py write | recall | reset")


if __name__ == "__main__":
    main()
