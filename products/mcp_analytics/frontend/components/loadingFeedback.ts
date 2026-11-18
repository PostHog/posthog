import { cn } from 'lib/utils/css-classes'

// Loads that finish within this window show no loading feedback, so fast refreshes do not flash.
// The delay-200 class in dimWhileLoading must match this value.
export const LOADING_FEEDBACK_DELAY_MS = 200

export function dimWhileLoading(loading: boolean): string {
    return cn('transition-opacity duration-150 ease-out', loading && 'opacity-50 delay-200')
}
