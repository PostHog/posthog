# posthog-agent-toolkit

Tools to give agents access to your PostHog data, manage feature flags, create insights, and more.

This is a Python wrapper around the PostHog MCP (Model Context Protocol) server, providing easy integration with AI frameworks like LangChain.

## Installation

```bash
pip install posthog-agent-toolkit
```

## Quick Start

The toolkit provides integrations for popular AI frameworks:

### Using with LangChain

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from posthog_agent_toolkit.integrations.langchain.toolkit import PostHogAgentToolkit

# Initialize the PostHog toolkit
toolkit = PostHogAgentToolkit(
    personal_api_key="your_posthog_personal_api_key",
    url="https://mcp.posthog.com/mcp"  # or your own, if you are self hosting the MCP server
)

# Get the tools
tools = await toolkit.get_tools()

# Initialize the LLM
llm = ChatOpenAI(model="gpt-5-mini")

# Create a prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a data analyst with access to PostHog analytics"),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

# Create and run the agent
agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
executor = AgentExecutor(agent=agent, tools=tools)

result = await executor.ainvoke({
    "input": "Analyze our product usage by getting the top 5 most interesting insights and summarising the data from them."
})
```

**[→ See full LangChain example](https://github.com/PostHog/posthog/tree/master/products/mcp/examples/langchain)**

## Available Tools

For a list of all available tools, please see the [docs](https://posthog.com/docs/model-context-protocol).
