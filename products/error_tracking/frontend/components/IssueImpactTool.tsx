import { useActions } from 'kea'
import { router } from 'kea-router'

import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssueImpactToolOutput } from '~/queries/schema/schema-general'

import { errorTrackingImpactListLogic } from '../scenes/ErrorTrackingScene/tabs/impact/errorTrackingImpactListLogic'

export function ErrorTrackingIssueImpactTool(): JSX.Element {
    const { setEvents } = useActions(errorTrackingImpactListLogic)

    const callback = (toolOutput: ErrorTrackingIssueImpactToolOutput): void => {
        setEvents(toolOutput.events)
        router.actions.push(urls.errorTrackingImpact())
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
