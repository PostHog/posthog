import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingSetupPrompt } from '../components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { errorTrackingImpactSceneLogic } from './errorTrackingImpactSceneLogic'
import { useActions, useValues } from 'kea'
import { LemonEventName } from 'scenes/actions/EventName'
import { Spinner } from '@posthog/lemon-ui'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ErrorTrackingIssueImpactTool } from '../components/IssueImpactTool'

export const scene: SceneExport = {
    component: ErrorTrackingImpactScene,
    logic: errorTrackingImpactSceneLogic,
}

export function ErrorTrackingImpactScene(): JSX.Element | null {
    const { issues, events, issuesLoading } = useValues(errorTrackingImpactSceneLogic)
    const { setEvents } = useActions(errorTrackingImpactSceneLogic)
    const hasIssueCorrelation = useFeatureFlag('ERROR_TRACKING_ISSUE_CORRELATION')

    return hasIssueCorrelation ? (
        <ErrorTrackingSetupPrompt>
            <ErrorTrackingIssueImpactTool />
            <LemonEventName
                value={events && events.length > 0 ? events[0] : null}
                onChange={(event) => setEvents(event ? [event] : [])}
                allEventsOption="clear"
            />
            {issuesLoading ? <Spinner /> : <div>{JSON.stringify(issues)}</div>}
        </ErrorTrackingSetupPrompt>
    ) : null
}
