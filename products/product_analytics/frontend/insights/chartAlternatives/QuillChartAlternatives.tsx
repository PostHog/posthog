import { Button, Popover, PopoverContent, PopoverTrigger, SelectTriggerIcon } from '@posthog/quill'

import { ChartDisplayIcon } from './ChartDisplayIcon'
import type { ChartDisplayOption } from './chartDisplayOptions'

export interface QuillChartAlternativesProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    currentOption: ChartDisplayOption | null | undefined
    disabledReason?: string
    gallery: JSX.Element
}

export function QuillChartAlternatives({
    open,
    onOpenChange,
    currentOption,
    disabledReason,
    gallery,
}: QuillChartAlternativesProps): JSX.Element {
    return (
        <Popover open={open} onOpenChange={onOpenChange}>
            <PopoverTrigger
                render={<Button variant="outline" disabledReason={disabledReason} data-attr="chart-alternatives-all" />}
            >
                {currentOption && <ChartDisplayIcon icon={currentOption.icon} />}
                {currentOption?.label ?? 'Chart type'}
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent
                align="end"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto max-h-(--available-height) overflow-y-auto p-0 scroll-mask-y-4"
            >
                {gallery}
            </PopoverContent>
        </Popover>
    )
}
