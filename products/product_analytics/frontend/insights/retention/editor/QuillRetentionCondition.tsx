import { useActions, useValues } from 'kea'
import { toast } from 'react-toastify'

import { Checkbox, Input, Label } from '@posthog/quill'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getRetentionPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { groupsModel } from '~/models/groupsModel'
import { EditorFilterProps, FilterType, RetentionPeriod, RetentionType } from '~/types'

import { AggregationSelect } from 'products/product_analytics/frontend/insights/shared/AggregationSelect'

import { dateOptionPlurals, dateOptions, retentionOptionDescriptions, retentionOptions } from '../constants'
import { retentionLogic } from '../retentionLogic'
import { QuillRetentionCustomBrackets } from './QuillRetentionCustomBrackets'
import {
    actionsTaxonomicGroupTypes,
    filterToRetentionEntity,
    retentionDataWarehousePopoverFields,
    retentionEntityToFilter,
} from './retentionConditionUtils'

export function QuillRetentionCondition({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const { retentionFilter, dateRange } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter, updateDateRange } = useActions(retentionLogic(insightProps))
    const { targetEntity, returningEntity, retentionType, totalIntervals, period, retentionCustomBrackets } =
        retentionFilter || {}
    const periodOptions = dateOptions.map((option) => ({ value: option, label: dateOptionPlurals[option] || option }))

    return (
        <div className="flex flex-col gap-3 mb-4" data-attr="retention-condition">
            <div className="flex items-center gap-2">
                For
                {showGroupsOptions ? (
                    <AggregationSelect insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b>Unique users</b>
                )}
            </div>
            <div>who performed</div>
            <ActionFilter
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                hideRename
                filters={retentionEntityToFilter(targetEntity)}
                setFilters={(newFilters: FilterType) => {
                    updateInsightFilter({ targetEntity: filterToRetentionEntity(newFilters) })
                }}
                typeKey={`${keyForInsightLogicProps('new')(insightProps)}-targetEntity`}
                propertiesTaxonomicGroupTypes={getRetentionPropertyFilterGroupTypes()}
                actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes}
                flagCallsFromFlagEvaluations
                dataWarehousePopoverFields={retentionDataWarehousePopoverFields}
            />
            <div>
                <QuillSelect<string>
                    options={Object.entries(retentionOptions).map(([key, label]) => ({
                        value: key,
                        label,
                        description: retentionOptionDescriptions[key as keyof typeof retentionOptionDescriptions],
                    }))}
                    value={retentionType}
                    onChange={(value) => updateInsightFilter({ retentionType: value as RetentionType })}
                />
            </div>
            <div>and then returned to perform</div>
            <ActionFilter
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                hideRename
                buttonCopy="Add graph series"
                filters={retentionEntityToFilter(returningEntity)}
                setFilters={(newFilters: FilterType) => {
                    updateInsightFilter({ returningEntity: filterToRetentionEntity(newFilters) })
                }}
                typeKey={`${keyForInsightLogicProps('new')(insightProps)}-returningEntity`}
                propertiesTaxonomicGroupTypes={getRetentionPropertyFilterGroupTypes()}
                actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes}
                flagCallsFromFlagEvaluations
                dataWarehousePopoverFields={retentionDataWarehousePopoverFields}
            />
            {!retentionCustomBrackets ? (
                <div className="flex items-center gap-2">
                    <span>during the next</span>
                    <Input
                        type="number"
                        className="w-20"
                        aria-label="Number of periods"
                        defaultValue={(totalIntervals ?? 7) - 1}
                        min={1}
                        max={31}
                        onBlur={({ target }) => {
                            let newValue = Number(target.value)
                            if (newValue > 31) {
                                // Keep the first two digits when someone mashed keys
                                newValue = Number(target.value.substring(0, 2))
                                if (newValue > 31) {
                                    newValue = 10
                                }
                                toast.warn(
                                    <>
                                        The maximum number of {dateOptionPlurals[period || 'Day']} is{' '}
                                        <strong>31</strong>
                                    </>
                                )
                            }
                            target.value = newValue.toString()
                            updateInsightFilter({ totalIntervals: (newValue || 0) + 1 })
                            if (!dateRange) {
                                // A date range set before the interval type changes would otherwise be missing
                                updateDateRange({
                                    date_from: `-7${(period ?? RetentionPeriod.Day)?.toLowerCase().charAt(0)}`,
                                    date_to: `now`,
                                })
                            }
                        }}
                    />
                    <QuillSelect
                        value={period ?? RetentionPeriod.Day}
                        onChange={(value) => {
                            updateInsightFilter({ period: value })
                            // A new interval type resets the date range
                            updateDateRange({
                                date_from: `-7${value.toLowerCase().charAt(0)}`,
                                date_to: `now`,
                            })
                        }}
                        options={periodOptions}
                    />
                </div>
            ) : null}
            <div className="flex items-center gap-2">
                <Checkbox
                    id="retention-custom-brackets"
                    checked={retentionCustomBrackets !== undefined}
                    onCheckedChange={(checked: boolean) =>
                        updateInsightFilter({ retentionCustomBrackets: checked ? [1, 3, 5] : undefined })
                    }
                />
                <Label htmlFor="retention-custom-brackets">Use custom return ranges</Label>
            </div>
            {retentionCustomBrackets !== undefined ? (
                <QuillRetentionCustomBrackets insightProps={insightProps} />
            ) : null}
        </div>
    )
}
