import { BindLogic, useActions, useValues } from 'kea'
import { memo, useCallback, useMemo, useRef, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonDivider, LemonDropdown, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { SeverityLevelsFilter } from 'products/logs/frontend/components/LogsViewer/Filters/SeverityLevelsFilter'
import { ThresholdOperatorEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertFormLogic } from './logsAlertFormLogic'

const WINDOW_OPTIONS = [
    { value: 5, label: '5 minutes' },
    { value: 10, label: '10 minutes' },
    { value: 15, label: '15 minutes' },
    { value: 30, label: '30 minutes' },
    { value: 60, label: '60 minutes' },
]

const taxonomicFilterLogicKey = 'logs-alert'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Logs,
    TaxonomicFilterGroupType.LogResourceAttributes,
    TaxonomicFilterGroupType.LogAttributes,
]

function buildCheckPattern(datapoints: number, periods: number): boolean[] {
    // Last check is always matched — it's the one that tips the alert over.
    // Distribute OK checks evenly across the remaining positions.
    const result: boolean[] = Array(periods).fill(true)
    const okCount = periods - datapoints
    for (let i = 0; i < okCount; i++) {
        const pos = Math.round((i * (periods - 2)) / Math.max(okCount - 1, 1))
        result[pos] = false
    }
    return result
}

function CheckDots({ checks }: { checks: boolean[] }): JSX.Element {
    return (
        <>
            {checks.map((matched, i) => (
                <div
                    key={i}
                    className={`w-3 h-3 rounded-full border ${
                        matched ? 'bg-danger-highlight border-danger' : 'bg-success-highlight border-success'
                    }`}
                    title={`Check ${i + 1}: ${matched ? 'matched' : 'ok'}`}
                />
            ))}
        </>
    )
}

function CheckDotsTooltip({ datapoints, periods }: { datapoints: number; periods: number }): JSX.Element {
    const checks = useMemo(() => buildCheckPattern(datapoints, periods), [datapoints, periods])

    return (
        <Tooltip
            title={
                <div className="space-y-1 py-0.5">
                    <div className="text-xs">
                        {datapoints} of {periods} checks must match to fire
                    </div>
                    <div className="flex items-center gap-1.5">
                        <CheckDots checks={checks} />
                        <span className="text-xs">→</span>
                        <span className="text-xs font-semibold text-danger">fires</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-secondary">
                        <span className="inline-flex items-center gap-1">
                            <span className="inline-block w-2 h-2 rounded-full bg-danger-highlight border border-danger" />
                            matched
                        </span>
                        <span className="inline-flex items-center gap-1">
                            <span className="inline-block w-2 h-2 rounded-full bg-success-highlight border border-success" />
                            OK
                        </span>
                    </div>
                </div>
            }
        >
            <IconInfo className="text-base text-secondary" />
        </Tooltip>
    )
}

export function LogsAlertForm(): JSX.Element {
    const { alertForm } = useValues(logsAlertFormLogic)
    const { setAlertFormValue } = useActions(logsAlertFormLogic)

    const handleFilterGroupChange = useCallback(
        (group: UniversalFiltersGroup) => setAlertFormValue('filterGroup', group),
        [setAlertFormValue]
    )

    return (
        <div className="space-y-6 max-w-2xl">
            <div className="space-y-3">
                <h3 className="text-base font-semibold m-0">Filters</h3>
                <p className="text-xs text-secondary m-0">Every 5 minutes, query for logs matching these filters.</p>
                <LemonField name="severityLevels" label="Severity">
                    <SeverityLevelsFilter
                        value={alertForm.severityLevels}
                        onChange={(levels) => setAlertFormValue('severityLevels', levels)}
                    />
                </LemonField>
                <LemonField.Pure label="Service">
                    <ServiceFilter
                        value={alertForm.serviceNames}
                        onChange={(names) => setAlertFormValue('serviceNames', names)}
                    />
                </LemonField.Pure>
                <LemonField name="filterGroup" label="Attributes">
                    <AlertFilterGroup filterGroup={alertForm.filterGroup} onChange={handleFilterGroupChange} />
                </LemonField>
            </div>

            <LemonDivider />

            <div className="space-y-3">
                <h3 className="text-base font-semibold m-0">Rules</h3>
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm">Alert if count goes</span>
                    <LemonSegmentedButton
                        value={alertForm.thresholdOperator}
                        onChange={(value) => setAlertFormValue('thresholdOperator', value)}
                        options={[
                            { value: ThresholdOperatorEnumApi.Above, label: 'above' },
                            { value: ThresholdOperatorEnumApi.Below, label: 'below' },
                        ]}
                        size="small"
                    />
                    <LemonInput
                        type="number"
                        min={1}
                        value={alertForm.thresholdCount}
                        onChange={(val) => setAlertFormValue('thresholdCount', val ?? 1)}
                        className="w-24"
                        size="small"
                    />
                    <span className="text-sm">in the last</span>
                    <LemonSelect
                        value={alertForm.windowMinutes}
                        onChange={(val) => setAlertFormValue('windowMinutes', val ?? 10)}
                        options={WINDOW_OPTIONS}
                        size="small"
                    />
                </div>
            </div>

            <LemonDivider />

            <div className="space-y-4">
                <h3 className="text-base font-semibold m-0">Advanced</h3>
                <LemonField.Pure
                    label={
                        <span className="inline-flex items-center gap-1">
                            Reduce noise
                            <Tooltip title="Require the condition to be met multiple times before the alert fires. This prevents notifications on brief, one-off spikes.">
                                <IconInfo className="text-base text-secondary" />
                            </Tooltip>
                        </span>
                    }
                >
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 flex-wrap">
                            <LemonInput
                                type="number"
                                min={1}
                                max={alertForm.evaluationPeriods}
                                value={alertForm.datapointsToAlarm}
                                onChange={(val) => setAlertFormValue('datapointsToAlarm', val ?? 1)}
                                className="w-16"
                                size="small"
                            />
                            <span className="text-sm">of</span>
                            <LemonInput
                                type="number"
                                min={alertForm.datapointsToAlarm}
                                max={10}
                                value={alertForm.evaluationPeriods}
                                onChange={(val) => {
                                    const newPeriods = val ?? alertForm.datapointsToAlarm
                                    setAlertFormValue('evaluationPeriods', newPeriods)
                                    if (alertForm.datapointsToAlarm > newPeriods) {
                                        setAlertFormValue('datapointsToAlarm', newPeriods)
                                    }
                                }}
                                className="w-16"
                                size="small"
                            />
                            <span className="text-sm">checks must match to fire</span>
                            <CheckDotsTooltip
                                datapoints={alertForm.datapointsToAlarm}
                                periods={alertForm.evaluationPeriods}
                            />
                        </div>
                        <p className="text-xs text-secondary m-0">
                            The alert auto-resolves once the condition is no longer met.
                        </p>
                    </div>
                </LemonField.Pure>
                <LemonField.Pure
                    label="Notification cooldown"
                    help="After firing, wait this long before sending another notification. Set to 0 to notify on every check."
                >
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            min={0}
                            value={alertForm.cooldownMinutes}
                            onChange={(val) => setAlertFormValue('cooldownMinutes', val ?? 0)}
                            className="w-24"
                            size="small"
                        />
                        <span className="text-sm">minutes</span>
                    </div>
                </LemonField.Pure>
            </div>
        </div>
    )
}

const AlertFilterGroup = memo(function AlertFilterGroup({
    filterGroup,
    onChange,
}: {
    filterGroup: UniversalFiltersGroup
    onChange: (group: UniversalFiltersGroup) => void
}): JSX.Element {
    return (
        <UniversalFilters
            rootKey={taxonomicFilterLogicKey}
            group={filterGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={onChange}
        >
            <div className="space-y-2">
                <AlertFilterSearch />
                <AlertAppliedFilters />
            </div>
        </UniversalFilters>
    )
})

function AlertFilterSearch(): JSX.Element {
    const [visible, setVisible] = useState<boolean>(false)
    const { addGroupFilter, setGroupValues } = useActions(universalFiltersLogic)
    const { filterGroup } = useValues(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)
    const filterGroupRef = useRef(filterGroup)
    filterGroupRef.current = filterGroup

    const onClose = useCallback((): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }, [])

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = useMemo(
        () => ({
            taxonomicFilterLogicKey,
            taxonomicGroupTypes,
            onChange: (taxonomicGroup, value, item) => {
                if (item.value === undefined) {
                    addGroupFilter(taxonomicGroup, value, item)
                    setVisible(false)
                    return
                }

                const newValues = [...filterGroupRef.current.values]
                const newPropertyFilter = {
                    key: item.key,
                    value: item.value,
                    operator: PropertyOperator.IContains,
                    type: item.propertyFilterType,
                } as AnyPropertyFilter
                newValues.push(newPropertyFilter)
                setGroupValues(newValues)
                setVisible(false)
            },
            onEnter: () => {
                searchInputRef.current?.blur()
                setVisible(false)
            },
            autoSelectItem: true,
        }),
        [addGroupFilter, setGroupValues]
    )

    const showDropdown = useCallback(() => setVisible(true), [])

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <div className="w-[400px]">
                        <InfiniteSelectResults
                            focusInput={() => searchInputRef.current?.focus()}
                            taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                            popupAnchorElement={floatingRef.current}
                        />
                    </div>
                }
                visible={visible}
                closeOnClickInside={false}
                floatingRef={floatingRef}
                onClickOutside={onClose}
            >
                <TaxonomicFilterSearchInput
                    onClick={showDropdown}
                    searchInputRef={searchInputRef}
                    onClose={onClose}
                    onChange={showDropdown}
                />
            </LemonDropdown>
        </BindLogic>
    )
}

function AlertAppliedFilters(): JSX.Element | null {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    if (filterGroup.values.length === 0) {
        return null
    }

    return (
        <div className="flex gap-1 items-center flex-wrap">
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <AlertAppliedFilters />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={filterOrGroup.type !== PropertyFilterType.HogQL}
                    />
                )
            })}
        </div>
    )
}
