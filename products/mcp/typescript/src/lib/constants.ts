import { env } from 'cloudflare:workers'

export const CUSTOM_BASE_URL = env.POSTHOG_BASE_URL || undefined

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'
