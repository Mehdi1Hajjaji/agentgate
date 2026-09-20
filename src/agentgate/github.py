from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt

from .config import Settings


class GitHubError(RuntimeError):
    pass


class GitHubAppClient:
    def __init__(self, settings: Settings): self.settings = settings

    def configured(self) -> bool:
        return bool(self.settings.github_app_id and self.settings.github_installation_id and self.settings.github_private_key_path and self.settings.github_private_key_path.is_file())

    def _installation_token(self) -> str:
        if not self.configured(): raise GitHubError("github_app_not_configured")
        private_key = self.settings.github_private_key_path.read_text(encoding="utf-8")
        import time
        app_jwt = jwt.encode({"iat":int(time.time())-30,"exp":int(time.time())+540,"iss":self.settings.github_app_id}, private_key, algorithm="RS256")
        request = Request(f"https://api.github.com/app/installations/{self.settings.github_installation_id}/access_tokens", data=b"{}", method="POST", headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {app_jwt}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"AgentGate/0.1"})
        try:
            with urlopen(request,timeout=15) as response: return json.loads(response.read())["token"]
        except (HTTPError,URLError,KeyError,json.JSONDecodeError) as exc: raise GitHubError("github_installation_token_denied") from exc

    def execute(self, repository: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        token=self._installation_token(); endpoint=""; body: dict[str, Any]
        if action=="github.create_issue": endpoint="issues"; body={"title":payload["title"],"body":payload["body"]}
        elif action=="github.create_pull_request": endpoint="pulls"; body={k:payload[k] for k in ("title","head","base")}; body["body"]=payload.get("body",""); body["draft"]=bool(payload.get("draft",False))
        elif action=="github.create_comment": endpoint=f"issues/{payload['issue_number']}/comments"; body={"body":payload["body"]}
        elif action=="github.request_review": endpoint=f"pulls/{payload['pull_number']}/requested_reviewers"; body={"reviewers":payload["reviewers"]}
        else: raise GitHubError("action_not_implemented")
        request=Request(f"https://api.github.com/repos/{repository}/{endpoint}",data=json.dumps(body,separators=(",",":")).encode(),method="POST",headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","Content-Type":"application/json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"AgentGate/0.1"})
        try:
            with urlopen(request,timeout=20) as response:
                result=json.loads(response.read()); return {"github_status":response.status,"github_request_id":response.headers.get("X-GitHub-Request-Id"),"url":result.get("html_url"),"number":result.get("number"),"node_id":result.get("node_id"),"action":action,"repository":repository}
        except HTTPError as exc: raise GitHubError(f"github_api_denied_{exc.code}") from exc
        except (URLError,json.JSONDecodeError) as exc: raise GitHubError("github_api_unavailable") from exc
