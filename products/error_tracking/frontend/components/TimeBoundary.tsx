import { useActions, useValues } from 'kea'
import { MouseEvent, useCallback } from 'react'
import { P, match } from 'ts-pattern'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs } from 'lib/dayjs'

import { DateRange } from '~/schema'

import { errorFiltersLogic } from './ErrorFilters/errorFiltersLogic'

type TimeBoundaryProps = {
    label: string
    time: Dayjs | null | undefined
    loading: boolean
    updateDateRange: (dateRange: DateRange) => DateRange
}

export function TimeBoundary({ time, loading, label, updateDateRange }: TimeBoundaryProps): JSX.Element {
    const { dateRange } = useValues(errorFiltersLogic)
    const { setDateRange } = useActions(errorFiltersLogic)
    const onClick = useCallback(
        (e: MouseEvent): void => {
            setDateRange(updateDateRange(dateRange))
            e.preventDefault()
            e.stopPropagation()
        },
        [dateRange, updateDateRange, setDateRange]
    )
    return (
        <>
            {match([loading, time])
                .with([true, P.any], () => <LemonSkeleton className="h-2 w-[50px]" />)
                .with([false, P.nullish], () => <span className="text-muted text-xs">-</span>)
                .with([false, P.any], () => (
                    <span
                        onClick={onClick}
                        className="hover:bg-fill-button-tertiary-hover flex cursor-pointer items-center rounded px-1"
                    >
                        <TZLabel
                            time={time as Dayjs}
                            className="text-muted border-b border-dotted text-xs"
                            title={label}
                        />
                    </span>
                ))
                .exhaustive()}
        </>
    )
}
