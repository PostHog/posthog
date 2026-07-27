import { randomBytes } from 'node:crypto'

export interface Config {
    port: number
    /**
     * Public HTTPS origin for this service. Recall.ai renders the stage page and opens the transcript
     * websocket from its own infrastructure, so localhost is never reachable: both URLs have to resolve
     * on the public internet (a tunnel is fine for a demo).
     */
    publicBaseUrl: string
    /** Guards the stage page and the transcript socket, both of which are necessarily public. */
    sharedSecret: string

    recallApiKey: string
    /**
     * Recall.ai is region-sharded and there is no global hostname, so the region a workspace was created
     * in has to be configured rather than inferred.
     */
    recallApiBase: string
    /** Larger instance type for output media, which needs headroom to encode audio and video. */
    recallBotVariant: string
    botName: string
    transcriptProvider: string

    anthropicApiKey: string
    anthropicModel: string
    /** Requesting a fallback model server-side needs a beta that not every org has enabled. */
    enableRefusalFallback: boolean

    posthogMcpUrl: string
    posthogPersonalApiKey: string

    elevenLabsApiKey: string
    elevenLabsVoiceId: string
    elevenLabsModelId: string

    triggerPhrase: string
    /** How much preceding conversation to hand the model as context for a question. */
    bufferSeconds: number
}

function required(name: string): string {
    const value = process.env[name]
    if (!value) {
        throw new Error(`${name} is required. See products/meeting_bot/README.md for setup.`)
    }
    return value
}

function optional(name: string, fallback: string): string {
    return process.env[name] || fallback
}

export function loadConfig(): Config {
    return {
        port: Number(optional('PORT', '3030')),
        publicBaseUrl: required('PUBLIC_BASE_URL').replace(/\/$/, ''),
        sharedSecret: optional('SHARED_SECRET', randomBytes(16).toString('hex')),

        recallApiKey: required('RECALL_API_KEY'),
        recallApiBase: optional('RECALL_API_BASE', 'https://us-west-2.recall.ai').replace(/\/$/, ''),
        recallBotVariant: optional('RECALL_BOT_VARIANT', 'web_4_core'),
        botName: optional('BOT_NAME', 'PostHog'),
        transcriptProvider: optional('RECALL_TRANSCRIPT_PROVIDER', 'recallai_streaming'),

        anthropicApiKey: required('ANTHROPIC_API_KEY'),
        anthropicModel: optional('ANTHROPIC_MODEL', 'claude-opus-5'),
        enableRefusalFallback: optional('ANTHROPIC_REFUSAL_FALLBACK', 'true') === 'true',

        posthogMcpUrl: optional('POSTHOG_MCP_URL', 'https://mcp.posthog.com/mcp'),
        posthogPersonalApiKey: required('POSTHOG_PERSONAL_API_KEY'),

        elevenLabsApiKey: required('ELEVENLABS_API_KEY'),
        elevenLabsVoiceId: optional('ELEVENLABS_VOICE_ID', '21m00Tcm4TlvDq8ikWAM'),
        elevenLabsModelId: optional('ELEVENLABS_MODEL_ID', 'eleven_flash_v2_5'),

        triggerPhrase: optional('TRIGGER_PHRASE', 'hey posthog'),
        bufferSeconds: Number(optional('BUFFER_SECONDS', '90')),
    }
}
