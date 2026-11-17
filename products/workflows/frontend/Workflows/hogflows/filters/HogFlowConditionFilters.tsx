import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { HogFlowAction } from '../types'
import {
    ConditionFilterGroup,
    ConditionFilterGroups,
    fromConditionFilterGroups,
    isConditionFilterGroups,
    toConditionFilterGroups,
} from './conditionFilterGroups'
import { HogFlowPropertyFilters } from './HogFlowFilters'

export type ConditionFilters = Extract<
    HogFlowAction,
    { type: 'conditional_branch' }
>['config']['conditions'][number]['filters']

export type HogFlowConditionFiltersProps = {
    filtersKey: string
    filters: ConditionFilters
    setFilters: (filters: ConditionFilters) => void
}

/** The filters of one conditional branch condition, as AND/OR groups of property filters. */
export function HogFlowConditionFilters({
    filtersKey,
    filters,
    setFilters,
}: HogFlowConditionFiltersProps): JSX.Element {
    const filterGroupsEnabled = useFeatureFlag('WORKFLOWS_CONDITION_FILTER_GROUPS')
    const properties = filters?.properties as AnyPropertyFilter[] | ConditionFilterGroups | undefined

    // A condition saved with groups keeps the group editor when the flag is off, because the flat
    // editor cannot show a group and saving from it would lose the condition.
    if (!filterGroupsEnabled && !isConditionFilterGroups(properties)) {
        return (
            <HogFlowPropertyFilters
                filtersKey={filtersKey}
                includeCohorts
                filters={filters as HogFlowAction['filters']}
                setFilters={(next) => setFilters(next ?? {})}
            />
        )
    }

    const groups = toConditionFilterGroups(properties)

    const setGroups = (next: ConditionFilterGroups): void => {
        setFilters({ ...filters, properties: fromConditionFilterGroups(next) } as ConditionFilters)
    }
    const setGroup = (index: number, group: ConditionFilterGroup): void => {
        setGroups({ ...groups, values: groups.values.map((existing, i) => (i === index ? group : existing)) })
    }

    return (
        <div className="flex flex-col gap-2">
            {groups.values.length > 1 && (
                <AndOrFilterSelect
                    value={groups.type}
                    onChange={(type) => setGroups({ ...groups, type })}
                    topLevelFilter
                    suffix={['group', 'groups']}
                />
            )}
            {groups.values.map((group, index) => (
                <div key={index} className="flex flex-col gap-2">
                    {index > 0 && <div className="text-xs font-semibold text-secondary">{groups.type}</div>}
                    <div className="flex flex-col gap-2 rounded border p-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <AndOrFilterSelect
                                value={group.type}
                                onChange={(type) => setGroup(index, { ...group, type })}
                            />
                            {groups.values.length > 1 && (
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    tooltip="Remove filter group"
                                    data-attr="hog-flow-condition-remove-filter-group"
                                    onClick={() =>
                                        setGroups({ ...groups, values: groups.values.filter((_, i) => i !== index) })
                                    }
                                />
                            )}
                        </div>
                        <HogFlowPropertyFilters
                            filtersKey={`${filtersKey}-group-${index}`}
                            includeCohorts
                            filters={{ properties: group.values }}
                            setFilters={(groupFilters) =>
                                setGroup(index, { ...group, values: groupFilters?.properties ?? [] })
                            }
                            propertyGroupType={group.type}
                        />
                    </div>
                </div>
            ))}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlusSmall />}
                    data-attr="hog-flow-condition-add-filter-group"
                    onClick={() =>
                        setGroups({
                            ...groups,
                            values: [...groups.values, { type: FilterLogicalOperator.And, values: [] }],
                        })
                    }
                >
                    Add filter group
                </LemonButton>
            </div>
        </div>
    )
}
