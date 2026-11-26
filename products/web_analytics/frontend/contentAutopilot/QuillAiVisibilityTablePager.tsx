import { IconChevronRight } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

export function QuillAiVisibilityTablePager({
    page,
    pageSize,
    entryCount,
    canGoBack,
    canGoForward,
    onBackward,
    onForward,
}: {
    page: number
    pageSize: number
    entryCount: number
    canGoBack: boolean
    canGoForward: boolean
    onBackward: () => void
    onForward: () => void
}): JSX.Element {
    return (
        <div className="flex items-center justify-end gap-2">
            <Text size="xs" variant="muted" render={<span />}>
                {`${(page - 1) * pageSize + 1}-${Math.min(page * pageSize, entryCount)} of ${entryCount}`}
            </Text>
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
