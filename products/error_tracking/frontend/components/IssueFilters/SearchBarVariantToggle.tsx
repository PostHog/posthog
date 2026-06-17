import { useActions, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { searchBarVariantLogic } from './searchBarVariantLogic'

/**
 * Whether to render the redesigned (v2) filter bar: the flag must be enabled and the user must not
 * have flipped back to the legacy (v1) layout. Without the flag the legacy bar always wins.
 */
export const useErrorTrackingSearchBarRedesign = (): boolean => {
    const hasRedesign = useFeatureFlag('ERROR_TRACKING_SEARCH_BAR_REDESIGN')
    const { variant } = useValues(searchBarVariantLogic)
    return hasRedesign && variant === 'v2'
}

/** Small circle pinned to the top-right of the filter bar that flips between v1 and v2 layouts. */
export const SearchBarVariantToggle = ({ className }: { className?: string }): JSX.Element | null => {
    const hasRedesign = useFeatureFlag('ERROR_TRACKING_SEARCH_BAR_REDESIGN')
    const { variant } = useValues(searchBarVariantLogic)
    const { toggleVariant } = useActions(searchBarVariantLogic)

    if (!hasRedesign) {
        return null
    }

    const other = variant === 'v2' ? 'v1' : 'v2'

    return (
        <Tooltip title={`Switch to ${other} search bar`}>
            <button
                type="button"
                onClick={toggleVariant}
                className={cn(
                    'absolute -top-2 -right-2 z-10 flex h-5 w-5 items-center justify-center rounded-full border bg-surface-primary text-[10px] font-semibold text-muted shadow-sm hover:text-default',
                    className
                )}
            >
                {variant}
            </button>
        </Tooltip>
    )
}
