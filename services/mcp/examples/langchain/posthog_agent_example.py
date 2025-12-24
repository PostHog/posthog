"""
PostHog LangChain Integration Example

This example demonstrates how to use PostHog tools with LangChain using
the local posthog_agent_toolkit package. It shows how to analyze product
usage data similar to the TypeScript example.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from posthog_agent_toolkit.integrations.langchain.toolkit import PostHogAgentToolkit


async def analyze_product_usage():
    """Analyze product usage using PostHog data."""

    print("🚀 PostHog LangChain Agent - Product Usage Analysis\n")

    # Initialize the PostHog toolkit with credentials
    toolkit = PostHogAgentToolkit(
        personal_api_key=os.getenv("POSTHOG_PERSONAL_API_KEY"),
        url=os.getenv("POSTHOG_MCP_URL", "https://mcp.posthog.com/mcp"),
    )

    # Get the tools
    tools = await toolkit.get_tools()

    # Initialize the LLM
    llm = ChatOpenAI(model="gpt-5-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))

    # Create a system prompt for the agent
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a data analyst. Your task is to do a deep dive into what's happening in our product. "
                "Be concise and data-driven in your responses.",
            ),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=prompt,
    )

    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        max_iterations=30,
    )

    # Invoke the agent with an analysis request
    result = await agent_executor.ainvoke(
        {
            "input": """Please analyze our product usage:
        
        1. Get all available insights (limit 100)
        2. Pick the 5 MOST INTERESTING and VALUABLE insights - prioritize:
           - User behavior and engagement metrics
           - Conversion funnels
           - Retention and growth metrics
           - Product adoption insights
           - Revenue or business KPIs
           AVOID picking feature flag insights unless they show significant business impact
        3. For each selected insight, query its data and explain why it's important
        4. Summarize the key findings in a brief report with actionable recommendations
        
        Focus on insights that tell a story about user behavior and business performance."""
        }
    )

    print("\n📊 Analysis Complete!\n")
    print("=" * 50)
    print(result["output"])
    print("=" * 50)


async def main():
    """Main function to run the product usage analysis."""
    try:
        # Load environment variables
        load_dotenv()

        # Run the analysis
        await analyze_product_usage()
    except Exception as error:
        print(f"Error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
