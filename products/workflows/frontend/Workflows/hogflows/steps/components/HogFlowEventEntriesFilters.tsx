import { Fragment } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { HogFlowEventFilters, HogFlowFiltersProps, HogFlowPropertyFilters } from '../../filters/HogFlowFilters'
import { EventEntry } from './cohortMembershipEvent'

export interface HogFlowEventEntriesFiltersProps extends Pick<
    HogFlowFiltersProps,
    'buttonCopy' | 'excludeGroupProperties'
> {
    entries: EventEntry[]
    onChange: (entries: EventEntry[]) => void
    typeKey: string
}

export function HogFlowEventEntriesFilters({
    entries,
    onChange,
    typeKey,
    ...filterProps
}: HogFlowEventEntriesFiltersProps): JSX.Element {
    const allEntriesEnabled = useFeatureFlag('WORKFLOWS_GOAL_EVENT_ENTRIES')

    if (!allEntriesEnabled) {
        return (
            <HogFlowEventFilters
                {...filterProps}
                filtersKey={typeKey}
                typeKey={typeKey}
                filters={entries[0]?.filters ?? {}}
                setFilters={(filters) => onChange(filters ? [{ filters }] : [])}
            />
        )
    }

    const shownEntries: EventEntry[] = entries.length ? entries : [{}]
    const replaceEntry = (index: number, nextEntry: EventEntry): void =>
        onChange(shownEntries.map((entry, i) => (i === index ? nextEntry : entry)))

    return (
        <div className="flex flex-col gap-2 items-start w-full">
            {shownEntries.map((entry, index) => {
                const entryTypeKey = `${typeKey}-${index}`
                return (
                    <Fragment key={index}>
                        {index > 0 ? <span className="text-xs text-tertiary uppercase tracking-wide">or</span> : null}
                        <HogFlowEventFilters
                            {...filterProps}
                            filtersKey={entryTypeKey}
                            typeKey={entryTypeKey}
                            filters={entry.filters ?? {}}
                            setFilters={(filters) =>
                                replaceEntry(index, { ...entry, filters: { ...entry.filters, ...filters } })
                            }
                        />
                        {entry.filters?.properties?.length ? (
                            <HogFlowPropertyFilters
                                filtersKey={`${entryTypeKey}-properties`}
                                filters={entry.filters}
                                setFilters={(filters) =>
                                    replaceEntry(index, {
                                        ...entry,
                                        filters: { ...entry.filters, properties: filters?.properties ?? [] },
                                    })
                                }
                                excludeGroupProperties={filterProps.excludeGroupProperties}
                            />
                        ) : null}
                    </Fragment>
                )
            })}
        </div>
    )
}
