"""Server one: the help-centre RAG index as an MCP server (ours).

Same index the FastAPI app serves (backend/app: structure_aware chunks, frozen
bge-small + BM25 scorer, Week 4 reranker when HELP_CENTRE_RERANK=1), exposed
over MCP so any host can discover and call it. Run over stdio -- the host
spawns it as a child process and owns its lifetime:

    .venv/bin/python week9/servers/rag_server.py            # stdio
    .venv/bin/python week9/servers/rag_server.py --http 8764

Primitives:

  tool      search_help_centre(query, k, product_area)   model-invoked search
  tool      get_article(article_id)                      model-invoked fetch
  resource  kb://articles                                 catalog, app-attached
  resource  kb://articles/{article_id}                    one article as text
  prompt    grounded_answer(question)                     user-picked template

The Task Set A rewrite (requirement 5) is get_article. Its old docstring was
two words and its not-found path said "Error 3", which a model cannot act on:
it cannot tell a malformed id from a missing article from a dead server, so
it resends the same call. The new docstring is written as a prompt -- when to
use it, the id shape, what comes back, what each failure means -- and the
not-found error names the id shape, the ids that exist, and the tool to call
instead. HELP_CENTRE_RAG_ERRORS=legacy serves the old text and the old error
so error_demo.py can run the same failing call against both.

No model runs in here: search and fetch only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# The scorer resolves its model cache relative to the working directory.
os.chdir(ROOT)

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ResourceError, ToolError  # noqa: E402

from backend.app.ingest import build_index, load_articles  # noqa: E402

LEGACY = os.environ.get("HELP_CENTRE_RAG_ERRORS") == "legacy"

# ---- requirement 5: the one docstring rewritten as a prompt ----------------

GET_ARTICLE_DOC_BEFORE = "Get article."

GET_ARTICLE_DOC_AFTER = """\
Fetch the full text of ONE help-centre article by its article id.

Use this when you already hold an article id -- from the user's message, or
from the article_id field of a search_help_centre hit -- and need the whole
article rather than a chunk of it. If you only have a topic or a question,
call search_help_centre instead; never guess an id.

article_id: "BM-" followed by exactly three digits, e.g. "BM-004". A user who
writes "BM-4" or "bm 4" means "BM-004".

Returns article_id, title, product_area, last_updated and text (markdown).
Quote from text when you cite it; text is exactly what the user would read.

Errors are recoverable and say which case they are:
  - "not found ... ids look like BM-nnn": reformat the id and call again once.
  - "no article ... call search_help_centre": the id is well-formed but does
    not exist; search by topic instead of retrying.
"""

ID_SHAPE = re.compile(r"^BM-\d{3}$")

_index = None


def index():
    """Built on first use, not at import: the host's initialize handshake
    returns immediately and the embedder loads on the first search."""
    global _index
    if _index is None:
        _index = build_index("structure_aware")
    return _index


def _articles() -> dict[str, dict]:
    out = {}
    for source_file, front, body in load_articles():
        out[front["article_id"]] = {
            "article_id": front["article_id"], "title": front.get("title", ""),
            "product_area": front.get("product_area", ""),
            "last_updated": str(front.get("last_updated", "")),
            "source_file": source_file, "text": body}
    return out


ARTICLES = _articles()

mcp = FastMCP(
    name="help-centre-rag",
    version="9.0.0",
    instructions=("Billing-migration help-centre knowledge base. Search it "
                  "with search_help_centre; fetch whole articles (BM-nnn) "
                  "with get_article. Every hit carries the chunk_id and "
                  "article_id to cite."),
)


@mcp.tool(annotations={"readOnlyHint": True})
def search_help_centre(query: str, k: int = 3, product_area: str | None = None) -> dict:
    """Search the billing-migration help centre and return the k best chunks.

    Use this for any question about the billing migration (phases, cutover,
    payment methods, invoices, proration, tax ids, API and webhooks) and to
    ground an answer about a support ticket in policy. Pass the user's
    question, or a ticket's subject, as `query` in plain words.

    k: 1-10, default 3. product_area: optional exact filter, one of
    billing, payments, invoicing, subscriptions, tax-compliance,
    developer-api.

    Each hit has chunk_id, article_id, title, score, relevance and text.
    Cite chunk_id and quote text verbatim. relevance is "weak" when the
    reranker scores the chunk as unrelated to the query: treat weak hits, or
    an empty `hits` list, as "the help centre does not cover this" and say so
    rather than answering from memory.
    """
    k = max(1, min(int(k), 10))
    where = {"product_area": product_area} if product_area else None
    hits = index().search(query, k=k, where=where)
    return {"query": query, "product_area": product_area, "hits": [
        {"rank": h["rank"], "chunk_id": h["chunk_id"],
         "article_id": h["meta"].get("article_id"), "title": h["meta"].get("title"),
         "score": h.get("rerank_score", h["score"]), "relevance": _relevance(h),
         "text": h["text"]}
        for h in hits]}


# Cross-encoder logit below which a chunk is unrelated to the query. Measured
# on this corpus: in-scope questions top out at -1.0 or above, off-corpus ones
# ("password reset", "hardware returns") at -1.88 or below. The fused Week 3
# score is min-max normalised per query, so it carries no absolute signal.
WEAK_BELOW = -1.5


def _relevance(hit: dict) -> str:
    if "rerank_score" not in hit:
        return "unknown"
    return "weak" if hit["rerank_score"] < WEAK_BELOW else "strong"


def get_article(article_id: str) -> dict:
    aid = (article_id or "").strip()
    if aid in ARTICLES:
        return dict(ARTICLES[aid])
    if LEGACY:
        # The pre-rewrite error path, kept only so the before/after demo can
        # replay it. This is what "swallowing the not-found case" looks like.
        raise ToolError("Error 3")
    known = ", ".join(sorted(ARTICLES))
    if not ID_SHAPE.match(aid.upper()):
        raise ToolError(
            f"article {article_id!r} not found: ids look like BM-nnn (BM- then "
            f"three digits, e.g. BM-004). Known ids: {known}. Reformat the id "
            "and call get_article again.")
    raise ToolError(
        f"no article {aid}: the id is well-formed but does not exist (known "
        f"ids: {known}). Call search_help_centre with the topic instead of "
        "retrying this id.")


mcp.tool(get_article, description=GET_ARTICLE_DOC_BEFORE if LEGACY else GET_ARTICLE_DOC_AFTER,
         annotations={"readOnlyHint": True})


@mcp.resource("kb://articles", mime_type="application/json",
              description="Catalog of every article: id, title, product area, "
                          "last updated. For the host to attach, not to call.")
def catalog() -> str:
    return json.dumps([{k: a[k] for k in ("article_id", "title", "product_area",
                                          "last_updated")}
                       for a in ARTICLES.values()], indent=1)


@mcp.resource("kb://articles/{article_id}", mime_type="text/markdown",
              description="One article's markdown, by id (BM-nnn).")
def article_resource(article_id: str) -> str:
    if article_id not in ARTICLES:
        raise ResourceError(f"no article {article_id}; known ids: "
                            + ", ".join(sorted(ARTICLES)))
    return ARTICLES[article_id]["text"]


@mcp.prompt
def grounded_answer(question: str) -> str:
    """Answer a customer question from the help centre, citing chunks."""
    return (f"Answer this customer question using only search_help_centre "
            f"results. Cite every claim with its chunk_id and quote the text "
            f"that supports it verbatim. If nothing relevant comes back, say "
            f"the help centre does not cover it.\n\nQuestion: {question}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=None, metavar="PORT")
    a = ap.parse_args()
    if a.http:
        mcp.run(transport="http", host="127.0.0.1", port=a.http, path="/mcp",
                show_banner=False)
    else:
        mcp.run(transport="stdio", show_banner=False)
