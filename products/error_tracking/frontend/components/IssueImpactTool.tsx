import { router } from 'kea-router'
import { useActions } from 'node_modules/kea/lib'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'
import { ErrorTrackingIssueImpactToolOutput } from '~/queries/schema/schema-general'
import { errorTrackingImpactSceneLogic } from '../impact/errorTrackingImpactSceneLogic'

export function ErrorTrackingIssueImpactTool(): JSX.Element {
    const { setEvent } = useActions(errorTrackingImpactSceneLogic)

    const callback = (toolOutput: ErrorTrackingIssueImpactToolOutput): void => {
        setEvent(toolOutput.events[0])
        router.actions.push(urls.errorTrackingImpact())
    }

    return (
        <MaxTool
            name="find_error_tracking_impactful_issues"
            displayName="Find impactful issues"
            description="Max can find issues that are affecting signup, activation or any of your events."
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
