import { useActions, useValues } from 'kea'

import { maxContextLogic } from 'scenes/max/maxContextLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export interface UseErrorTrackingExplainIssueReturn {
    isMaxOpen: boolean
    openMax: () => void
}

/**
 * Hook to open the Max AI side panel with a prompt to explain an error tracking issue.
 * The issue is added to Max's context so the explanation is grounded in the current issue.
 *
 * @param issueId - The error tracking issue ID to explain
 */
export function useErrorTrackingExplainIssue(issueId: string): UseErrorTrackingExplainIssueReturn {
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { addOrUpdateContextErrorTrackingIssue } = useActions(maxContextLogic)

    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max

    return {
        isMaxOpen,
        openMax: () => {
            addOrUpdateContextErrorTrackingIssue({ id: issueId })
            // Leading "!" auto-runs the prompt once the side panel opens.
            openSidePanel(SidePanelTab.Max, '!Explain this issue to me')
        },
    }
}
