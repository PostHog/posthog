import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { IconFlask } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { DisabledRuleBanner } from './DisabledRuleBanner'
import { MatchResultBanner } from './MatchResultBanner'

interface RuleModalProps {
    logic: any
    ruleLabel: string
    description: string
    pageKey: string
    width?: number
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    saveDisabledReason?: string
    suffix: (issuesLink: JSX.Element, dateRangeLabel: string) => JSX.Element
    filterLabels?: ReactNode
    extraFields?: ReactNode
    footerExtra?: ReactNode
    samplingRate?: number
    filtersOptional?: boolean
}

export function RuleModal({
    logic,
    ruleLabel,
    description,
    pageKey,
    width = 700,
    taxonomicGroupTypes,
    saveDisabledReason,
    suffix,
    filterLabels,
    extraFields,
    footerExtra,
    samplingRate,
    filtersOptional = false,
}: RuleModalProps): JSX.Element {
    const { isOpen, rule, hasFilters, matchResult, matchResultLoading, savingLoading, deletingLoading, dateRange } =
        useValues(logic)
    const { closeModal, updateRule, loadMatchCount, saveRule, deleteRule, increaseDateRange } = useActions(logic)

    const isEditing = rule.id !== 'new'
    const defaultSaveDisabled = !filtersOptional && !hasFilters ? 'Add at least one filter' : undefined
    const resolvedSaveDisabled = saveDisabledReason ?? defaultSaveDisabled

    const [confirmingDelete, setConfirmingDelete] = useState(false)
    const [confirmEnabled, setConfirmEnabled] = useState(false)
    const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])

    const clearTimers = useCallback(() => {
        timersRef.current.forEach(clearTimeout)
        timersRef.current = []
    }, [])

    useEffect(() => {
        if (!isOpen) {
            setConfirmingDelete(false)
            setConfirmEnabled(false)
            clearTimers()
        }
    }, [isOpen, clearTimers])

    useEffect(() => {
        if (confirmingDelete) {
            clearTimers()
            timersRef.current.push(setTimeout(() => setConfirmEnabled(true), 1000))
            timersRef.current.push(
                setTimeout(() => {
                    setConfirmingDelete(false)
                    setConfirmEnabled(false)
                }, 3000)
            )
        }
        return clearTimers
    }, [confirmingDelete, clearTimers])

    return (
        <LemonModal
            title={rule.id === 'new' ? `New ${ruleLabel} rule` : `Edit ${ruleLabel} rule`}
            description={<span className="text-secondary">{description}</span>}
            isOpen={isOpen}
            onClose={closeModal}
            width={width}
            overlayClassName="pt-20"
            footer={
                <div className="flex justify-between w-full">
                    <div className="flex gap-2">
                        {isEditing && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                loading={deletingLoading}
                                disabledReason={
                                    confirmingDelete && !confirmEnabled ? 'Click again to confirm' : undefined
                                }
                                onClick={() => {
                                    if (confirmingDelete && confirmEnabled) {
                                        deleteRule()
                                    } else {
                                        setConfirmingDelete(true)
                                    }
                                }}
                            >
                                {confirmingDelete ? 'Confirm delete' : 'Delete'}
                            </LemonButton>
                        )}
                        {footerExtra}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={matchResultLoading ? <Spinner textColored /> : <IconFlask />}
                            disabledReason={
                                !filtersOptional && !hasFilters ? 'Add at least one filter first' : undefined
                            }
                            onClick={loadMatchCount}
                        >
                            Test rule
                        </LemonButton>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={resolvedSaveDisabled}
                            onClick={() => saveRule()}
                            loading={savingLoading}
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-4 py-2">
                {rule.disabled_data && <DisabledRuleBanner rule={rule} onClose={closeModal} />}
                <div>
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-3">
                            <span className="font-semibold text-sm">Filters</span>
                            {filterLabels && (
                                <>
                                    <span className="text-muted">·</span>
                                    {filterLabels}
                                </>
                            )}
                        </div>
                        <div className="flex gap-2 items-center">
                            <span className="text-secondary text-sm">Match</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={rule.filters.type}
                                onChange={(type: FilterLogicalOperator) =>
                                    updateRule({ ...rule, filters: { ...rule.filters, type } })
                                }
                                options={[
                                    { label: 'All', value: FilterLogicalOperator.And },
                                    { label: 'Any', value: FilterLogicalOperator.Or },
                                ]}
                            />
                        </div>
                    </div>
                    <PropertyFilters
                        editable
                        propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(properties: AnyPropertyFilter[]) =>
                            updateRule({
                                ...rule,
                                filters: { ...rule.filters, values: properties },
                            })
                        }
                        pageKey={pageKey}
                        buttonSize="small"
                        propertyGroupType={rule.filters.type}
                        hasRowOperator={false}
                        disablePopover
                    />
                </div>

                {extraFields}

                {matchResult !== null && !matchResultLoading ? (
                    <LemonBanner type={matchResult.exceptionCount === 0 ? 'error' : 'success'}>
                        <MatchResultBanner
                            matchResult={matchResult}
                            properties={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                            filterType={rule.filters.type}
                            dateRange={dateRange}
                            onIncreaseDateRange={increaseDateRange}
                            suffix={suffix}
                            samplingRate={samplingRate}
                        />
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
