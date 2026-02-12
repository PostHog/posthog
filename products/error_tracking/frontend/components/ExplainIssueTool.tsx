import { useOpenAi } from 'scenes/max/useOpenAi'

export interface UseErrorTrackingExplainIssueReturn {
    isMaxOpen: boolean
    openMax: () => void
}

/**
 * Hook to open Max AI side panel with a prompt to explain an error tracking issue.
 * In side panel mode, the issue context is automatically provided via the maxContext selector.
 * In new tab mode, the issue ID is passed for context restoration.
 *
 * @param issueId - The error tracking issue ID to explain
 */
export function useErrorTrackingExplainIssue(issueId: string): UseErrorTrackingExplainIssueReturn {
    const { isMaxOpen, openAi } = useOpenAi()

    return {
        isMaxOpen,
        openMax: () =>
            openAi('Explain this issue to me', {
                errorTrackingIssue: { id: issueId },
            }),
    }
}
