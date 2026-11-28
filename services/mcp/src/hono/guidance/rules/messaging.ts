import { areaFlag } from 'products/workflows/mcp/messagingPlacements'

import type { GuidanceCall } from '../engine'
import type { GuidanceRule } from '../rule-schema'

const LEAF_TYPES_A_BATCH_AUDIENCE_REJECTS = new Set(['behavioral', 'cohort'])

function isStaticCohort(args: Record<string, unknown>): boolean {
    if ('is_static' in args) {
        return args.is_static === true
    }
    return Object.entries(args).some(
        ([key, value]) => key.replace(/[_-]/g, '').toLowerCase() === 'isstatic' && value === true
    )
}

function hasLeafABatchAudienceRejects(node: unknown): boolean {
    if (Array.isArray(node)) {
        return node.some(hasLeafABatchAudienceRejects)
    }
    if (typeof node !== 'object' || node === null) {
        return false
    }
    const { type, values } = node as { type?: unknown; values?: unknown }
    return Array.isArray(values)
        ? hasLeafABatchAudienceRejects(values)
        : typeof type === 'string' && LEAF_TYPES_A_BATCH_AUDIENCE_REJECTS.has(type)
}

function batchAudienceAccepts({ args }: GuidanceCall): boolean {
    if (!args) {
        return false
    }
    const filters = args.filters as { properties?: unknown } | undefined
    return isStaticCohort(args) || !hasLeafABatchAudienceRejects(filters?.properties)
}

const rules: GuidanceRule[] = [
    {
        id: 'cohorts-create-messaging',
        flag: areaFlag('mcp'),
        trigger: { tool: 'cohorts-create', outcome: 'success', presets: ['user'] },
        threshold: 1,
        maxPerSession: 1,
        suppressIfCalled: ['broadcasts-create', 'workflows-create'],
        requiresTool: ['broadcasts-create'],
        condition: ({ call }) => batchAudienceAccepts(call),
        experiment: {
            placement: 'mcp.after_cohorts_create',
            text: ({ attemptId }) =>
                'You can offer the user an email to the people in the cohort this call returned. ' +
                'They review and launch it in the broadcast editor. ' +
                'If they want it, call broadcasts-create with a batch trigger on that cohort, ' +
                `and pass entry_attempt_id: "${attemptId}".`,
        },
    },
]

export default rules
