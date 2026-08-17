import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ANALYSIS_NUDGE_THRESHOLD, analysisNudgeLogic } from '../logics/analysisNudgeLogic'
import { AnalysisNudge } from './AnalysisNudge'

// The nudge hides without scanner editor access; grant it on the storybook app context before
// the story mounts and restore the original on unmount so story order can't leak. Persisted
// suppressions are cleared here too, before the logic's persisted reducers read them on mount.
const grantScannerAccess: Decorator = function GrantScannerAccess(Story): JSX.Element {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const original = useRef<{ value: unknown }>()
    if (appContext && !original.current) {
        original.current = { value: appContext.resource_access_control }
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
            [AccessControlResourceType.SessionRecording]: AccessControlLevel.Editor,
        }
        localStorage.removeItem('products.replay_vision.frontend.logics.analysisNudgeLogic.suppressed')
        localStorage.removeItem('products.replay_vision.frontend.logics.analysisNudgeLogic.lastShownAt')
    }
    useEffect(
        () => () => {
            if (appContext && original.current) {
                appContext.resource_access_control = original.current.value
            }
        },
        [appContext]
    )
    return <Story />
}

const meta: Meta<typeof AnalysisNudge> = {
    title: 'Replay Vision/Analysis nudge',
    component: AnalysisNudge,
    decorators: [
        grantScannerAccess,
        // The nudge only shows for teams without scanners, checked against this endpoint.
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_ANALYSIS_NUDGE]: true },
    },
}
export default meta

function PrimedNudge(): JSX.Element {
    const logic = useMountedLogic(analysisNudgeLogic)
    useEffect(() => {
        for (let i = 0; i < ANALYSIS_NUDGE_THRESHOLD; i++) {
            logic.actions.recordingAnalyzed(`story-recording-${i}`)
        }
    }, [logic])
    return (
        // Stands in for the player area the card overlays in the app. An explicit width matters:
        // the card is absolutely positioned, so without one the wrapper collapses to its borders
        // and the visual-regression snapshot captures a 2px sliver instead of the card.
        <div className="relative h-80 w-160 border rounded">
            <AnalysisNudge />
        </div>
    )
}

export const Default: StoryObj = {
    render: () => <PrimedNudge />,
}
