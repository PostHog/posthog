import { z } from 'zod'

import { MCP_SCOPE_PRESET, type McpScopePreset } from '@/lib/scope-preset'

import {
    areaFlag,
    PLACEMENTS,
    type MessagingCtaCopy,
    type MessagingPlacementKey,
} from 'products/workflows/mcp/messagingPlacements'

import type { GuidanceCall } from './engine'
import type { GuidanceProductState } from './product-state'

const scopePresets = Object.values(MCP_SCOPE_PRESET) as [McpScopePreset, ...McpScopePreset[]]

export type GuidanceCondition = (input: {
    call: GuidanceCall
    productState: GuidanceProductState
}) => boolean | Promise<boolean>
type GuidanceText = (call: GuidanceCall) => string
type ExperimentText = (hint: { copy: MessagingCtaCopy; attemptId: string }) => string

const placementKeys = PLACEMENTS.map((placement) => placement.key) as [
    MessagingPlacementKey,
    ...MessagingPlacementKey[],
]

const guidanceRuleShape = z.object({
    id: z.string().regex(/^[a-z0-9-]+$/),
    /** The feature flag that turns the rule on for a caller. Every rule ships off. */
    flag: z.string().min(1),
    trigger: z.object({
        /** Effective tool name (the inner tool for exec calls). A trailing `*` matches a prefix. */
        tool: z.string().min(1).optional(),
        /** A non-call exec verb such as `search`. The effective tool name is `exec` for those. */
        execVerb: z.string().min(1).optional(),
        /** Dot path into the call arguments whose string value `argPattern` must match. */
        argPath: z.string().min(1).optional(),
        argPattern: z.instanceof(RegExp).optional(),
        /** A longer `argPath` value never matches, so `argPattern` only runs on bounded input. */
        argMaxLength: z.number().int().min(1).optional(),
        /** Call arguments that rule the call out when they are set, such as a target outside the project. */
        excludeArgs: z.array(z.string().min(1)).optional(),
        resultEmpty: z.boolean().optional(),
        outcome: z.enum(['any', 'success', 'error']),
        presets: z.array(z.enum(scopePresets)).min(1),
    }),
    /** The notice is shown once the session's matching-call count reaches this. */
    threshold: z.number().int().min(1),
    maxPerSession: z.number().int().min(1),
    /** Once the session has called any of these (same `*` prefix syntax), the rule stays silent. */
    suppressIfCalled: z.array(z.string().min(1)),
    /** Every tool the notice names, so it never points at one the caller's roster lacks. */
    requiresTool: z.array(z.string().min(1)).min(1),
    /** The notice sends the agent to an AI feature, so it is withheld (and stamped) without org consent. */
    requiresAiConsent: z.boolean().optional(),
    /** Runs for every outcome, so `shown` and `flag_off` callers stay comparable. A rejected call is not counted. */
    condition: z.custom<GuidanceCondition>((value) => typeof value === 'function').optional(),
    text: z
        .union([z.string().min(1).max(2000), z.custom<GuidanceText>((value) => typeof value === 'function')])
        .optional(),
    /** Runs the rule as an arm of a placement's experiment: the flag variant decides the outcome, and the text gets an attempt ID. */
    experiment: z
        .object({
            placement: z.enum(placementKeys),
            text: z.custom<ExperimentText>((value) => typeof value === 'function'),
        })
        .optional(),
})

export const guidanceRuleSchema = guidanceRuleShape.superRefine((rule, ctx) => {
    if ((rule.text === undefined) === (rule.experiment === undefined)) {
        ctx.addIssue({ code: 'custom', message: 'A rule needs exactly one of `text` or `experiment`.' })
    }
    const placement = PLACEMENTS.find((candidate) => candidate.key === rule.experiment?.placement)
    if (placement && rule.flag !== areaFlag(placement.area)) {
        ctx.addIssue({
            code: 'custom',
            path: ['flag'],
            message: `Use the placement's area flag ${areaFlag(placement.area)}.`,
        })
    }
})

export type GuidanceRule = z.infer<typeof guidanceRuleSchema>
