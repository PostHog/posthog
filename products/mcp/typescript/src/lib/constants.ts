import { env } from 'cloudflare:workers'

export const DEV = false

export const CUSTOM_BASE_URL = env.POSTHOG_BASE_URL || (DEV ? 'http://localhost:8010' : undefined)

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'
