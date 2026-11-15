import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { type ModelNaming, modelTierNaming } from './types'

export function useModelNaming(): { fieldLabel: string; naming: ModelNaming } {
    const { featureFlags } = useValues(featureFlagLogic)
    return modelTierNaming(featureFlags[FEATURE_FLAGS.VISION_MODEL_TIER_NAMING])
}
