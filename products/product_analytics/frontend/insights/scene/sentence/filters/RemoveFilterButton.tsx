import { IconX } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function RemoveFilterButton({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        aria-label="Remove filter"
                        onClick={onClick}
                        data-attr="quill-insight-filters-remove"
                    />
                }
            >
                <IconX />
            </TooltipTrigger>
            <TooltipContent>Remove filter</TooltipContent>
        </Tooltip>
    )
}
