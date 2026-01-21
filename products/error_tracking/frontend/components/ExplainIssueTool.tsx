import { useOpenAi } from 'scenes/max/useOpenAi'

export interface UseErrorTrackingExplainIssueReturn {
    isMaxOpen: boolean
    openMax: () => void
}

/**
 * Hook to open Max AI side panel with a prompt to explain an error tracking issue.
 * The issue context is automatically provided via the maxContext selector in errorTrackingIssueSceneLogic.
 */
export function useErrorTrackingExplainIssue(): UseErrorTrackingExplainIssueReturn {
    const { isMaxOpen, openAi } = useOpenAi()

    return {
        isMaxOpen,
        openMax: () => openAi('Explain this issue to me'),
    }
}
