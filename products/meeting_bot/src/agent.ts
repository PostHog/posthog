import Anthropic from '@anthropic-ai/sdk'

import type { Config } from './config'

export interface AnswerSeries {
    label: string
    value: number
}

export interface Answer {
    /** Read aloud, so it has to be plain speakable prose with no markdown or long numbers. */
    speech: string
    /** Rendered large on the bot's video feed. */
    headline: string
    detail: string
    unit: string
    /** Empty when the answer is not a comparison worth charting. */
    series: AnswerSeries[]
}

const ANSWER_SCHEMA = {
    type: 'object',
    properties: {
        speech: {
            type: 'string',
            description: 'One to three sentences to read aloud. Plain prose, no markdown, no bullet points.',
        },
        headline: {
            type: 'string',
            description: 'The answer in under 60 characters, usually the number itself.',
        },
        detail: {
            type: 'string',
            description: 'One short supporting line, such as the date range or the breakdown that was used.',
        },
        unit: {
            type: 'string',
            description: 'What the numbers count, such as "users" or "events". Empty string if not applicable.',
        },
        series: {
            type: 'array',
            description: 'Points to chart on screen. Empty array when there is nothing worth charting.',
            items: {
                type: 'object',
                properties: {
                    label: { type: 'string' },
                    value: { type: 'number' },
                },
                required: ['label', 'value'],
                additionalProperties: false,
            },
        },
    },
    required: ['speech', 'headline', 'detail', 'unit', 'series'],
    additionalProperties: false,
} as const

const SYSTEM_PROMPT = `You are PostHog, sitting in on a live video call as a participant.

Someone has addressed you out loud and asked a question. Answer it using the PostHog tools available to
you, which query the analytics data of the project the API key belongs to.

Rules:
- Your answer is spoken out loud and shown on your video feed at the same time. Keep "speech" to what a
  person would actually say: short, conversational, no markdown, and round long numbers (say
  "about twelve thousand four hundred", not "12,431.7").
- The question was transcribed from speech, so expect mangled product and page names. Map them to the
  closest thing that exists in the data rather than reporting the literal string back.
- If a question is ambiguous, pick the most reasonable reading, answer it, and say which reading you took.
- If the data genuinely is not there, say so in one sentence and name what you looked for.
- Never speculate about numbers you did not retrieve.`

interface AskOptions {
    question: string
    /** Recent conversation, so references like "that page" or "since last week" resolve. */
    context: string
}

export class PostHogAgent {
    private readonly client: Anthropic

    constructor(private readonly config: Config) {
        this.client = new Anthropic({ apiKey: config.anthropicApiKey })
    }

    async ask({ question, context }: AskOptions): Promise<Answer> {
        const userContent = context
            ? `Recent conversation on the call:\n<transcript>\n${context}\n</transcript>\n\nThe question directed at you: ${question}`
            : `The question directed at you: ${question}`

        const request = {
            model: this.config.anthropicModel,
            max_tokens: 4096,
            system: SYSTEM_PROMPT,
            // Answers land mid-conversation, so trade reasoning depth for latency.
            output_config: { effort: 'low' as const, format: { type: 'json_schema' as const, schema: ANSWER_SCHEMA } },
            mcp_servers: [
                {
                    type: 'url' as const,
                    url: this.config.posthogMcpUrl,
                    name: 'posthog',
                    authorization_token: this.config.posthogPersonalApiKey,
                },
            ],
            tools: [{ type: 'mcp_toolset' as const, mcp_server_name: 'posthog' }],
            betas: this.config.enableRefusalFallback
                ? ['mcp-client-2025-11-20', 'server-side-fallback-2026-07-01']
                : ['mcp-client-2025-11-20'],
            ...(this.config.enableRefusalFallback ? { fallbacks: 'default' as const } : {}),
        }

        let messages: Anthropic.Beta.BetaMessageParam[] = [{ role: 'user', content: userContent }]
        let response = await this.client.beta.messages.create({ ...request, messages })

        // The MCP tools run on Anthropic's side, and that server-side loop stops with `pause_turn` when it
        // hits its per-request iteration cap. Re-sending the paused turn resumes it; the cap here only
        // exists so a pathological query cannot spin forever on a live call.
        for (let resumes = 0; response.stop_reason === 'pause_turn' && resumes < 4; resumes++) {
            messages = [
                { role: 'user', content: userContent },
                { role: 'assistant', content: response.content },
            ]
            response = await this.client.beta.messages.create({ ...request, messages })
        }

        if (response.stop_reason === 'refusal') {
            throw new Error('The model declined to answer that question.')
        }

        const text = response.content.find((block) => block.type === 'text')
        if (!text || text.type !== 'text') {
            throw new Error(`No answer came back (stop reason: ${response.stop_reason}).`)
        }

        return JSON.parse(text.text) as Answer
    }
}
