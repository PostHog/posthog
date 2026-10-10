import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'
import { SplitPickerPopover } from './SplitPickerPopover'

const BIN_COUNTS = [5, 10, 20, 50, 100]
const LIMITS = [5, 10, 25, 50, 100]
const DEFAULT_LIMIT = 25
const MAX_SPLITS = 3

interface SplitDetails {
    value: string | number
    type: string
    /** Set when the property is a number that the chart groups into ranges. */
    bins: number | null
}

function splitAt(breakdownFilter: BreakdownFilter | null | undefined, splitIndex: number): SplitDetails | null {
    const split = breakdownFilter?.breakdowns?.[splitIndex]
    if (split) {
        return { value: split.property, type: split.type ?? 'event', bins: split.histogram_bin_count ?? null }
    }
    const breakdown = breakdownFilter?.breakdown
    if (splitIndex === 0 && (typeof breakdown === 'string' || typeof breakdown === 'number')) {
        return {
            value: breakdown,
            type: breakdownFilter?.breakdown_type ?? 'event',
            bins: breakdownFilter?.breakdown_histogram_bin_count ?? null,
        }
    }
    return null
}

export function SentenceSplit({
    insightProps,
    splitIndex,
    label,
}: {
    insightProps: InsightLogicProps
    splitIndex: number
    label: string
}): JSX.Element {
    const { trendsQuery, overriddenSlots } = useValues(insightSentenceLogic(insightProps))
    const { changeSplitBins, changeSplitLimit, removeSplit, removeSplitAt } = useActions(
        insightSentenceLogic(insightProps)
    )
    // The same picker either replaces this split or adds one after it.
    const [adding, setAdding] = useState(false)
    const breakdownFilter = trendsQuery?.breakdownFilter
    const split = splitAt(breakdownFilter, splitIndex)
    const splitCount = breakdownFilter?.breakdowns?.length ?? (split ? 1 : 0)

    return (
        <SplitPickerPopover
            insightProps={insightProps}
            breakdownType={adding ? undefined : split?.type}
            breakdownValue={adding ? undefined : split?.value}
            trigger={(_, toggle) => (
                <span>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <EditableWord
                                    color="green"
                                    overridden={overriddenSlots.includes('split')}
                                    data-attr="quill-insight-sentence-split"
                                />
                            }
                        >
                            {label}
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="min-w-56">
                            <DropdownMenuItem
                                onClick={() => {
                                    setAdding(false)
                                    toggle()
                                }}
                            >
                                Change property
                            </DropdownMenuItem>
                            {splitCount < MAX_SPLITS && (
                                <DropdownMenuItem
                                    onClick={() => {
                                        setAdding(true)
                                        toggle()
                                    }}
                                >
                                    Add another split
                                </DropdownMenuItem>
                            )}
                            {split?.bins != null && (
                                <DropdownMenuSub>
                                    <DropdownMenuSubTrigger>Number of ranges</DropdownMenuSubTrigger>
                                    <DropdownMenuSubContent className="min-w-40">
                                        <DropdownMenuRadioGroup
                                            value={String(split.bins)}
                                            onValueChange={(value: string) =>
                                                changeSplitBins(splitIndex, Number(value))
                                            }
                                        >
                                            {BIN_COUNTS.map((count) => (
                                                <DropdownMenuRadioItem key={count} value={String(count)}>
                                                    {`${count} ranges`}
                                                </DropdownMenuRadioItem>
                                            ))}
                                        </DropdownMenuRadioGroup>
                                    </DropdownMenuSubContent>
                                </DropdownMenuSub>
                            )}
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>Values to show</DropdownMenuSubTrigger>
                                <DropdownMenuSubContent className="min-w-40">
                                    <DropdownMenuRadioGroup
                                        value={String(breakdownFilter?.breakdown_limit ?? DEFAULT_LIMIT)}
                                        onValueChange={(value: string) => changeSplitLimit(Number(value))}
                                    >
                                        {LIMITS.map((limit) => (
                                            <DropdownMenuRadioItem key={limit} value={String(limit)}>
                                                {`Top ${limit}`}
                                            </DropdownMenuRadioItem>
                                        ))}
                                    </DropdownMenuRadioGroup>
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => (splitCount > 1 ? removeSplitAt(splitIndex) : removeSplit())}
                            >
                                Remove this split
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </span>
            )}
        />
    )
}
