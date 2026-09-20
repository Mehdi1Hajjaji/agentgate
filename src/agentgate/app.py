from __future__ import annotations

import hmac
import json
import os
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .github import GitHubAppClient, GitHubError
from .policy import Policy
from .store import Store


class AgentGateApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.database_path)
        self.policy = Policy.load(settings.policy_path)
        self.github = GitHubAppClient(settings)

    @staticmethod
    def public_request(row: dict) -> dict:
        keep = ("id", "requester_id", "repository", "action", "payload", "status", "request_reason", "approver_id", "approval_reason", "approval_at", "created_at", "updated_at", "execution_error")
        return {key: row.get(key) for key in keep}

    def submit(self, requester: str, data: dict) -> tuple[dict, int]:
        repository = data.get("repository")
        action = data.get("action")
        payload = data.get("payload")
        reason = data.get("reason")
        idem = data.get("idempotency_key")
        if not all(isinstance(item, str) and item.strip() for item in (repository, action, reason, idem)) or not isinstance(payload, dict):
            raise ValueError("repository, action, payload, reason, and idempotency_key are required")
        decision = self.policy.evaluate(repository, action, payload)
        if not decision.allowed:
            return {"allowed": False, "reason": decision.reason}, 403
        request, created = self.store.create_request(requester, repository, action, payload, reason, idem, str(self.policy.raw.get("version", "1")))
        return {"allowed": True, "request": self.public_request(request), "review_url": f"/requests/{request['id']}", "idempotent_replay": not created}, 202

    def execute(self, request_id: str) -> tuple[dict, int]:
        request = self.store.reserve_execution(request_id)
        # Reload policy immediately before the external boundary; stale policy never executes.
        self.policy = Policy.load(self.settings.policy_path)
        decision = self.policy.evaluate(request["repository"], request["action"], request["payload"])
        if not decision.allowed:
            self.store.fail_execution(request_id, "policy_changed_before_execution")
            return {"allowed": False, "reason": "policy_changed_before_execution"}, 403
        try:
            external = self.github.execute(request["repository"], request["action"], request["payload"])
            receipt = self.store.record_receipt(request_id, external)
        except GitHubError as exc:
            self.store.fail_execution(request_id, str(exc))
            return {"allowed": False, "reason": str(exc)}, 502
        return {"allowed": True, "request_id": request_id, "receipt": receipt, "external_reference": external}, 200


def form_page(request: dict | None, error: str = "") -> bytes:
    if request is None:
        content = "<h1>Request not found</h1>"
    else:
        payload = escape(json.dumps(request["payload"], indent=2, ensure_ascii=False))
        status = escape(request["status"])
        title = escape(f"{request['action']} on {request['repository']}")
        content = f"""<main><p class='eyebrow'>AGENTGATE · HUMAN DECISION</p><h1>{title}</h1><p class='status'>{status}</p><dl><dt>Requested by</dt><dd>{escape(request['requester_id'])}</dd><dt>Why</dt><dd>{escape(request['request_reason'])}</dd></dl><h2>Bounded action payload</h2><pre>{payload}</pre>"""
        if request["status"] == "pending_approval":
            content += f"""<form method='post' action='/requests/{escape(request['id'])}/decision'><label>Reviewer identity<input required name='approver_id' maxlength='120'></label><label>Decision reason<textarea required name='reason' maxlength='500'></textarea></label><label>Reviewer token<input required type='password' name='admin_token'></label><button name='decision' value='approve'>Approve narrowly</button><button class='deny' name='decision' value='deny'>Deny</button></form>"""
        else:
            content += f"<h2>Decision</h2><p>{escape(str(request.get('approval_reason') or request.get('execution_error') or 'No decision details'))}</p>"
        content += "</main>"
    page=f"""<!doctype html><html><head><meta charset='utf-8'><title>AgentGate review</title><style>body{{margin:0;background:#0b1020;color:#e6edf7;font:16px system-ui}}main{{max-width:760px;margin:48px auto;padding:32px;background:#131b2f;border:1px solid #263451;border-radius:14px}}h1{{margin-top:4px}}.eyebrow{{color:#79c0ff;font-size:12px;letter-spacing:.1em}}.status{{display:inline-block;padding:6px 10px;border-radius:20px;background:#263451;color:#a5d6ff}}dt{{color:#9db0ca;margin-top:14px}}dd{{margin:4px 0 0}}pre{{white-space:pre-wrap;overflow:auto;background:#080c17;padding:18px;border-radius:8px}}form{{display:grid;gap:14px;margin-top:24px}}label{{display:grid;gap:7px;color:#b8c7dc}}input,textarea{{background:#080c17;color:#fff;border:1px solid #3a4b6b;border-radius:7px;padding:10px;font:inherit}}textarea{{min-height:90px}}button{{background:#2ea043;color:#fff;border:0;border-radius:7px;padding:11px;font-weight:700;cursor:pointer}}button.deny{{background:#da3633}}</style></head><body>{content}</body></html>"""
    return page.encode("utf-8")


def handler_factory(app: AgentGateApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentGate/0.1"

        def _json(self, status: int, value: dict) -> None:
            body=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

        def _body_json(self) -> dict:
            length=int(self.headers.get("Content-Length","0")); raw=self.rfile.read(length)
            try: parsed=json.loads(raw)
            except json.JSONDecodeError: raise ValueError("invalid_json")
            if not isinstance(parsed,dict): raise ValueError("json_object_required")
            return parsed

        def _agent(self) -> str | None:
            given=self.headers.get("Authorization","").removeprefix("Bearer ").strip()
            if not app.settings.agent_token or not hmac.compare_digest(given,app.settings.agent_token): return None
            actor=self.headers.get("X-AgentGate-Actor","").strip()
            return actor if 1 <= len(actor) <= 120 else None

        def _admin(self) -> bool:
            given=self.headers.get("X-AgentGate-Admin-Key","").strip()
            return bool(app.settings.admin_token and hmac.compare_digest(given,app.settings.admin_token))

        def do_GET(self) -> None:
            parsed=urlparse(self.path)
            if parsed.path=="/healthz": return self._json(200,{"status":"ok","github_app_configured":app.github.configured()})
            if parsed.path=="/v1/requests":
                if not self._admin(): return self._json(401,{"error":"admin_auth_required"})
                return self._json(200,{"requests":[app.public_request(row) for row in app.store.list_pending()]})
            if parsed.path.startswith("/v1/requests/"):
                row=app.store.get_request(parsed.path.rsplit("/",1)[-1]); return self._json(200,{"request":app.public_request(row)}) if row else self._json(404,{"error":"request_not_found"})
            if parsed.path.startswith("/v1/receipts/"):
                row=app.store.get_receipt(parsed.path.rsplit("/",1)[-1]); return self._json(200,{"receipt":row}) if row else self._json(404,{"error":"receipt_not_found"})
            if parsed.path.startswith("/requests/"):
                request_id=parsed.path.rsplit("/",1)[-1]; row=app.store.get_request(request_id); body=form_page(row); self.send_response(200 if row else 404); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            self._json(404,{"error":"not_found"})

        def do_POST(self) -> None:
            parsed=urlparse(self.path); path=parsed.path
            try:
                if path=="/v1/actions":
                    actor=self._agent()
                    if not actor: return self._json(401,{"error":"agent_auth_required"})
                    value,status=app.submit(actor,self._body_json()); return self._json(status,value)
                if path.startswith("/v1/requests/") and path.endswith("/decision"):
                    if not self._admin(): return self._json(401,{"error":"admin_auth_required"})
                    request_id=path.split("/")[3]; data=self._body_json(); item=app.store.decide(request_id,str(data.get("approver_id","")),str(data.get("reason","")),str(data.get("decision",""))=="approve"); return self._json(200,{"request":app.public_request(item)})
                if path.startswith("/v1/requests/") and path.endswith("/execute"):
                    actor=self._agent()
                    if not actor: return self._json(401,{"error":"agent_auth_required"})
                    request_id=path.split("/")[3]; row=app.store.get_request(request_id)
                    if not row or row["requester_id"]!=actor: return self._json(403,{"error":"requester_binding_failed"})
                    value,status=app.execute(request_id); return self._json(status,value)
                if path=="/github/webhook":
                    raw=self.rfile.read(int(self.headers.get("Content-Length","0"))); signature=self.headers.get("X-Hub-Signature-256",""); expected="sha256="+hmac.new(app.settings.github_webhook_secret.encode(),raw,"sha256").hexdigest()
                    if not app.settings.github_webhook_secret or not hmac.compare_digest(signature,expected): return self._json(401,{"error":"invalid_webhook_signature"})
                    delivered=app.store.record_webhook(self.headers.get("X-GitHub-Delivery",""),self.headers.get("X-GitHub-Event",""),raw); return self._json(202,{"accepted":delivered,"duplicate":not delivered})
                if path.startswith("/requests/") and path.endswith("/decision"):
                    request_id=path.split("/")[2]; raw=self.rfile.read(int(self.headers.get("Content-Length","0"))).decode(); form=parse_qs(raw); token=form.get("admin_token",[""])[0]
                    if not app.settings.admin_token or not hmac.compare_digest(token,app.settings.admin_token): return self._json(401,{"error":"admin_auth_required"})
                    item=app.store.decide(request_id,form.get("approver_id",[""])[0],form.get("reason",[""])[0],form.get("decision",[""])[0]=="approve")
                    self.send_response(303); self.send_header("Location",f"/requests/{item['id']}"); self.end_headers(); return
                self._json(404,{"error":"not_found"})
            except ValueError as exc: self._json(400,{"error":str(exc)})
            except LookupError as exc: self._json(404,{"error":str(exc)})
            except PermissionError as exc: self._json(403,{"error":str(exc)})
            except Exception: self._json(500,{"error":"internal_error"})

        def log_message(self, format: str, *args: object) -> None: return
    return Handler


def main() -> None:
    settings=Settings.from_env()
    if not settings.agent_token or not settings.admin_token:
        raise SystemExit("Set AGENTGATE_AGENT_TOKEN and AGENTGATE_ADMIN_TOKEN; see .env.example")
    app=AgentGateApp(settings)
    server=ThreadingHTTPServer((os.environ.get("AGENTGATE_HOST","127.0.0.1"),int(os.environ.get("AGENTGATE_PORT","8080"))),handler_factory(app))
    print(f"AgentGate listening on http://{server.server_address[0]}:{server.server_address[1]}")
    server.serve_forever()

if __name__=="__main__": main()
