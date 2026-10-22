"""The triage squad in AutoGen (autogen-agentchat 0.4+): same roles and tool.

    pip install "autogen-agentchat" "autogen-ext[anthropic]"
    ANTHROPIC_API_KEY=... .venv/bin/python -m week10.frameworks.autogen_squad C-02

AutoGen's model: agents exchange messages in a team. SelectorGroupChat lets
a model pick the next speaker from the agents' descriptions every turn, and
every agent sees the whole shared thread -- which is the context re-send
cost made structural: each turn re-reads everything said so far. Not run on
this checkout (no API key, package not installed).
"""
from __future__ import annotations

import asyncio
import json
import sys

from week10 import race


def build(index):
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import SelectorGroupChat
    from autogen_ext.models.anthropic import AnthropicChatCompletionClient

    async def search_help_centre(query: str, product_area: str = "") -> str:
        """Search the billing-migration help centre; returns the top 3 chunks."""
        _, chunks = race._search(index, {"question": query, "product_area": product_area or None})
        return json.dumps(chunks)

    client = AnthropicChatCompletionClient(model=race.PRICED_AS)
    orchestrator = AssistantAgent(
        "orchestrator", model_client=client,
        description="Owns the ticket; writes the final reply.",
        system_message=race.SYS_ORCH + " When the reply is final, end with TERMINATE.")
    triage = AssistantAgent("triage", model_client=client,
                            description="Extracts error codes, priority, refund window.",
                            system_message=race.SYS_TRIAGE)
    policy = AssistantAgent("policy_lookup", model_client=client, tools=[search_help_centre],
                            description="Finds the help-centre fix and applies SP-001.",
                            system_message=race.SYS_POLICY + "\n\n" + race.POLICY_TEXT)
    stop = TextMentionTermination("TERMINATE") | MaxMessageTermination(8)
    return SelectorGroupChat([orchestrator, triage, policy], model_client=client,
                             termination_condition=stop)


async def run(case_id: str) -> None:
    case = {c["case_id"]: c for c in race.load_cases()}[case_id]
    team = build(race.D.build_index_with_policy())
    result = await team.run(task=json.dumps(case["ticket"]))
    for m in result.messages:
        print(f"[{m.source}] {getattr(m, 'content', '')}"[:400])
        if getattr(m, "models_usage", None):
            print("   usage:", m.models_usage)


def main(case_id: str = "C-02") -> None:
    try:
        import autogen_agentchat  # noqa: F401
    except ImportError:
        sys.exit('autogen is not installed: pip install "autogen-agentchat" "autogen-ext[anthropic]"')
    asyncio.run(run(case_id))


if __name__ == "__main__":
    main(*sys.argv[1:])
