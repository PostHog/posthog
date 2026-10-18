import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import type { TeamType } from '~/types'

type TeamIntents = Pick<TeamType, 'product_intents'> | null

function isInFirstWorkflowCardAudience(team: TeamIntents): boolean {
    const productIntents = team?.product_intents
    return !!productIntents && !productIntents.some((intent) => intent.product_type === ProductKey.WORKFLOWS)
}

export function firstWorkflowCardVariant(team: TeamIntents, featureFlags: FeatureFlagsSet): string | null {
    if (!isInFirstWorkflowCardAudience(team)) {
        return null
    }
    const variant = featureFlags[FEATURE_FLAGS.WORKFLOWS_FIRST_WORKFLOW_CARD]
    return typeof variant === 'string' ? variant : null
}
