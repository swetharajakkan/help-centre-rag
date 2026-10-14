"""Load the agent's MCP config: which servers to connect to, and how.

The file is the only place a server is named. Adding a server is an edit to
JSON, never to this package -- that is what Task Set A requirement 2 proves.

Shape (deliberately close to the mcpServers block Claude Desktop and Claude
Code use, plus one host-side key, "attach"):

    {"mcpServers": {
       "<name>": {"transport": "stdio", "command": "...", "args": [...],
                  "cwd": "...", "env": {...}},
       "<name>": {"transport": "http", "url": "...", "headers": {...}},
       "<name>": {..., "attach": [{"uri": "x://{id}/y", "when": "<regex>"}],
                  "enabled": false}}}

"attach" lists resources the HOST reads and puts in the prompt when the user's
message matches `when` -- app-attached context, as opposed to tools the model
chooses to call.

Values may use ${VAR} or ${VAR:-default}. Two names are always defined:
${PYTHON} (this interpreter) and ${ROOT} (the repo root, or HELP_CENTRE_ROOT).
"""
from __future__ import annotations

import json
import os
import re
import sys

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "mcp_config.json")
_VAR = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def root() -> str:
    return os.path.abspath(os.environ.get("HELP_CENTRE_ROOT") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _expand(value, env: dict):
    if isinstance(value, str):
        return _VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v, env) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, env) for k, v in value.items()}
    return value


def load(path: str | None = None) -> dict:
    """Read and expand the config. Returns {"path", "servers": {name: spec}}."""
    path = os.path.abspath(path or os.environ.get("HELP_CENTRE_MCP_CONFIG")
                           or DEFAULT_PATH)
    with open(path) as fh:
        raw = json.load(fh)
    env = {**os.environ, "PYTHON": sys.executable, "ROOT": root()}
    servers = {name: _expand(spec, env)
               for name, spec in raw.get("mcpServers", {}).items()
               if spec.get("enabled", True)}
    return {"path": path, "servers": servers}
