# MCP builder playbooks

The markdown in this directory is the **single source of truth** for the
agent-platform _builder playbooks_ — operator docs about how to use the
authoring tools (read / debug / edit / author agents, identity, secrets, Slack
setup, MCP-surface design, model choice, testing, cost, observability).

`scripts/copy-instructions.ts` generates `src/tools/agentPlatform/playbook*.generated.ts`
from these files; the `agent-resolve-resource` MCP tool serves them to any
consumer, appending a **live, scope-aware tool surface** computed against the
caller's actual scopes. To add or edit a playbook: change the `<id>/SKILL.md`
here and run `tsx services/mcp/scripts/copy-instructions.ts` (CI does this too).

## Three homes for agent guidance — don't confuse them

Agent-platform instructional content lives in exactly one of three places,
chosen by **what the content is for**. Putting a piece in the wrong home is how
the concierge ended up with the same docs bundled _and_ in the MCP.

|                   | **Kernel skills**                                                                                                                                                                             | **MCP playbooks** (here)                                                       | **Skill store**                                                      |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| **What**          | The concierge's own runtime behaviour, **coupled to the platform architecture** — its `focus_*` client tools, runtime client-kind modes, the principal/safety model, the fleet-audit workflow | Reusable knowledge about the **authoring tools** — how to build/operate agents | **Team-authored** reusable agent runtime skills                      |
| **Why this home** | Must move in lockstep with the implementation; identical across every account; **cannot drift in the DB**                                                                                     | Platform docs of the live tool surface; version with the MCP                   | Content that is _supposed_ to vary per team                          |
| **Home**          | **Code** — `products/agent_platform/backend/kernel_skills/`; injected into the bundle at freeze, like the framework preamble                                                                  | **Code** — this dir; served via `agent-resolve-resource`                       | **DB** — the llma-skill store; `skill_refs` → materialized at freeze |
| **Consumer**      | The concierge itself                                                                                                                                                                          | Anyone building agents (human, IDE, _or the concierge_)                        | Any team agent                                                       |

**The discriminator:** _reusable platform knowledge_ → MCP playbook; _this
deployed agent's runtime behaviour_ → kernel skill; _content meant to vary per
team_ → store skill.

**Why kernel can't be a store skill (the drift argument):** if
`safety-and-boundaries` or `using-the-console-ui` were a per-team `skill_refs`
store skill, an account could freeze an agent against a stale copy while the
platform's actual enforcement / client-tool set moved on — the agent would then
_describe a platform it isn't running on_. Kernel content is code-locked so that
can't happen. The store is **only** for content meant to diverge per team.

**Why a playbook isn't a kernel skill:** the concierge _builds_ agents, so it
needs builder knowledge the same way Claude Code does — by fetching it from the
MCP. Builder playbooks are not bundled into any agent; they're fetched on demand
with `agent-resolve-resource`, which is also why they can carry a live
scope-aware tool surface that a static bundled file never could.

## The four kernel skills

These live in the concierge bundle, **not** here:
`safety-and-boundaries`, `using-the-console-ui`, `working-outside-the-console`,
`auditing-the-fleet`. A playbook here must not tell the reader to "load" one of
them (a generic MCP consumer has no such bundled file) — state the relevant fact
inline instead.
