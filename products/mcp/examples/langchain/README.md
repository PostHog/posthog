# PostHog LangChain Python Integration Example

This example demonstrates how to use PostHog tools with LangChain using the `posthog_agent_toolkit` package, which provides a wrapper around the PostHog MCP (Model Context Protocol) server.

## Setup

1. Install dependencies:

```bash
pip install posthog-agent-toolkit
# Or if using uv:
uv sync
```

2. Copy the environment file and fill in your credentials:

```bash
cp .env.example .env
```

3. Update your `.env` file with:
    - `POSTHOG_PERSONAL_API_KEY`: Your PostHog personal API key
    - `OPENAI_API_KEY`: Your OpenAI API key

## Usage

Run the example:

```bash
python posthog_agent_example.py
# Or if using uv:
uv run python posthog_agent_example.py
```

The example will:

1. Connect to the PostHog MCP server using your personal API key
2. Load all available PostHog tools from the MCP server
3. Create a LangChain agent with access to PostHog data
4. Analyze product usage by:
    - Getting available insights
    - Querying data for the most relevant ones
    - Summarizing key findings

## Available Tools

For a complete list of all available tools and their capabilities, see the [PostHog MCP documentation](https://posthog.com/docs/model-context-protocol).
