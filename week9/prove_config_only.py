"""Requirements 1-3: add server two with config only, and prove it.

    .venv/bin/python week9/prove_config_only.py

What it does, in a throwaway git repository so the diff is a real git diff:

  commit 1  "server one"         week9/agent/ + mcp_config.json listing only
                                 the RAG server (config/mcp_config.server_one.json)
  run 1     the agent, executed FROM THAT COMMIT'S FILES, lists its tools
  commit 2  "server one + two"   only mcp_config.json changes (the shipped one)
  run 2     the same agent files list tools again and answer a ticket query,
            which must call a ticket-history tool

Outputs (week9/evidence/):
  agent_diff.txt      git diff commit1..commit2 -- week9/agent  (must be empty)
                      plus sha256 of every agent file in both commits and in
                      this working tree, so the proof covers the shipped code
  config_diff.txt     git diff commit1..commit2 -- week9/mcp_config.json
  tool_counts.txt     N before -> M after, names from tools/list
  trace_server_two.json  run 2's discovery and tool-call trace
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runtime  # noqa: E402

QUERY = "What is going on with ticket TCK-4403, and what does the help centre say about it?"


def git(repo: str, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "week9", "GIT_AUTHOR_EMAIL": "week9@local",
           "GIT_COMMITTER_NAME": "week9", "GIT_COMMITTER_EMAIL": "week9@local"}
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                          text=True, env=env).stdout


def hashes(base: str) -> dict[str, str]:
    out = {}
    for p in sorted(glob.glob(os.path.join(base, "week9", "agent", "*.py"))):
        out[os.path.relpath(p, base)] = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    return out


def run_agent(repo: str, json_out: str, question: str | None) -> dict:
    """Run the agent package that lives in `repo` (not the working tree)."""
    cmd = [sys.executable, "-m", "week9.agent.cli", "--config",
           os.path.join(repo, "week9", "mcp_config.json"), "--json", json_out]
    if question:
        cmd.insert(3, question)
    env = {**os.environ, "PYTHONPATH": repo, "HELP_CENTRE_ROOT": runtime.ROOT,
           "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run(cmd, check=True, cwd=repo, env=env, capture_output=True, text=True)
    with open(json_out) as fh:
        return json.load(fh)


def main() -> None:
    os.makedirs(runtime.EVIDENCE, exist_ok=True)
    repo = tempfile.mkdtemp(prefix="week9-proof-")
    try:
        git(repo, "init", "-q")
        with open(os.path.join(repo, ".gitignore"), "w") as fh:
            fh.write("__pycache__/\n*.pyc\n/before.json\n/after.json\n")
        shutil.copytree(os.path.join(HERE, "agent"), os.path.join(repo, "week9", "agent"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(HERE, "config", "mcp_config.server_one.json"),
                    os.path.join(repo, "week9", "mcp_config.json"))
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "server one: help-centre-rag only")
        c1 = git(repo, "rev-parse", "--short", "HEAD").strip()
        h1 = hashes(repo)

        with runtime.ticket_server():
            before = run_agent(repo, os.path.join(repo, "before.json"), None)["discovery"]

            shutil.copy(os.path.join(HERE, "mcp_config.json"),
                        os.path.join(repo, "week9", "mcp_config.json"))
            git(repo, "add", "week9")
            git(repo, "commit", "-qm", "server one + two: add ticket-history (config only)")
            c2 = git(repo, "rev-parse", "--short", "HEAD").strip()
            h2 = hashes(repo)
            after = run_agent(repo, os.path.join(repo, "after.json"), QUERY)

        agent_diff = git(repo, "diff", c1, c2, "--", "week9/agent")
        numstat = git(repo, "diff", "--numstat", c1, c2, "--", "week9/agent")
        stat_all = git(repo, "diff", "--stat", c1, c2)
        config_diff = git(repo, "diff", c1, c2, "--", "week9/mcp_config.json")
        log = git(repo, "log", "--oneline")
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    tree = hashes(runtime.ROOT)
    changed = sum(int(a) + int(d) for a, d, _ in (l.split("\t") for l in numstat.splitlines()))
    same_as_tree = h1 == h2 == {k: v for k, v in tree.items() if k in h1} and set(h1) == set(tree)
    lines = [
        "# Agent module diff: server one -> server one + two",
        f"# $ git diff {c1} {c2} -- week9/agent",
        "# ---- output (empty means zero lines changed) ----",
        agent_diff.rstrip(),
        "# ---- end of output ----",
        f"# changed lines in week9/agent: {changed}",
        f"# whole-commit stat (everything that DID change):\n#   " + stat_all.strip().replace("\n", "\n#   "),
        "#",
        "# git log:",
        *("#   " + l for l in log.strip().splitlines()),
        "#",
        "# sha256[:16] of every agent file  (commit1 | commit2 | this working tree)",
        *(f"#   {k:28} {h1[k]} | {h2.get(k)} | {tree.get(k)}" for k in h1),
        f"# agent files identical across both commits and the shipped tree: {same_as_tree}",
    ]
    with open(os.path.join(runtime.EVIDENCE, "agent_diff.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(runtime.EVIDENCE, "config_diff.txt"), "w") as fh:
        fh.write(f"# $ git diff {c1} {c2} -- week9/mcp_config.json\n" + config_diff)

    def names(d):
        return [t["name"] for s in d["servers"].values() for t in s["tools"]]

    b, a = names(before), names(after["discovery"])
    by_server = {n: [t["name"] for t in s["tools"]] for n, s in after["discovery"]["servers"].items()}
    counts = [f"{len(b)} before -> {len(a)} after",
              f"before ({len(b)}): " + ", ".join(b),
              f"after  ({len(a)}): " + ", ".join(a),
              *(f"  {srv}: {', '.join(ts)}" for srv, ts in by_server.items()),
              "source: tools/list responses received by week9/agent/host.py at connect time"]
    with open(os.path.join(runtime.EVIDENCE, "tool_counts.txt"), "w") as fh:
        fh.write("\n".join(counts) + "\n")

    run = after["run"]
    calls = [s for s in run["steps"] if s["kind"] == "tool"]
    trace = {"query": QUERY, "config": "week9/mcp_config.json (commit 2)",
             "tool_calls": [{"tool": s["qualified"], "server": s["server"], "args": s["args"],
                             "is_error": s["is_error"], "ms": s["ms"]} for s in calls],
             "attached_context": [c["uri"] for c in run["context"]],
             "answer": run["final"]["answer"], "model": run["steps"][0]["model"],
             "discovery": after["discovery"]}
    with open(os.path.join(runtime.EVIDENCE, "trace_server_two.json"), "w") as fh:
        json.dump(trace, fh, indent=1)

    two = [c["tool"] for c in trace["tool_calls"] if c["server"] == "ticket-history"]
    print(open(os.path.join(runtime.EVIDENCE, "tool_counts.txt")).read())
    print(f"agent lines changed: {changed}   identical to working tree: {same_as_tree}")
    print(f"server-two tools called: {two}")
    if changed or not two:
        sys.exit("PROOF FAILED")


if __name__ == "__main__":
    main()
