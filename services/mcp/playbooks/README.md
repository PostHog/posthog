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

Agent-platform instructional content lives in one of three places, chosen by
**what the content is for**.

|                   | **Bundled skills**                                                                                                                                                                            | **MCP playbooks** (here)                                                       | **Skill store**                                                       |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| **What**          | An agent's own runtime behaviour shipped with it — e.g. the agent-builder's `focus_*` client tools, client-kind modes, principal/safety model, fleet-audit workflow                               | Reusable knowledge about the **authoring tools** — how to build/operate agents | **Team-authored** reusable agent runtime skills                       |
| **Why this home** | Owned by the agent; for a code-seeded agent, in lockstep with the implementation                                                                                                             | Platform docs of the live tool surface; version with the MCP                   | Content that is _supposed_ to vary per team; edit once, used live     |
| **Home**          | The agent's own bundle (`skills/<id>/SKILL.md`, `source: 'bundle'`); read via `@posthog/load-skill`                                                                                           | **Code** — this dir; served via `agent-resolve-resource`                       | **DB** — the llma-skill store; `skill_refs` (`source: 'store'`), resolved LIVE at load |
| **Consumer**      | The agent that ships it                                                                                                                                                                       | Anyone building agents (human, IDE, _or the agent-builder_)                        | Any team agent                                                        |

**The discriminator:** _reusable platform knowledge_ → MCP playbook; _this
agent's own runtime behaviour_ → bundled skill; _content meant to vary per team_
→ store skill.

**Bundled vs store (the drift argument):** a code-seeded agent like the
agent-builder ships its safety/console/audit skills **in its own bundle**, so they
move with the code and can't drift per account. The store is for content meant to
diverge per team — and is resolved LIVE at load time, so a team edit propagates
to its agents without a re-freeze (pin a `version` to opt out).

**Why a playbook isn't a bundled skill:** the agent-builder _builds_ agents, so it
needs builder knowledge the same way Claude Code does — by fetching it from the
MCP. Builder playbooks are not bundled into any agent; they're fetched on demand
with `agent-resolve-resource`, which is also why they can carry a live
scope-aware tool surface that a static bundled file never could.

## The four agent-builder bundled skills

These live in the agent-builder bundle (`examples/agent-builder/skills/`), **not**
here: `safety-and-boundaries`, `using-the-console-ui`,
`working-outside-the-console`, `auditing-the-fleet`. A playbook here must not
tell the reader to "load" one of them (a generic MCP consumer has no such
bundled file) — state the relevant fact inline instead.
