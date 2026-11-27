import { IconChevronRight } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import type { PagerState } from './aiVisibilityTablePaging'

export function AiVisibilityTablePager({
    page,
    pageSize,
    entryCount,
    entryCountIsLowerBound,
    canGoBack,
    canGoForward,
    onBackward,
    onForward,
}: Omit<PagerState, 'show' | 'slice'> & { onBackward: () => void; onForward: () => void }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-end gap-2">
            {entryCount !== null && entryCount > 0 ? (
                <Text size="xs" variant="muted" render={<span className="m-0 tabular-nums" translate="no" />}>
                    {`${(page - 1) * pageSize + 1}-${Math.min(page * pageSize, entryCount)} of ${entryCount}${entryCountIsLowerBound ? '+' : ''}`}
                </Text>
            ) : null}
            <Button
                size="icon"
                aria-label="Previous page"
                tooltip="Previous page"
                onClick={onBackward}
                disabledReason={canGoBack ? undefined : 'This is the first page'}
            >
                <IconChevronRight className="rotate-180" />
            </Button>
            <Button
                size="icon"
                aria-label="Next page"
                tooltip="Next page"
                onClick={onForward}
                disabledReason={canGoForward ? undefined : 'This is the last page'}
            >
                <IconChevronRight />
            </Button>
        </div>
    )
}
