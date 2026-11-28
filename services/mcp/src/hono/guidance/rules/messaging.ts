import { areaFlag } from 'products/workflows/mcp/messagingPlacements'

import type { GuidanceCall } from '../engine'
import type { GuidanceRule } from '../rule-schema'

const COHORT_FILTER_ON_BEHAVIOR_OR_COHORT = /"type":"(behavioral|cohort)"/

function batchAudienceAccepts(call: GuidanceCall): boolean {
    return (
        call.args?.is_static === true ||
        !COHORT_FILTER_ON_BEHAVIOR_OR_COHORT.test(JSON.stringify(call.args?.filters ?? null))
    )
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
