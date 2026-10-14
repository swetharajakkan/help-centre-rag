"""Start/stop the HTTP MCP servers the evidence scripts need.

Not part of the agent: this only launches processes the way an operator
would, so each script is one command.
"""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEEK9 = os.path.join(ROOT, "week9")
EVIDENCE = os.path.join(WEEK9, "evidence")
TICKET_SERVER = os.path.join(WEEK9, "servers", "ticket_history", "server.py")


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


@contextlib.contextmanager
def serve(args: list[str], port: int, env: dict | None = None, log: str | None = None):
    """Run a server for the duration of the block, unless one is already up."""
    if port_open(port):
        yield None
        return
    out = open(log, "w") if log else subprocess.DEVNULL
    proc = subprocess.Popen([sys.executable, *args], cwd=ROOT, stdout=out,
                            stderr=subprocess.STDOUT, env={**os.environ, **(env or {})})
    try:
        for _ in range(150):
            if port_open(port):
                break
            if proc.poll() is not None:
                raise RuntimeError(f"{args[0]} exited with {proc.returncode}")
            time.sleep(0.1)
        else:
            raise RuntimeError(f"{args[0]} did not open port {port}")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if log:
            out.close()


def ticket_server(port: int = 8765, env: dict | None = None):
    return serve([TICKET_SERVER, "--transport", "http", "--port", str(port)], port, env)
