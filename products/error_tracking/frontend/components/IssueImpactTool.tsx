import { useActions } from 'kea'

import MaxTool from 'scenes/max/MaxTool'

import { ErrorTrackingIssueImpactToolOutput } from '~/queries/schema/schema-general'

import { errorTrackingSceneLogic } from '../scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { errorTrackingImpactListLogic } from '../scenes/ErrorTrackingScene/tabs/impact/errorTrackingImpactListLogic'

export function ErrorTrackingIssueImpactTool(): JSX.Element {
    const { setEvents } = useActions(errorTrackingImpactListLogic)
    const { setActiveTab } = useActions(errorTrackingSceneLogic)

    const callback = (toolOutput: ErrorTrackingIssueImpactToolOutput): void => {
        setActiveTab('impact')
        setEvents(toolOutput.events)
    }

    return (
        <MaxTool
            identifier="find_error_tracking_impactful_issue_event_list"
            context={{}}
            callback={callback}
            suggestions={[]}
            introOverride={{
                headline: 'What kind of issues are you looking for?',
                description: 'Search by message, file name, event properties, or stack trace.',
            }}
            className="hidden"
        >
            <div className="relative" />
        </MaxTool>
    )
}
