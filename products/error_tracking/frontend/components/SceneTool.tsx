import MaxTool from 'scenes/max/MaxTool'
import { ErrorTrackingSceneToolOutput } from 'queries/schema/schema-foo'
import { errorTrackingSceneLogic } from '../errorTrackingSceneLogic'
import { useValues } from 'kea'

export function ErrorTrackingSceneTool(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)

    const callback = (toolOutput: ErrorTrackingSceneToolOutput): void => {}

    return (
        <MaxTool
            name="search_error_tracking_issues"
            displayName="Filter issues"
            context={{
                current_query: query,
            }}
            callback={(toolOutput: ErrorTrackingSceneToolOutput) => {
                callback(toolOutput)
            }}
            suggestions={[]}
            introOverride={{
                headline: 'Find kind of issues are you looking for?',
                description: 'Search by message, file name, event properties, or stack trace.',
            }}
        >
            <div className="relative" />
        </MaxTool>
    )
}
