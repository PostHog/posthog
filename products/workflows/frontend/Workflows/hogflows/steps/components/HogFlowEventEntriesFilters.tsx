import { Fragment } from 'react'

import { HogFlowEventFilters, HogFlowFiltersProps } from '../../filters/HogFlowFilters'
import { EventEntry } from './cohortMembershipEvent'

export interface HogFlowEventEntriesFiltersProps extends Pick<
    HogFlowFiltersProps,
    'buttonCopy' | 'excludeGroupProperties'
> {
    entries: EventEntry[]
    onChange: (entries: EventEntry[]) => void
    filtersKey: string
    typeKey: string
}

export function HogFlowEventEntriesFilters({
    entries,
    onChange,
    filtersKey,
    typeKey,
    ...filterProps
}: HogFlowEventEntriesFiltersProps): JSX.Element {
    const shownEntries: EventEntry[] = entries.length ? entries : [{}]

    return (
        <div className="flex flex-col gap-2 items-start w-full">
            {shownEntries.map((entry, index) => (
                <Fragment key={index}>
                    {index > 0 ? <span className="text-xs text-tertiary uppercase tracking-wide">or</span> : null}
                    <HogFlowEventFilters
                        {...filterProps}
                        filtersKey={`${filtersKey}-${index}`}
                        typeKey={`${typeKey}-${index}`}
                        filters={entry.filters ?? {}}
                        setFilters={(filters) =>
                            onChange(shownEntries.map((shown, i) => (i === index ? { ...shown, filters } : shown)))
                        }
                    />
                </Fragment>
            ))}
        </div>
    )
}
