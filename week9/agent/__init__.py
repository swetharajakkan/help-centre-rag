"""Week 9 agent: an MCP host whose tools come only from its config.

    host.py    one MCP client per configured server; tools/list discovery
    model.py   where the AI runs (Claude, or the offline planner)
    loop.py    the agent loop over discovered tools
    crew.py    Responder + Verifier
    config.py  reads mcp_config.json
    cli.py     python -m week9.agent.cli
"""
