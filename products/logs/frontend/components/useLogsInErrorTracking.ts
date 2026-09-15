import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

// Every logs entry point inside error tracking is behind one flag, so the button in the exception
// card header and the Logs tab beside it can never appear without each other.
export function useLogsInErrorTracking(): boolean {
    return useFeatureFlag('LOGS_IN_ERROR_TRACKING')
}
