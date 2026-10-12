import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { FiltersEditor } from './filters/FiltersEditor'
import { insightSentenceLogic } from './insightSentenceLogic'

/** The filters on the whole insight. The word also shows while the first filter is chosen, and then opens by itself. */
export function SentenceFilters({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { overriddenSlots, filtersPending } = useValues(insightSentenceLogic(insightProps))
    const { removeFilters, setFiltersPending } = useActions(insightSentenceLogic(insightProps))
    const [open, setOpen] = useState(filtersPending)

    useEffect(() => {
        if (filtersPending) {
            setOpen(true)
        }
    }, [filtersPending])

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (!nextOpen && filtersPending) {
                    setFiltersPending(false)
                }
            }}
        >
            <PopoverTrigger
                render={
                    <EditableWord
                        color="green"
                        overridden={overriddenSlots.includes('filters')}
                        onRemove={filtersPending ? undefined : removeFilters}
                        removeLabel="Remove filters"
                        data-attr="quill-insight-sentence-filters"
                    />
                }
            >
                {label}
            </PopoverTrigger>
            <PopoverContent
                align="start"
                aria-label="Filters"
                className="max-h-(--available-height) w-112 max-w-(--available-width) overflow-y-auto"
                data-attr="quill-insight-filters-popover"
            >
                <FiltersEditor insightProps={insightProps} />
            </PopoverContent>
        </Popover>
    )
}
