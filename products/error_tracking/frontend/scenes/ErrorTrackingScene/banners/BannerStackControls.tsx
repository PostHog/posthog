import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { Button, Text } from 'lib/ui/quill'

export function BannerStackControls({
    index,
    total,
    onPrevious,
    onNext,
}: {
    index: number
    total: number
    onPrevious: () => void
    onNext: () => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <Button
                variant="default"
                size="icon-sm"
                aria-label="Previous recommendation"
                tooltip="Previous recommendation"
                disabledReason={index <= 0 ? 'This is the first recommendation' : undefined}
                onClick={onPrevious}
                data-attr="error-tracking-banners-previous"
            >
                <IconChevronLeft />
            </Button>
            <Text size="xs" variant="muted" className="tabular-nums">
                {`${index + 1} of ${total}`}
            </Text>
            <Button
                variant="default"
                size="icon-sm"
                aria-label="Next recommendation"
                tooltip="Next recommendation"
                disabledReason={index >= total - 1 ? 'This is the last recommendation' : undefined}
                onClick={onNext}
                data-attr="error-tracking-banners-next"
            >
                <IconChevronRight />
            </Button>
        </div>
    )
}
