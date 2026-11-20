#!/usr/bin/env bash
# PROTOTYPE (ses-threading), never merged. Sends a threaded support-style reply through the code-send API.
# Recipients are caught by the stack's maildev; nothing leaves the box.
set -euo pipefail
KEY=$(cat /tmp/proto_key)
REFS=$(python3 -c 'import json; print(json.dumps([f"<{i:03d}-c0ffee-thread-message@mail.customer-proto.dev>" for i in range(40)]))')
BODY=$(python3 - "$REFS" <<'PY'
import json, sys
refs = json.loads(sys.argv[1])
print(json.dumps({
    "to": "proto-customer@posthog.com",
    "template_key": "support-reply",
    "subject": "Re: Proto ticket about invoices",
    "text": "Thanks, we fixed it.",
    "html": "<p>Thanks, we fixed it.</p>",
    "from": "Proto Support <support@proto-support.dev>",
    "reply_to": ["team-abc123@inbound.proto-support.dev"],
    "cc": ["proto-cc@posthog.com"],
    "tracking": False,
    "sensitive": True,
    "in_reply_to": refs[-1],
    "references": refs,
}))
PY
)
curl -sS -X POST "http://172.17.0.1:8000/api/projects/1/messaging/send/email/" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: proto-outbox-$(date +%s)" -d "$BODY"
echo
