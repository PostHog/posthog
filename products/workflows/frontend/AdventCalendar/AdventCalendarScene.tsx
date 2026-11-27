import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { AdventShareButton } from './AdventShareButton'
import { AdventStage } from './AdventStage'

export const scene: SceneExport = {
    component: AdventCalendarScene,
}

export function AdventCalendarScene(): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { featureFlagsTimedOut } = useValues(appLogic)

    if (!receivedFeatureFlags && !featureFlagsTimedOut) {
        return <div className="flex-1" />
    }
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]) {
        return <NotFound object="page" />
    }

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <h1 className="m-0 text-xl font-bold">A very merry PostHog</h1>
                <AdventShareButton />
            </div>
            <AdventStage />
        </div>
    )
}
