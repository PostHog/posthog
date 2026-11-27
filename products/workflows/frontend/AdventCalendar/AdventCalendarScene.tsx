import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AdventShareButton } from './AdventShareButton'
import { AdventStage } from './AdventStage'

export const scene: SceneExport = {
    component: AdventCalendarScene,
}

export function AdventCalendarScene(): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { featureFlagsTimedOut } = useValues(appLogic)
    const hasCalendar = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]

    useEffect(() => {
        if (receivedFeatureFlags && !hasCalendar) {
            router.actions.replace(urls.workflows())
        }
    }, [receivedFeatureFlags, hasCalendar])

    if ((!receivedFeatureFlags && !featureFlagsTimedOut) || !hasCalendar) {
        return <div className="flex-1" />
    }

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <h1 className="m-0 text-xl font-bold">THE WORKFLOWS ADVENT CALENDAR</h1>
                <AdventShareButton />
            </div>
            <AdventStage />
        </div>
    )
}
