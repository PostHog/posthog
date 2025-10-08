# @posthog/agent-toolkit

Tools to give agents access to your PostHog data, manage feature flags, create insights, and more.

## Installation

```bash
npm install @posthog/agent-toolkit
```

## Quick Start

The toolkit provides integrations for popular AI frameworks:

### Using with Vercel AI SDK

```typescript
import { openai } from '@ai-sdk/openai'
import { generateText } from 'ai'

import { PostHogAgentToolkit } from '@posthog/agent-toolkit/integrations/ai-sdk'

const toolkit = new PostHogAgentToolkit({
    posthogPersonalApiKey: process.env.POSTHOG_PERSONAL_API_KEY!,
    posthogApiBaseUrl: 'https://us.posthog.com', // or https://eu.posthog.com if you are hosting in the EU
})

const result = await generateText({
    model: openai('gpt-4'),
    tools: await toolkit.getTools(),
    prompt: 'Analyze our product usage by getting the top 5 most interesting insights and summarising the data from them.',
})
```

**[→ See full Vercel AI SDK example](https://github.com/PostHog/posthog/tree/master/products/mcp/examples/ai-sdk)**

### Using with LangChain.js

```typescript
import { ChatPromptTemplate, MessagesPlaceholder } from '@langchain/core/prompts'
import { ChatOpenAI } from '@langchain/openai'
import { AgentExecutor, createToolCallingAgent } from 'langchain/agents'

import { PostHogAgentToolkit } from '@posthog/agent-toolkit/integrations/langchain'

const toolkit = new PostHogAgentToolkit({
    posthogPersonalApiKey: process.env.POSTHOG_PERSONAL_API_KEY!,
    posthogApiBaseUrl: 'https://us.posthog.com', // or https://eu.posthog.com if you are hosting in the EU
})

const tools = await toolkit.getTools()
const llm = new ChatOpenAI({ model: 'gpt-4' })

const prompt = ChatPromptTemplate.fromMessages([
    ['system', 'You are a data analyst with access to PostHog analytics'],
    ['human', '{input}'],
    new MessagesPlaceholder('agent_scratchpad'),
])

const agent = createToolCallingAgent({ llm, tools, prompt })
const executor = new AgentExecutor({ agent, tools })

const result = await executor.invoke({
    input: 'Analyze our product usage by getting the top 5 most interesting insights and summarising the data from them.',
})
```

**[→ See full LangChain.js example](https://github.com/PostHog/posthog/tree/master/products/mcp/examples/langchain-js)**

## Available Tools

For a list of all available tools, please see the [docs](https://posthog.com/docs/model-context-protocol).
