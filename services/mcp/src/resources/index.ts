import webAnalyticsReadyPrompts from 'products/web_analytics/mcp/ready_prompts/prompts.yaml'

import type { ResourceManifest } from './manifest-types'
import { parseReadyPrompts } from './ready-prompts'

const READY_PROMPT_SOURCES = [webAnalyticsReadyPrompts]

export async function getPromptsFromManifest(): Promise<ResourceManifest['resources']['prompts']> {
    return READY_PROMPT_SOURCES.flatMap((source) => parseReadyPrompts(source))
}
