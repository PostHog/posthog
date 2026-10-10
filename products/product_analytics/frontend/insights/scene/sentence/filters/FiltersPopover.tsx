import { useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { FiltersEditor } from './FiltersEditor'
import type { FiltersTarget } from './filtersTarget'

export interface FiltersPopoverProps {
    insightProps: InsightLogicProps
    /** The filters to edit. The filters of the whole insight when not set. */
    target?: FiltersTarget
    trigger: (open: boolean, toggle: () => void) => JSX.Element
}

export function FiltersPopover({ insightProps, target, trigger }: FiltersPopoverProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <Popover open={open} onOpenChange={(nextOpen) => setOpen(nextOpen)}>
            {/* The popover also toggles on a trigger click. `toggle` sets the same value, so the two agree. */}
            <PopoverTrigger render={trigger(open, () => setOpen(!open))} />
            <PopoverContent
                align="start"
                aria-label={target?.kind === 'series' ? 'Filters on this event' : 'Filters'}
                className="max-h-(--available-height) w-112 max-w-(--available-width) overflow-y-auto"
                data-attr="quill-insight-filters-popover"
            >
                <FiltersEditor insightProps={insightProps} target={target} />
            </PopoverContent>
        </Popover>
    )
}
