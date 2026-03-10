import { useActions, useValues } from 'kea'

import { IconFlask } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonModal, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { DisabledRuleBanner } from '../rules/DisabledRuleBanner'
import { MatchResultBanner } from '../rules/MatchResultBanner'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

export function GroupingRuleModal(): JSX.Element {
    const { isOpen, rule, hasFilters, matchResult, matchResultLoading, savingLoading, deletingLoading, dateRange } =
        useValues(groupingRuleModalLogic)
    const { closeModal, updateRule, loadMatchCount, saveRule, deleteRule, increaseDateRange } =
        useActions(groupingRuleModalLogic)

    const isEditing = rule.id !== 'new'

    return (
        <LemonModal
            title={rule.id === 'new' ? 'New grouping rule' : 'Edit grouping rule'}
            description={<span className="text-secondary">Matching exceptions will be grouped as a single issue.</span>}
            isOpen={isOpen}
            onClose={closeModal}
            width={700}
            overlayClassName="pt-20"
            footer={
                <div className="flex justify-between w-full">
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={matchResultLoading ? <Spinner textColored /> : <IconFlask />}
                            disabledReason={!hasFilters ? 'Add at least one filter first' : undefined}
                            onClick={loadMatchCount}
                        >
                            Test rule
                        </LemonButton>
                        {isEditing && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                loading={deletingLoading}
                                onClick={() =>
                                    LemonDialog.open({
                                        title: 'Delete rule',
                                        description:
                                            'Are you sure you want to delete this rule? This action cannot be undone.',
                                        primaryButton: {
                                            status: 'danger',
                                            children: 'Delete',
                                            onClick: () => deleteRule(),
                                        },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }
                            >
                                Delete
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={!hasFilters ? 'Add at least one filter' : undefined}
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
                        <span className="font-semibold text-sm">Filters</span>
                        <div className="flex gap-2 items-center">
                            <span className="text-secondary text-sm">Match</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={rule.filters.type}
                                onChange={(type) => updateRule({ ...rule, filters: { ...rule.filters, type } })}
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
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        onChange={(properties: AnyPropertyFilter[]) =>
                            updateRule({ ...rule, filters: { ...rule.filters, values: properties } })
                        }
                        pageKey="grouping-rule-modal"
                        buttonSize="small"
                        propertyGroupType={rule.filters.type}
                        hasRowOperator={false}
                        disablePopover
                    />
                </div>

                {matchResult !== null && !matchResultLoading ? (
                    <LemonBanner type={matchResult.exceptionCount === 0 ? 'error' : 'success'}>
                        <MatchResultBanner
                            matchResult={matchResult}
                            properties={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                            dateRange={dateRange}
                            onIncreaseDateRange={increaseDateRange}
                            suffix={(issuesLink, dateRangeLabel) => (
                                <>
                                    across {issuesLink} would have been grouped into one issue in the last{' '}
                                    {dateRangeLabel}
                                </>
                            )}
                        />
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
