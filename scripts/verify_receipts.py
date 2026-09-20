#!/usr/bin/env python3
"""Verify AgentGate's local append-only receipt chain."""
from __future__ import annotations
import hashlib, json, os, sqlite3, sys
from pathlib import Path

path=Path(os.environ.get("AGENTGATE_DATA_DIR","./data"))/"agentgate.sqlite"
if not path.exists(): raise SystemExit("No AgentGate database found.")
conn=sqlite3.connect(path); conn.row_factory=sqlite3.Row
previous=None; count=0
for row in conn.execute("SELECT * FROM receipts ORDER BY accepted_at,rowid"):
    if row["previous_hash"]!=previous: raise SystemExit(f"FAIL receipt {row['id']}: previous_hash mismatch")
    material="|".join([previous or "",row["action_request_id"],row["capability_id"],row["external_reference_json"],row["accepted_at"]])
    expected=hashlib.sha256(material.encode()).hexdigest()
    if row["receipt_hash"]!=expected: raise SystemExit(f"FAIL receipt {row['id']}: hash mismatch")
    previous=expected; count+=1
print(f"PASS: {count} receipt(s), chain head {previous or 'empty'}")
