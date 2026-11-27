import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { adventCalendarAccessLogic } from './adventCalendarAccessLogic'
import { AdventShareButton } from './AdventShareButton'
import { AdventStage } from './AdventStage'

export const scene: SceneExport = {
    component: AdventCalendarScene,
}

export function AdventCalendarScene(): JSX.Element {
    const { hasCalendar, flagsSettled } = useValues(adventCalendarAccessLogic)
    const { leaveWithoutCalendar } = useActions(adventCalendarAccessLogic)

    useEffect(() => {
        if (flagsSettled && !hasCalendar) {
            leaveWithoutCalendar()
        }
    }, [flagsSettled, hasCalendar, leaveWithoutCalendar])

    if (!flagsSettled || !hasCalendar) {
        return <SpinnerOverlay sceneLevel />
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
