import { ChatPromptTemplate, MessagesPlaceholder } from '@langchain/core/prompts'
import { ChatOpenAI } from '@langchain/openai'
import { PostHogAgentToolkit } from '@posthog/agent-toolkit/integrations/langchain'
import { AgentExecutor, createToolCallingAgent } from 'langchain/agents'
import 'dotenv/config'

async function analyzeProductUsage() {
    const agentToolkit = new PostHogAgentToolkit({
        posthogPersonalApiKey: process.env.POSTHOG_PERSONAL_API_KEY!,
        posthogApiBaseUrl: process.env.POSTHOG_API_BASE_URL || 'https://us.posthog.com',
    })

    const tools = await agentToolkit.getTools()

    const llm = new ChatOpenAI({
        model: 'gpt-5-mini',
    })

    const prompt = ChatPromptTemplate.fromMessages([
        [
            'system',
            "You are a data analyst. Your task is to do a deep dive into what's happening in our product. Be concise and data-driven in your responses.",
        ],
        ['human', '{input}'],
        new MessagesPlaceholder('agent_scratchpad'),
    ])

    const agent = createToolCallingAgent({
        llm,
        tools,
        prompt,
    })

    const agentExecutor = new AgentExecutor({
        agent,
        tools,
        verbose: false,
        maxIterations: 5,
    })

    const result = await agentExecutor.invoke({
        input: `Please analyze our product usage:
        
        1. Get all available insights (limit 100) and pick the 5 most relevant ones
        2. For each insight, query its data
        3. Summarize the key findings in a brief report
        
        Keep your response focused and data-driven.`,
    })
}

async function main() {
    try {
        await analyzeProductUsage()
    } catch (error) {
        console.error('Error:', error)
        process.exit(1)
    }
}

main().catch(console.error)
