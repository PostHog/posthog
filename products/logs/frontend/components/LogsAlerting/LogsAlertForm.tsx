import { BindLogic, useActions, useValues } from 'kea'
import { memo, useCallback, useMemo, useRef, useState } from 'react'

import {
    LemonButton,
    LemonCollapse,
    LemonDropdown,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'

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

export function LogsAlertForm(): JSX.Element {
    const { alertForm } = useValues(logsAlertFormLogic)
    const { setAlertFormValue } = useActions(logsAlertFormLogic)

    const handleFilterGroupChange = useCallback(
        (group: UniversalFiltersGroup) => setAlertFormValue('filterGroup', group),
        [setAlertFormValue]
    )

    const consecutiveEnabled = alertForm.evaluationPeriods > 1

    return (
        <div className="space-y-4">
            <LemonField name="name" label="Name">
                <LemonInput placeholder="e.g. API 5xx errors" fullWidth />
            </LemonField>

            <div className="space-y-2">
                <h5 className="m-0">Filters</h5>

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

            <div className="space-y-2">
                <h5 className="m-0">Threshold</h5>

                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm">Alert when log count is</span>
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

            <LemonCollapse
                panels={[
                    {
                        key: 'advanced',
                        header: 'Advanced',
                        content: (
                            <div className="space-y-4">
                                <LemonField.Pure
                                    label="Consecutive trigger"
                                    help="Require N of M checks to breach before firing. Reduces noise from transient spikes."
                                >
                                    <div className="flex items-center gap-2">
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                if (consecutiveEnabled) {
                                                    setAlertFormValue('evaluationPeriods', 1)
                                                    setAlertFormValue('datapointsToAlarm', 1)
                                                } else {
                                                    setAlertFormValue('evaluationPeriods', 3)
                                                    setAlertFormValue('datapointsToAlarm', 2)
                                                }
                                            }}
                                        >
                                            {consecutiveEnabled ? 'Disable' : 'Enable'}
                                        </LemonButton>
                                        {consecutiveEnabled && (
                                            <>
                                                <LemonInput
                                                    type="number"
                                                    min={2}
                                                    value={alertForm.datapointsToAlarm}
                                                    onChange={(val) => setAlertFormValue('datapointsToAlarm', val ?? 2)}
                                                    className="w-16"
                                                    size="small"
                                                />
                                                <span className="text-sm">of</span>
                                                <LemonInput
                                                    type="number"
                                                    min={alertForm.datapointsToAlarm}
                                                    value={alertForm.evaluationPeriods}
                                                    onChange={(val) =>
                                                        setAlertFormValue(
                                                            'evaluationPeriods',
                                                            val ?? alertForm.datapointsToAlarm
                                                        )
                                                    }
                                                    className="w-16"
                                                    size="small"
                                                />
                                                <span className="text-sm">checks</span>
                                            </>
                                        )}
                                    </div>
                                </LemonField.Pure>

                                <LemonField.Pure
                                    label="Re-notify cooldown"
                                    help="Minutes to suppress duplicate notifications after firing. Set to 0 for immediate re-notification."
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
                        ),
                    },
                ]}
            />
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
                            useVerticalLayout={true}
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
