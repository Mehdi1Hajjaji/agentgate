from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agentgate.app import AgentGateApp, handler_factory
from agentgate.config import Settings
from http.server import ThreadingHTTPServer


class HttpFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); root=Path(self.temp.name)
        policy=root/"policy.yaml"
        policy.write_text("""version: \"1\"\ndefault: deny\nrepositories:\n  acme/example-repository:\n    actions:\n      github.create_issue:\n        approval: required\n        max_title_length: 160\n        max_body_length: 1000\n""")
        settings=Settings(root,policy,"agent-token","admin-token","","",None,"webhook-secret")
        self.server=ThreadingHTTPServer(("127.0.0.1",0),handler_factory(AgentGateApp(settings)))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.temp.cleanup()

    def post(self,path,payload,headers):
        request=Request(self.base+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json",**headers},method="POST")
        try:
            with urlopen(request) as result: return result.status,json.loads(result.read())
        except HTTPError as error: return error.code,json.loads(error.read())

    def test_approval_and_single_use_fail_closed(self):
        agent={"Authorization":"Bearer agent-token","X-AgentGate-Actor":"agent-a"}
        status,created=self.post("/v1/actions",{"repository":"acme/example-repository","action":"github.create_issue","payload":{"title":"Bounded issue","body":"Review first."},"reason":"A real reason","idempotency_key":"http-flow-idempotency-key-0001"},agent)
        self.assertEqual(status,202); request_id=created["request"]["id"]
        denied,_=self.post(f"/v1/requests/{request_id}/decision",{"approver_id":"agent-a","reason":"bad","decision":"approve"},{"X-AgentGate-Admin-Key":"admin-token"})
        self.assertEqual(denied,403)
        approved,_=self.post(f"/v1/requests/{request_id}/decision",{"approver_id":"reviewer-b","reason":"Independent review","decision":"approve"},{"X-AgentGate-Admin-Key":"admin-token"})
        self.assertEqual(approved,200)
        failed,body=self.post(f"/v1/requests/{request_id}/execute",{},agent)
        self.assertEqual(failed,502); self.assertEqual(body["reason"],"github_app_not_configured")
        replay,body=self.post(f"/v1/requests/{request_id}/execute",{},agent)
        self.assertEqual(replay,403); self.assertEqual(body["error"],"capability_not_active_or_already_used")


if __name__=="__main__": unittest.main()
