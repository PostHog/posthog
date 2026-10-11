import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { FiltersEditor } from './filters/FiltersEditor'
import type { FiltersTarget } from './filters/filtersTarget'
import { insightSentenceLogic } from './insightSentenceLogic'

/** The filters on one event. The word also shows while the first filter is chosen, and then opens by itself. */
export function SentenceSeriesFilters({
    insightProps,
    seriesIndex,
    label,
}: {
    insightProps: InsightLogicProps
    seriesIndex: number
    label: string
}): JSX.Element {
    const { pendingFilterSeriesIndex } = useValues(insightSentenceLogic(insightProps))
    const { removeSeriesFilters, setPendingFilterSeriesIndex } = useActions(insightSentenceLogic(insightProps))
    const isPending = pendingFilterSeriesIndex === seriesIndex
    const [open, setOpen] = useState(isPending)
    const target = useMemo((): FiltersTarget => ({ kind: 'series', seriesIndex }), [seriesIndex])

    useEffect(() => {
        if (isPending) {
            setOpen(true)
        }
    }, [isPending])

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (!nextOpen && isPending) {
                    setPendingFilterSeriesIndex(null)
                }
            }}
        >
            <PopoverTrigger
                render={
                    <EditableWord
                        color="green"
                        onRemove={isPending ? undefined : () => removeSeriesFilters(seriesIndex)}
                        removeLabel="Remove these filters"
                        data-attr="quill-insight-sentence-series-filters"
                    />
                }
            >
                {label}
            </PopoverTrigger>
            <PopoverContent
                align="start"
                aria-label="Filters on this event"
                className="max-h-(--available-height) w-112 max-w-(--available-width) overflow-y-auto"
                data-attr="quill-insight-series-filters-popover"
            >
                <FiltersEditor insightProps={insightProps} target={target} />
            </PopoverContent>
        </Popover>
    )
}
