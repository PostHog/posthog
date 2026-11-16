import { z } from 'zod'

import { guidanceRuleSchema, type GuidanceRule } from '../rule-schema'
import errorTracking from './error-tracking'
import sql from './sql'

export type { GuidanceRule } from '../rule-schema'
export * from './error-tracking'
export * from './sql'

export const MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG = 'mcp-guidance-error-tracking-sd-activation'

export const GUIDANCE_RULES: readonly GuidanceRule[] = z.array(guidanceRuleSchema).parse([...sql, ...errorTracking])

export const GUIDANCE_RULE_FLAGS: readonly string[] = [
    ...new Set(GUIDANCE_RULES.map((rule) => rule.flag)),
    MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG,
]
