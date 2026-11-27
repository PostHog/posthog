import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

// pinned: the dismiss key is the localStorage key that keeps the banner closed. Renaming it shows the banner again.
const DISMISS_KEY = 'workflows-advent-calendar-banner'

export function AdventCalendarBanner(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            dismissKey={DISMISS_KEY}
            action={{
                children: 'Open the calendar',
                to: urls.workflowsAdventCalendar(),
                'data-attr': 'advent-banner-open',
            }}
        >
            The Workflows advent calendar is open. Until December 24, a new door each day shows a hedgehog and a
            Workflows tip.
        </LemonBanner>
    )
}
