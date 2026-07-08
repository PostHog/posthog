import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCheckbox, LemonDialog, LemonDivider, Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { rulesLogic } from './rulesLogic'
import { SortableRuleItem } from './SortableRuleItem'
import { ErrorTrackingRule, ErrorTrackingRuleType } from './types'

interface RuleListProps {
    ruleType: ErrorTrackingRuleType
    modalLogic: any
    modal: ReactNode
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    pageKeyPrefix: string
    description?: ReactNode
    renderCardHeaderExtra?: (rule: any) => ReactNode
    onMount?: () => void
    /** Extra actions rendered to the left of the Reorder/Add rule buttons (e.g. bulk import). */
    headerActions?: ReactNode
}

export function RuleList({
    ruleType,
    modalLogic,
    modal,
    taxonomicGroupTypes,
    pageKeyPrefix,
    description,
    renderCardHeaderExtra,
    onMount,
    headerActions,
}: RuleListProps): JSX.Element {
    const logic = rulesLogic({ ruleType })
    const { rules, allRules, isReorderingRules, isSelectingRules, selectedRuleIds, rulesLoading, initialLoadComplete } =
        useValues(logic)
    const {
        loadRules,
        startReorderingRules,
        finishReorderingRules,
        cancelReorderingRules,
        reorderLocalRules,
        startSelectingRules,
        cancelSelectingRules,
        toggleSelectedRule,
        setSelectedRuleIds,
        deleteSelectedRules,
    } = useActions(logic)
    const { openModal } = useActions(modalLogic)

    useEffect(() => {
        loadRules()
        onMount?.()
    }, [loadRules, onMount])

    if (!initialLoadComplete) {
        return <Spinner />
    }

    const displayRules = (isReorderingRules ? allRules : rules) as ErrorTrackingRule[]
    const selectedRuleCount = selectedRuleIds.length
    const allRulesSelected = rules.length > 0 && selectedRuleCount === rules.length

    return (
        <>
            {modal}
            {description}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{rules.length}</span>
                    <span className="text-secondary">{rules.length === 1 ? 'rule' : 'rules'}</span>
                </div>
                <div className="flex gap-2">
                    {isReorderingRules ? (
                        <>
                            <LemonButton type="secondary" size="small" onClick={cancelReorderingRules}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={finishReorderingRules}
                                loading={rulesLoading}
                            >
                                Finish reordering
                            </LemonButton>
                        </>
                    ) : isSelectingRules ? (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => setSelectedRuleIds(allRulesSelected ? [] : rules.map((rule) => rule.id))}
                            >
                                {allRulesSelected ? 'Deselect all' : 'Select all'}
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={cancelSelectingRules}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                status="danger"
                                size="small"
                                icon={<IconTrash />}
                                disabled={selectedRuleCount === 0}
                                loading={rulesLoading}
                                onClick={() =>
                                    LemonDialog.open({
                                        title: 'Delete rules',
                                        description: `Are you sure you want to delete ${selectedRuleCount} ${
                                            selectedRuleCount === 1 ? 'rule' : 'rules'
                                        }?`,
                                        secondaryButton: {
                                            type: 'secondary',
                                            children: 'Cancel',
                                        },
                                        primaryButton: {
                                            type: 'primary',
                                            status: 'danger',
                                            onClick: deleteSelectedRules,
                                            children: 'Delete',
                                        },
                                    })
                                }
                            >
                                Delete{selectedRuleCount > 0 ? ` ${selectedRuleCount}` : ''}
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            {headerActions}
                            {rules.length > 1 && (
                                <>
                                    <LemonButton type="secondary" size="small" onClick={startSelectingRules}>
                                        Select
                                    </LemonButton>
                                    <LemonButton type="secondary" size="small" onClick={startReorderingRules}>
                                        Reorder
                                    </LemonButton>
                                </>
                            )}
                            <LemonButton type="primary" size="small" onClick={() => openModal()}>
                                Add rule
                            </LemonButton>
                        </>
                    )}
                </div>
            </div>
            <DndContext
                modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                onDragEnd={({ active, over }) => {
                    if (over && active.id !== over.id) {
                        const activeIndex = displayRules.findIndex((r) => r.id === active.id)
                        const overIndex = displayRules.findIndex((r) => r.id === over.id)
                        reorderLocalRules(arrayMove(displayRules, activeIndex, overIndex))
                    }
                }}
            >
                <SortableContext items={displayRules} strategy={verticalListSortingStrategy}>
                    <div className="flex flex-col mt-2 gap-2">
                        {displayRules.map((rule) => {
                            const disabled = !!rule.disabled_data

                            return (
                                <SortableRuleItem
                                    key={rule.id}
                                    ruleId={rule.id}
                                    reorderable={isReorderingRules}
                                    leading={
                                        isSelectingRules ? (
                                            <LemonCheckbox
                                                checked={selectedRuleIds.includes(rule.id)}
                                                onChange={() => toggleSelectedRule(rule.id)}
                                            />
                                        ) : null
                                    }
                                >
                                    <LemonCard
                                        hoverEffect={false}
                                        className={cn(
                                            'flex flex-col p-0',
                                            !isReorderingRules && !isSelectingRules && 'cursor-pointer'
                                        )}
                                        onClick={
                                            isReorderingRules || isSelectingRules ? undefined : () => openModal(rule)
                                        }
                                    >
                                        <div className="flex items-center justify-between px-3 py-2">
                                            {renderCardHeaderExtra ? (
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-semibold uppercase text-secondary">
                                                        Match{' '}
                                                        {rule.filters.type === FilterLogicalOperator.And
                                                            ? 'all'
                                                            : 'any'}
                                                    </span>
                                                    {renderCardHeaderExtra(rule)}
                                                </div>
                                            ) : (
                                                <span className="text-xs font-semibold uppercase text-secondary">
                                                    Match{' '}
                                                    {rule.filters.type === FilterLogicalOperator.And ? 'all' : 'any'}
                                                </span>
                                            )}
                                            <span className="flex items-center gap-1 text-xs text-muted">
                                                {disabled && (
                                                    <>
                                                        <IconWarning className="text-warning text-base" />
                                                        <span className="text-warning font-semibold">Disabled</span>
                                                        <span>·</span>
                                                    </>
                                                )}
                                                {rule.updated_at && rule.updated_at !== rule.created_at ? (
                                                    <>
                                                        Updated <TZLabel time={rule.updated_at} />
                                                    </>
                                                ) : rule.created_at ? (
                                                    <>
                                                        Created <TZLabel time={rule.created_at} />
                                                    </>
                                                ) : null}
                                            </span>
                                        </div>
                                        <LemonDivider className="my-0" />
                                        <div className="px-3 py-2">
                                            {(rule.filters.values as AnyPropertyFilter[])?.length > 0 ? (
                                                <PropertyFilters
                                                    editable={false}
                                                    propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                                    onChange={() => {}}
                                                    pageKey={`${pageKeyPrefix}-${rule.id}`}
                                                    buttonSize="small"
                                                    propertyGroupType={rule.filters.type}
                                                    hasRowOperator={false}
                                                    disablePopover
                                                />
                                            ) : (
                                                <span className="text-xs text-secondary italic">
                                                    Matches all exceptions
                                                </span>
                                            )}
                                        </div>
                                    </LemonCard>
                                </SortableRuleItem>
                            )
                        })}
                    </div>
                </SortableContext>
            </DndContext>
        </>
    )
}
