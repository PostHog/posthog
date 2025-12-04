import { IconList } from '@posthog/icons'

import { addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import {
    ErrorTrackingExplainIssueToolContext,
    ErrorTrackingRelationalIssue,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'

import { useStacktraceDisplay } from '../hooks/use-stacktrace-display'

export function useErrorTrackingExplainIssueMaxTool(
    issueId: ErrorTrackingRelationalIssue['id'],
    issueName: ErrorTrackingRelationalIssue['name']
): ReturnType<typeof useMaxTool> {
    const { ready, stacktraceText } = useStacktraceDisplay()

    const context: ErrorTrackingExplainIssueToolContext = {
        stacktrace: stacktraceText,
        issue_name: issueName ?? issueId,
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
