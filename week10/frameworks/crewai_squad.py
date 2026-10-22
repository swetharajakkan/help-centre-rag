"""The triage squad in CrewAI: same roles, same prompts, same search tool.

    pip install crewai            # not in requirements.txt on purpose
    ANTHROPIC_API_KEY=... .venv/bin/python -m week10.frameworks.crewai_squad C-02

CrewAI's model: Agents (role/goal/backstory + tools) do Tasks inside a Crew.
Process.hierarchical adds a manager agent that decides which worker gets
which piece -- the orchestrator-worker pattern, with the routing done by an
LLM instead of by our code. Not run on this checkout: there is no API key and
CrewAI is not installed, so it has no numbers in the race.
"""
from __future__ import annotations

import json
import sys

from week10 import race


def build(index):
    from crewai import LLM, Agent, Crew, Process, Task
    from crewai.tools import tool

    @tool("search_help_centre")
    def search_help_centre(query: str, product_area: str = "") -> str:
        """Search the billing-migration help centre; returns the top 3 chunks."""
        _, chunks = race._search(index, {"question": query, "product_area": product_area or None})
        return json.dumps(chunks)

    llm = LLM(model=f"anthropic/{race.PRICED_AS}", temperature=0)
    orchestrator = Agent(role="Support orchestrator", goal=race.SYS_ORCH,
                         backstory="Owns the ticket; delegates and synthesises.",
                         llm=llm, allow_delegation=True)
    triage = Agent(role="Triage worker", goal=race.SYS_TRIAGE,
                   backstory="Reads ticket fields only.", llm=llm, tools=[],
                   allow_delegation=False)
    policy = Agent(role="Policy-lookup worker", goal=race.SYS_POLICY,
                   backstory=f"Applies this policy:\n{race.POLICY_TEXT}", llm=llm,
                   tools=[search_help_centre], allow_delegation=False)
    task = Task(description="Draft the reply for this support ticket: {ticket}",
                expected_output='JSON {"answered": bool, "claims": [...], "refusal": str}')
    return Crew(agents=[triage, policy], tasks=[task], process=Process.hierarchical,
                manager_agent=orchestrator, verbose=False)


def main(case_id: str = "C-02") -> None:
    try:
        import crewai  # noqa: F401
    except ImportError:
        sys.exit("crewai is not installed: pip install crewai")
    case = {c["case_id"]: c for c in race.load_cases()}[case_id]
    crew = build(race.D.build_index_with_policy())
    result = crew.kickoff(inputs={"ticket": json.dumps(case["ticket"])})
    print(result.raw)
    print("token usage:", result.token_usage)


if __name__ == "__main__":
    main(*sys.argv[1:])
