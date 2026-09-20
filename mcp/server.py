#!/usr/bin/env python3
"""Minimal stdio MCP adapter.  It never contains GitHub credentials.

Configure this process in a coding-agent client.  The client gets one bounded
tool; AgentGate owns approval, policy, execution, and evidence.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE = os.environ.get("AGENTGATE_URL", "http://127.0.0.1:8080").rstrip("/")
TOKEN = os.environ.get("AGENTGATE_AGENT_TOKEN", "")
ACTOR = os.environ.get("AGENTGATE_ACTOR_ID", "coding-agent")


def request(path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}", "X-AgentGate-Actor": ACTOR, "Content-Type": "application/json"}
    try:
        with urlopen(Request(BASE + path, data=body, headers=headers, method="POST" if body else "GET"), timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as error:
        return json.loads(error.read() or b'{"error":"agentgate_unavailable"}')


TOOLS = [{"name":"governed_github_action","description":"Request a bounded GitHub action through AgentGate. It cannot execute until a different human approves it.","inputSchema":{"type":"object","required":["repository","action","payload","reason","idempotency_key"],"properties":{"repository":{"type":"string","description":"Exact owner/repository allowed by policy"},"action":{"type":"string","enum":["github.create_issue","github.create_pull_request","github.create_comment","github.request_review"]},"payload":{"type":"object","description":"Typed action fields only; raw GitHub requests are impossible"},"reason":{"type":"string","description":"Human-readable purpose of the change"},"idempotency_key":{"type":"string","description":"A unique stable key for this intended action"}}}}]


def reply(identifier: object, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":identifier,"result":result},separators=(",",":"))+"\n"); sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        try:
            message=json.loads(line); method=message.get("method"); identifier=message.get("id")
            if method=="initialize": reply(identifier,{"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"agentgate","version":"0.1.0"}})
            elif method=="tools/list": reply(identifier,{"tools":TOOLS})
            elif method=="tools/call":
                params=message.get("params",{}); arguments=params.get("arguments",{})
                if params.get("name")!="governed_github_action": raise ValueError("unknown_tool")
                output=request("/v1/actions",arguments)
                reply(identifier,{"content":[{"type":"text","text":json.dumps(output,indent=2)}],"isError":not bool(output.get("allowed"))})
            elif identifier is not None: reply(identifier,{})
        except Exception as exc:
            if 'identifier' in locals() and identifier is not None: reply(identifier,{"content":[{"type":"text","text":f"AgentGate error: {exc}"}],"isError":True})


if __name__=="__main__": main()
