import { useActions, useValues } from 'kea'

import { addProductIntent } from 'lib/utils/product-intents'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ErrorTrackingRelationalIssue, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

/**
 * Hook to open Max with a prompt to explain an error tracking issue.
 * The tool now accepts issue_id as an argument and fetches the stacktrace from the backend.
 */
export function useErrorTrackingExplainIssueTool(issueId: ErrorTrackingRelationalIssue['id']): {
    openMax: () => void
    isMaxOpen: boolean
} {
    const { openSidePanel } = useActions(sidePanelLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max

    const openMax = (): void => {
        addProductIntent({
            product_type: ProductKey.ERROR_TRACKING,
            intent_context: ProductIntentContext.ERROR_TRACKING_ISSUE_EXPLAINED,
            metadata: { issue_id: issueId },
        })
        openSidePanel(SidePanelTab.Max, `Explain this issue to me`)
    }

    return { openMax, isMaxOpen }
}
