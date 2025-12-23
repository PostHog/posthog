# PostHog Langchain JS Integration Example

This example demonstrates how to use PostHog tools with Langchain JS using the `@posthog/agent-toolkit` package.

## Features

- Uses the `DynamicStructuredTool` class from Langchain for type-safe tool integration
- Automatically infers tool input types from Zod schemas
- Provides access to all PostHog MCP tools (feature flags, insights, dashboards, etc.)
- Works with any Langchain-compatible LLM

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
