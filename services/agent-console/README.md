# @posthog/agent-console

Standalone read-mostly console for the PostHog agent platform.

**v0 status:** Storybook-first. Every surface is mocked against fixtures
shipped by [`@posthog/agent-chat/fixtures`](../../packages/agent-chat/src/fixtures/).
No OAuth, no real API calls, no SSE. Design review happens in Storybook
before any backend wiring lands.

## Run it

```bash
pnpm --filter @posthog/agent-console install
pnpm --filter @posthog/agent-console storybook    # design review surface — :6041
pnpm --filter @posthog/agent-console dev          # Next.js app shell      — :3040
```

Both surfaces render the same page components against the same fixtures.

## Layout

```text
services/agent-console/
├── app/                     # Next.js app router routes
│   ├── layout.tsx
│   ├── page.tsx             # / — agents list
│   └── agents/[slug]/
│       └── page.tsx         # /agents/:slug — detail + AgentChat dock
├── src/
│   ├── pages/               # Page components shared by routes + stories
│   ├── lib/mockApi.ts       # Fixture-backed REST stub (v0 only)
│   └── styles/globals.css
└── .storybook/              # Storybook globs both this package and agent-chat
```
