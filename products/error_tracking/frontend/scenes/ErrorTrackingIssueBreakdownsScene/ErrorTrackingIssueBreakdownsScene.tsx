import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssueSceneLogicProps } from '../ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { BreakdownChart } from './BreakdownChart'
import { BreakdownPresets } from './BreakdownPresets'
import { BreakdownSearchBar } from './BreakdownSearchBar'
import { errorTrackingBreakdownsSceneLogic } from './errorTrackingBreakdownsSceneLogic'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueBreakdownsScene,
    logic: errorTrackingBreakdownsSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export function ErrorTrackingIssueBreakdownsScene({ id }: ErrorTrackingIssueSceneLogicProps): JSX.Element | null {
    const hasBreakdowns = useFeatureFlag('ERROR_TRACKING_BREAKDOWNS')
    const { breakdownQuery, selectedBreakdownPreset } = useValues(errorTrackingBreakdownsSceneLogic)

    if (!hasBreakdowns) {
        return null
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
                <LemonButton
                    type="secondary"
                    icon={<IconArrowLeft />}
                    onClick={() => router.actions.push(`/error_tracking/${id}`)}
                />
                <h1 className="mb-0">Breakdowns</h1>
                <span className="text-muted text-sm">
                    This is a work in progress. Hidden behind a feature flag. Available to posthog employees only for
                    now
                </span>
            </div>

            <div className="flex gap-2">
                <div className="w-[15%]">
                    <BreakdownPresets />
                </div>
                <div className="w-[70%] flex flex-col gap-2">
                    {selectedBreakdownPreset && breakdownQuery && (
                        <>
                            <BreakdownSearchBar />
                            <BreakdownChart />
                        </>
                    )}
                </div>
                <div className="w-[15%]">
                    <div className="border rounded bg-surface-primary overflow-hidden">
                        <div className="text-sm font-semibold p-3 border-b">Some settings</div>
                    </div>
                </div>
            </div>
        </div>
    )
}
