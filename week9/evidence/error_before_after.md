# Same failing call, before and after the rewrite

Server: `help-centre-rag` (ours) · tool: `get_article` · model: `offline-mcp-planner` · agent module unchanged between runs; the only switch is `HELP_CENTRE_RAG_ERRORS` in the server's config entry.

| | before | after |
|---|---|---|
| error text | `Error 3` | ids look like BM-nnn, known ids, what to call |
| model turns | 4 | 3 |
| tool calls (failed) | 3 (3) | 2 (1) |
| tokens | 3,081 | 3,813 |
| answered the user | False | True |

> Engine note: no ANTHROPIC_API_KEY on this checkout, so the model is the offline planner in `week9/agent/model.py`. It re-plans only from the error text it is handed (an id shape, a named tool, a do-not-retry phrase) and resends an opaque error up to 3 times. Set a key and rerun this script to get the same transcript from claude-opus-5-5.

## The docstring rewrite

```diff
--- get_article docstring (before)
+++ get_article docstring (after)
@@ -1 +1,17 @@
-Get article.
+Fetch the full text of ONE help-centre article by its article id.
+
+Use this when you already hold an article id -- from the user's message, or
+from the article_id field of a search_help_centre hit -- and need the whole
+article rather than a chunk of it. If you only have a topic or a question,
+call search_help_centre instead; never guess an id.
+
+article_id: "BM-" followed by exactly three digits, e.g. "BM-004". A user who
+writes "BM-4" or "bm 4" means "BM-004".
+
+Returns article_id, title, product_area, last_updated and text (markdown).
+Quote from text when you cite it; text is exactly what the user would read.
+
+Errors are recoverable and say which case they are:
+  - "not found ... ids look like BM-nnn": reformat the id and call again once.
+  - "no article ... call search_help_centre": the id is well-formed but does
+    not exist; search by topic instead of retrying.
```

## Before — `Error 3`

Docstring the model saw (from tools/list):

```text
Get article.
```

**User:** Open help article BM-4 and tell me what it says about proration.

1. **model** → tools/call `help-centre-rag__get_article({"article_id": "BM-4"})`
   - tool_result (**isError: true**): `Error 3`
2. **model** → tools/call `help-centre-rag__get_article({"article_id": "BM-4"})`
   - tool_result (**isError: true**): `Error 3`
3. **model** → tools/call `help-centre-rag__get_article({"article_id": "BM-4"})`
   - tool_result (**isError: true**): `Error 3`
4. **model** → final answer: I can't answer that from the connected sources: get_article({"article_id": "BM-4"}) failed: Error 3.

Model turns **4** · tool calls **3** (3 failed) · tokens 3,081 · answered: **False**

## After — recoverable error

Docstring the model saw (from tools/list):

```text
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
```

**User:** Open help article BM-4 and tell me what it says about proration.

1. **model** → tools/call `help-centre-rag__get_article({"article_id": "BM-4"})`
   - tool_result (**isError: true**): `article 'BM-4' not found: ids look like BM-nnn (BM- then three digits, e.g. BM-004). Known ids: BM-001, BM-002, BM-003, BM-004, BM-005, BM-006. Reformat the id and call get_article again.`
2. **model** → tools/call `help-centre-rag__get_article({"article_id": "BM-004"})`
   - tool_result (ok): `{"article_id":"BM-004","title":"Subscription and Proration Behaviour After Migration","product_area":"subscriptions","last_updated":"2026-07-28","source_file":"…`
3. **model** → final answer: BM-004 “Subscription and Proration Behaviour After Migration”: Ledger v1 prorated subscription changes to the nearest whole day. [BM-004]

Model turns **3** · tool calls **2** (1 failed) · tokens 3,813 · answered: **True**

