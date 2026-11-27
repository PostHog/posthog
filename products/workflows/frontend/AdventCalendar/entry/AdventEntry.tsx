import { useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { AdventEntryCard } from './AdventEntryCard'
import { adventEntryPhase } from './adventEntryPhase'

export function AdventEntry(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { location } = useValues(router)
    const onCalendar = removeProjectIdIfPresent(location.pathname) === urls.workflowsAdventCalendar()
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR] || onCalendar) {
        return null
    }
    return <AdventEntryCard phase={adventEntryPhase(new Date())} />
}
