import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AdventEntryCard } from './AdventEntryCard'

export function AdventEntry(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR] ? <AdventEntryCard /> : null
}
