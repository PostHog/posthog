# LLM analytics skills store — competitive landscape

**Question:** Are PostHog LLM analytics among the first observability vendors to host a managed, user-authored "skills store" — where users create, version, and maintain skills inside the product, reusable across any agent surface (Claude Code, Cursor, Codex, etc.) via the open Agent Skills spec?

**Short answer:** Yes, with one important caveat. Every major observability competitor checked has *vendor-authored* skills (a GitHub repo of skills that teach an agent how to use *their* product). None of them currently host *user-authored* skills as managed entities inside the product. Langfuse users have explicitly asked for it on GitHub and the team has not yet committed.

The caveat: most competitors have prompt management with versioning, which is the closest adjacent primitive. A skeptic could frame our skills feature as "prompt management with bundled files." The differentiators worth defending are (a) the bundled resources/files alongside the markdown body, (b) compliance with the open [Agent Skills spec](https://agentskills.io/specification) so the same skill works across Claude Code, Cursor, Codex, Gemini CLI, etc., and (c) the progressive-disclosure invocation model rather than always-on prompts.

## Comparison matrix

| Vendor | Vendor-authored skills (about their product) | User-authored skills hosted in product | Versioned skills | Reusable across agent surfaces (open spec) |
|---|---|---|---|---|
| **PostHog LLM analytics** | n/a (this is the in-product feature) | ✅ `LLMSkill` model, team-scoped | ✅ `version` + `is_latest` | ✅ Agent Skills spec |
| Langfuse | ✅ [`langfuse/skills`](https://github.com/langfuse/skills) | ❌ Asked for in [discussion #12290](https://github.com/orgs/langfuse/discussions/12290), Q2 planning, no commitment | n/a | n/a |
| LangSmith / LangChain | ✅ [`langchain-ai/langchain-skills`](https://github.com/langchain-ai/langchain-skills), [`langsmith-skills`](https://github.com/langchain-ai/langsmith-skills) | ❌ | n/a | n/a |
| Arize AX / Phoenix | ✅ [`arize-ai/phoenix`](https://github.com/Arize-ai/phoenix), [arize-skills](https://arize.com/docs/ax/agents/arize-skills) | ❌ | n/a | n/a |
| Datadog LLM Observability | ✅ [`datadog-labs/agent-skills`](https://github.com/datadog-labs/agent-skills) | ❌ | n/a | n/a |
| W&B Weave | ✅ [`wandb/skills`](https://github.com/wandb/skills) | ❌ | n/a | n/a |
| Helicone | ❌ (no skills offering found) | ❌ — has [prompt management with versioning](https://docs.helicone.ai/features/advanced-usage/prompts), but skills ≠ prompts | n/a (prompts only) | n/a |
| Galileo | ❌ | ❌ | n/a | n/a |
| Lunary | ❌ | ❌ | n/a | n/a |
| Pydantic Logfire | ❌ | ❌ | n/a | n/a |
| Honeycomb | ❌ | ❌ | n/a | n/a |

## Background — what's actually happening in the market

The [Agent Skills spec](https://agentskills.io/specification) (originally from Anthropic, Dec 2025) has become the dominant cross-agent standard. SKILL.md files with YAML frontmatter + markdown body + optional resources are now portable across 30+ agent products including OpenAI Codex, Google Gemini CLI, Microsoft/GitHub Copilot, Cursor, Windsurf, JetBrains Junie, etc.

This created a wave of skills marketplaces — [skills.sh](https://skills.sh/) (Vercel, Jan 2026), [SkillsMP](https://skillsmp.com/), [agentskills.io](https://agentskills.io/), [agentskills.so](https://agentskills.so/) — but those are general-purpose marketplaces, not LLM-observability-native.

Inside the LLM observability category, every vendor that has shipped "skills" so far has done so the same way: a GitHub repo of vendor-authored SKILL.md files that teach an agent how to use *their* product (call their API, query their traces, etc.), installed via `npx skills add` or as a Cursor plugin.

What none of them have shipped: a managed library where *users* author and version their own skills, hosted inside the observability product itself, that they can then reuse across whatever agent surface they want.

## Per-vendor notes

### Langfuse — the strongest evidence
- Has the vendor-authored [`langfuse/skills`](https://github.com/langfuse/skills) repo for using the Langfuse platform.
- [GitHub discussion #12290](https://github.com/orgs/langfuse/discussions/12290) — users explicitly asking for in-product user-authored skill management:
  > "skills are a piece of prompt but they are different, skills can have resources linked"
- Maintainer suggested storing skills as prompts as a workaround; users said the workaround lacks structure. Q2 planning underway, no concrete commitment to ship.
- This is the cleanest "we are first" signal — it's the most observability-spec-aware competitor, and they explicitly haven't shipped this yet.

### LangSmith / LangChain
- Two GitHub repos of vendor skills: [`langchain-skills`](https://github.com/langchain-ai/langchain-skills), [`langsmith-skills`](https://github.com/langchain-ai/langsmith-skills).
- Heavy investment in [Deep Agents](https://blog.langchain.com/using-skills-with-deep-agents/) which uses SKILL.md.
- No user-authored skills library hosted in LangSmith.

### Arize AX / Phoenix
- [Arize Skills](https://arize.com/docs/ax/agents/arize-skills) and the Alyx agent — vendor-authored skills for using Arize. Documentation explicitly frames skills as "encoding the workflows we've refined building the Arize platform."
- No user-authored skills library.

### Datadog LLM Observability
- [`datadog-labs/agent-skills`](https://github.com/datadog-labs/agent-skills) — four skills (eval-session-classify, eval-trace-rca, eval-bootstrap, experiment-analyzer). All Datadog-authored.
- No user-authored skills library.

### Weights & Biases Weave
- [`wandb/skills`](https://github.com/wandb/skills) — vendor-authored skills bundling helper libraries (`wandb_helpers.py`, `weave_helpers.py`).
- No user-authored skills library.

### Helicone
- [Prompt management with versioning](https://docs.helicone.ai/features/advanced-usage/prompts) and rollback, but no Agent Skills offering.
- This is the closest "adjacent primitive" — and the framing risk: prompt-management vendors will claim our skills are "just prompts."

### Galileo, Lunary, Pydantic Logfire, Honeycomb
- None ship Agent Skills (vendor or user-authored) at the time of writing.

## What this means for positioning

If the goal is to make noise about being first, the defensible claim is narrow and specific:

> PostHog LLM analytics is, as of April 2026, the first LLM observability product to host a managed library of *user-authored* Agent Skills — versioned, team-scoped, and portable across any agent surface that supports the open Agent Skills spec.

That claim survives scrutiny. The broader claim "first to have skills" does not — every major competitor has vendor-authored skills already.

The strategic story Andy flagged is also worth leading with: users adding their daily skills to PostHog turns LLM analytics into the canonical home for their agent context, which is the sticky factor and a natural extension of "product autonomy" → "agent autonomy."

## Caveats / counterarguments to be ready for

1. **"Isn't this just prompt management with extra steps?"** — Skills bundle resources/files (not just a single string), follow an open spec that's portable across agent surfaces, and use progressive disclosure (frontmatter loaded eagerly, body on demand). The Langfuse user thread is the cleanest external articulation of why these are different primitives.
2. **"What about general-purpose skills marketplaces (skills.sh, SkillsMP)?"** — Those host community skills but are not observability-native. The PostHog angle is hosting your skills next to your traces, evals, and metrics — same place you debug.
3. **Recency risk** — This space is moving fast (Agent Skills spec is ~4 months old). Langfuse could ship tomorrow. The "first" claim has a short shelf life; if making noise, do it now.
4. **Sample bias** — I checked 11 competitors (Braintrust, Langfuse, LangSmith, Arize AX/Phoenix, Datadog, W&B Weave, Helicone, Galileo, Lunary, Logfire, Honeycomb). I did not check every smaller player (e.g., Maxim AI, PromptLayer, TruLens, Comet Opik, Portkey). Worth a 30-min sweep before publishing if precision matters.

## Sources

- [Agent Skills specification](https://agentskills.io/specification)
- [Langfuse skills GitHub](https://github.com/langfuse/skills)
- [Langfuse skills management discussion #12290](https://github.com/orgs/langfuse/discussions/12290)
- [Langfuse Agent Skill docs](https://langfuse.com/docs/api-and-data-platform/features/agent-skill)
- [LangChain skills GitHub](https://github.com/langchain-ai/langchain-skills)
- [LangSmith skills GitHub](https://github.com/langchain-ai/langsmith-skills)
- [Using skills with Deep Agents — LangChain blog](https://blog.langchain.com/using-skills-with-deep-agents/)
- [Arize AX Skills docs](https://arize.com/docs/ax/agents/arize-skills)
- [Datadog agent-skills GitHub](https://github.com/datadog-labs/agent-skills)
- [W&B skills GitHub](https://github.com/wandb/skills)
- [Helicone prompt management](https://docs.helicone.ai/features/advanced-usage/prompts)
- [skills.sh announcement](https://skills.sh/)
- [SkillsMP marketplace](https://skillsmp.com/)
