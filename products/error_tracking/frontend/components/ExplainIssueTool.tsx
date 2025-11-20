import { useValues } from 'kea'

import { IconList } from '@posthog/icons'

import { ProductIntentContext, addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { ErrorTrackingExplainIssueToolContext, ProductKey } from '~/queries/schema/schema-general'

import { useStacktraceDisplay } from '../hooks/use-stacktrace-display'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

export function useErrorTrackingExplainIssueMaxTool(): ReturnType<typeof useMaxTool> {
    const { issueId, issue } = useValues(errorTrackingIssueSceneLogic)

    const { ready, stacktraceText } = useStacktraceDisplay()

    const context: ErrorTrackingExplainIssueToolContext = {
        stacktrace: stacktraceText,
        issue_name: issue?.name ?? issueId,
    }

    const maxToolResult = useMaxTool({
        identifier: 'error_tracking_explain_issue',
        context,
        contextDescription: {
            text: 'Issue stacktrace',
            icon: <IconList />,
        },
        active: ready,
        initialMaxPrompt: `Explain this issue to me`,
        callback() {
            addProductIntent({
                product_type: ProductKey.ERROR_TRACKING,
                intent_context: ProductIntentContext.ERROR_TRACKING_ISSUE_EXPLAINED,
                metadata: { issue_id: issueId },
            })
        },
    })

    return maxToolResult
}
