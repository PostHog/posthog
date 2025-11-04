import { useActions, useValues } from 'kea'

import MaxTool from 'scenes/max/MaxTool'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { ErrorTrackingIssueImpactToolOutput } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { errorTrackingSceneLogic } from '../scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { errorTrackingImpactListLogic } from '../scenes/ErrorTrackingScene/tabs/impact/errorTrackingImpactListLogic'

export function ErrorTrackingExplainIssueTool(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)

    return useMaxTool({
        identifier: 'explain_error_tracking_issue_cause',
        context: { issueId },
        // suggestions,
        // active,
        // initialMaxPrompt,
        // onMaxOpen,
    })

    return <></>

    // return (
    //     <MaxTool
    //         identifier="find_error_tracking_impactful_issue_event_list"
    //         context={{}}
    //         callback={callback}
    //         suggestions={[]}
    //         introOverride={{
    //             headline: 'What kind of issues are you looking for?',
    //             description: 'Search by message, file name, event properties, or stack trace.',
    //         }}
    //         className="hidden"
    //     >
    //         <div className="relative" />
    //     </MaxTool>
    // )
}
