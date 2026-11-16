import { z } from 'zod'

import { ERROR_TRACKING_RULES } from './error-tracking'
import { SQL_RULES } from './sql'
import { guidanceRuleSchema, type GuidanceRule } from './types'

export type { GuidanceRule } from './types'
export * from './error-tracking'
export * from './sql'

export const MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG = 'mcp-guidance-error-tracking-sd-activation'

export const GUIDANCE_RULES: readonly GuidanceRule[] = z
    .array(guidanceRuleSchema)
    .parse([...SQL_RULES, ...ERROR_TRACKING_RULES])

export const GUIDANCE_RULE_FLAGS: readonly string[] = [
    ...new Set(GUIDANCE_RULES.map((rule) => rule.flag)),
    MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG,
]
