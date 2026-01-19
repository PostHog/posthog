import { useActions, useValues } from 'kea'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

export interface UseErrorTrackingExplainIssueReturn {
    isMaxOpen: boolean
    openMax: () => void
}

/**
 * Hook to open Max AI side panel with a prompt to explain an error tracking issue.
 * The issue context is automatically provided via the maxContext selector in errorTrackingIssueSceneLogic.
 */
export function useErrorTrackingExplainIssue(): UseErrorTrackingExplainIssueReturn {
    const { openSidePanel } = useActions(sidePanelLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)

    return {
        isMaxOpen: sidePanelOpen && selectedTab === SidePanelTab.Max,
        openMax: () => openSidePanel(SidePanelTab.Max, 'Explain this issue to me'),
    }
}
