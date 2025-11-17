# PostHog AI SDK Integration Example

This example demonstrates how to use PostHog tools with the AI SDK using the `@posthog/agent-toolkit` package.

## Features

- Uses the `tool()` helper function from AI SDK for type-safe tool integration
- Automatically infers tool input types from Zod schemas
- Provides access to all PostHog MCP tools (feature flags, insights, dashboards, etc.)

## Setup

1. Install dependencies:

```bash
npm install
```

2. Copy the environment file and fill in your credentials:

```bash
cp .env.example .env
```

3. Run the example:

```bash
npm run dev
```
