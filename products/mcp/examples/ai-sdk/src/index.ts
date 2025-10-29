import { openai } from '@ai-sdk/openai'
import { PostHogAgentToolkit } from '@posthog/agent-toolkit/integrations/ai-sdk'
import { generateText, stepCountIs } from 'ai'
import 'dotenv/config'

async function analyzeProductUsage() {
    const agentToolkit = new PostHogAgentToolkit({
        posthogPersonalApiKey: process.env.POSTHOG_PERSONAL_API_KEY!,
        posthogApiBaseUrl: process.env.POSTHOG_API_BASE_URL || 'https://us.posthog.com',
    })

    const result = await generateText({
        model: openai('gpt-5-mini'),
        tools: await agentToolkit.getTools(),
        stopWhen: stepCountIs(30),
        system: `You are a data analyst. Your task is to do a deep dive into what's happening in our product.`,
        prompt: `Please analyze our product usage:
        
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
