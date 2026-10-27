import { Fragment } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { HogFlowEventFilters, HogFlowFiltersProps } from '../../filters/HogFlowFilters'
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
    const editableEntries = allEntriesEnabled ? entries : entries.slice(0, 1)
    const shownEntries: EventEntry[] = editableEntries.length ? editableEntries : [{}]

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
                                onChange(shownEntries.map((shown, i) => (i === index ? { ...shown, filters } : shown)))
                            }
                        />
                    </Fragment>
                )
            })}
        </div>
    )
}
