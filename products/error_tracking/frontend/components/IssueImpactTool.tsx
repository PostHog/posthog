import { router } from 'kea-router'
import { useActions } from 'kea'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'
import { ErrorTrackingIssueImpactToolOutput } from '~/queries/schema/schema-general'
import { errorTrackingImpactSceneLogic } from '../impact/errorTrackingImpactSceneLogic'

export function ErrorTrackingIssueImpactTool(): JSX.Element {
    const { setEvent } = useActions(errorTrackingImpactSceneLogic)

    const callback = (toolOutput: ErrorTrackingIssueImpactToolOutput): void => {
        setEvent(toolOutput.issues[0])
        router.actions.push(urls.errorTrackingImpact())
    }

    return (
        <MaxTool
            identifier="find_error_tracking_impactful_issues"
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
