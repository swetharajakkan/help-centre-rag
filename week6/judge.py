"""Run a judge prompt over the drafted replies.

Two engines, one prompt file:

  anthropic  ANTHROPIC_API_KEY is set. The prompt file is the system prompt,
             the ticket and reply are the user turn, and the model returns the
             verdict. This is the judge as leadership's number is described.

  offline    No key. The executor reads the [rule: ...] tags in the prompt file
             and applies exactly those rules. It is a shallow reader -- it
             decides from surface features of the reply, the way a cheap judge
             does -- and it is deliberately not allowed to know anything the
             prompt file does not say. Editing the prompt is the only way to
             change what it does, which is what makes the v1 -> v2 comparison
             a prompt experiment rather than a code experiment.

Whichever engine ran is written into the output file. The agreement numbers
are numbers about that engine.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

MODEL = "claude-opus-5"
CODE = re.compile(r"ERR-\d{4}")


# ---------------------------------------------------------------- prompt I/O

def parse_prompt(text: str) -> dict:
    """Pull the rule tags and the few-shot examples out of a judge prompt."""
    rules = set(re.findall(r"\[rule:\s*([a-z_]+)\s*\]", text))
    examples = []
    for block in re.findall(r"\[example:(.*?)\](.*?)(?=\n\[example:|\nRULE TAGS|\Z)",
                            text, re.S):
        head, body = block
        lesson = re.search(r"\[lesson:\s*([a-z_]+)\s*\]", body)
        examples.append({"case": head.strip(),
                         "lesson": lesson.group(1) if lesson else None})
    return {"rules": rules, "examples": examples,
            "lessons": {e["lesson"] for e in examples if e["lesson"]}}


# ------------------------------------------------------------ offline engine

def _reply_body(reply: str) -> str:
    """The substantive part: everything between the greeting and the sign-off.
    The envelope lines are assertion territory and are not judged."""
    body = reply.split("Best regards,")[0]
    body = "\n".join(l for l in body.splitlines()
                     if not l.startswith("Hi,") and l.strip() != "[ESCALATED]")
    return body


def offline_verdict(reply: str, ticket: str, spec: dict,
                    question: str) -> tuple[str, str]:
    body = _reply_body(reply)
    asked = set(CODE.findall(question))
    present = set(CODE.findall(body))

    if "declines" in spec["rules"] and (
            "could not find documentation" in body
            or "do not cover" in body.lower()):
        return "NOT_RESOLVED", "the reply declines to answer [rule: declines]"

    if "different_question" in spec["rules"] and asked and not (asked & present):
        return ("NOT_RESOLVED",
                f"the customer named {sorted(asked)} and the reply addresses "
                f"{sorted(present) or 'no code'} [rule: different_question]")

    extra = present - asked
    if "unrequested_codes" in spec["rules"] and extra:
        # v2 lesson: when the customer described the fault in words instead of
        # quoting the code, the code whose documented description matches that
        # wording IS the customer's code, not an extra.
        if "symptom_match" in spec["lessons"] and not asked:
            matched = _symptom_matched_codes(question, body)
            extra = extra - matched
        if extra:
            return ("NOT_RESOLVED",
                    f"the reply gives fixes for {sorted(extra)}, which the "
                    f"customer did not report [rule: unrequested_codes]")

    return "RESOLVED", "the reply gives the fix for the reported problem"


STOP = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "to", "of",
        "in", "on", "for", "that", "this", "what", "how", "do", "does", "i",
        "we", "it", "has", "have", "with", "not", "no", "but", "be", "been",
        "correct", "fix", "client", "customer", "case", "hit", "should",
        "mean", "means", "work", "works", "seeing", "asking", "please"}


def _symptom_matched_codes(question: str, body: str) -> set[str]:
    """Codes whose documented description overlaps the words the customer used.

    Only reachable when the v2 prompt carries the symptom_match lesson.
    """
    qwords = {w for w in re.findall(r"[a-z]{3,}", question.lower())
              if w not in STOP}
    matched = set()
    for line in body.splitlines():
        codes = CODE.findall(line)
        if not codes:
            continue
        lwords = {w for w in re.findall(r"[a-z]{3,}", line.lower())
                  if w not in STOP}
        if qwords and len(qwords & lwords) / len(qwords) >= 0.5:
            matched.update(codes)
    return matched


# ---------------------------------------------------------- anthropic engine

def anthropic_verdict(prompt: str, ticket: dict, reply: str) -> tuple[str, str]:
    import anthropic

    user = (f"TICKET {ticket['ticket_id']} (tier {ticket['tier']})\n"
            f"product area: {ticket['product_area']}\n"
            f"question: {ticket['question']}\n\n"
            f"DRAFTED REPLY\n{reply}")
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=300, temperature=0,
        system=prompt, messages=[{"role": "user", "content": user}])
    out = json.loads(re.search(r"\{.*\}", msg.content[0].text, re.S).group(0))
    return out["verdict"], out.get("reasoning", "")


# ------------------------------------------------------------------- driver

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    prompt_text = open(args.prompt).read()
    spec = parse_prompt(prompt_text)
    engine = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "offline"

    replies = [json.loads(l) for l in
               open(os.path.join(HERE, "replies.jsonl")) if l.strip()]
    cases = {json.loads(l)["case_id"]: json.loads(l) for l in
             open(os.path.join(HERE, "eval_set.jsonl")) if l.strip()}

    out = {
        "prompt_file": os.path.basename(args.prompt),
        "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest()[:16],
        "engine": engine,
        "model": MODEL if engine == "anthropic" else "offline-rule-executor",
        "rules_active": sorted(spec["rules"]),
        "few_shot_examples": [e["case"] for e in spec["examples"]],
        "lessons_active": sorted(spec["lessons"]),
        "verdicts": {},
    }

    for r in replies:
        if not cases[r["case_id"]]["judged"]:
            continue
        t = r["ticket"]
        if engine == "anthropic":
            verdict, why = anthropic_verdict(prompt_text, t, r["reply"])
        else:
            verdict, why = offline_verdict(r["reply"], t["ticket_id"], spec,
                                           t["question"])
        out["verdicts"][r["case_id"]] = {"verdict": verdict, "reasoning": why,
                                         "mode": r["mode"]}

    json.dump(out, open(args.out, "w"), indent=1)
    n_res = sum(v["verdict"] == "RESOLVED" for v in out["verdicts"].values())
    print(f"judge {out['prompt_file']} (engine={engine}, "
          f"rules={','.join(out['rules_active'])})")
    print(f"  {len(out['verdicts'])} cases judged: "
          f"{n_res} RESOLVED / {len(out['verdicts']) - n_res} NOT_RESOLVED")
    print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
