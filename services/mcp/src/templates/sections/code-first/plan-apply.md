### Mutations: plan → confirm → apply

`run` never applies changes directly. A read-only script returns its output immediately. A script that attempts mutations returns a **plan** instead: the exact set of creates/updates/deletes, a provisional output (computed against synthetic responses — placeholder ids like negative numbers are not real), and a single-use plan id — a short three-word phrase with a 10 minute expiry.

Protocol, in order:

1. `run` the script and read the returned plan — nothing has been applied yet.
2. Show the plan to the user and get their explicit confirmation. Never apply unconfirmed.
3. `apply <plan-id>`. The receipt lists each mutation as applied/failed/skipped, plus the real output.

If `apply` reports divergence ("the world changed"), an expired or not-found id, or an already-applied plan, re-run the script to get a fresh plan and confirm again — never retry `apply` blindly and never invent a plan id.
