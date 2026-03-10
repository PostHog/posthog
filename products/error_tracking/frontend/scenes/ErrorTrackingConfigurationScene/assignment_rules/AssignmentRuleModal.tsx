import { useActions, useValues } from 'kea'

import { IconFlask } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonModal, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { AssigneeLabelDisplay } from '../../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../../components/Assignee/AssigneeSelect'
import { DisabledRuleBanner } from '../rules/DisabledRuleBanner'
import { MatchResultBanner } from '../rules/MatchResultBanner'
import { assignmentRuleModalLogic } from './assignmentRuleModalLogic'

export function AssignmentRuleModal(): JSX.Element {
    const {
        isOpen,
        rule,
        hasFilters,
        hasAssignee,
        matchResult,
        matchResultLoading,
        savingLoading,
        deletingLoading,
        dateRange,
    } = useValues(assignmentRuleModalLogic)
    const { closeModal, updateRule, loadMatchCount, saveRule, deleteRule, increaseDateRange } =
        useActions(assignmentRuleModalLogic)

    const isEditing = rule.id !== 'new'

    const saveDisabledReason = !hasFilters ? 'Add at least one filter' : !hasAssignee ? 'Choose an assignee' : undefined

    return (
        <LemonModal
            title={rule.id === 'new' ? 'New assignment rule' : 'Edit assignment rule'}
            description={
                <span className="text-secondary">
                    Matching exceptions will be automatically assigned to the chosen user or role.
                </span>
            }
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
                            disabledReason={saveDisabledReason}
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
                    <LemonLabel className="mb-2">Assignee</LemonLabel>
                    <AssigneeSelect assignee={rule.assignee} onChange={(assignee) => updateRule({ ...rule, assignee })}>
                        {(displayAssignee) => (
                            <LemonButton fullWidth type="secondary" size="small">
                                <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Choose user or role" />
                            </LemonButton>
                        )}
                    </AssigneeSelect>
                </div>
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
                        pageKey="assignment-rule-modal"
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
                                    across {issuesLink} would have been assigned in the last {dateRangeLabel}
                                </>
                            )}
                        />
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
