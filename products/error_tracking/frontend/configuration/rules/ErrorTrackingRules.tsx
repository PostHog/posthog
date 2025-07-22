import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonDialog, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyFilters, PropertyFiltersProps } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropsWithChildren, useEffect } from 'react'

import { AnyPropertyFilter, FilterLogicalOperator, SidePanelTab } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from '../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../components/Assignee/AssigneeSelect'
import { errorTrackingRulesLogic } from './errorTrackingRulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRule, ErrorTrackingRuleType } from './types'
import { PageHeader } from 'lib/components/PageHeader'

import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { DndContext } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'

import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'

function isRuleDisabled(rule: ErrorTrackingRule): boolean {
    return 'disabled_data' in rule && !!rule.disabled_data
}

function ErrorTrackingRules<T extends ErrorTrackingRule>({
    ruleType,
    children,
}: {
    ruleType: ErrorTrackingRuleType
    children: ({ rule, editing, disabled }: { rule: T; editing: boolean; disabled: boolean }) => JSX.Element
}): JSX.Element {
    const logicProps = { ruleType }
    const logic = errorTrackingRulesLogic(logicProps)

    const { allRules, localRules, initialLoadComplete, isReorderingRules } = useValues(logic)
    const { loadRules, reorderLocalRules } = useActions(logic)

    useEffect(() => {
        loadRules()
    }, [loadRules])

    return !initialLoadComplete ? (
        <Spinner />
    ) : (
        <BindLogic logic={errorTrackingRulesLogic} props={logicProps}>
            <DndContext
                modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                onDragEnd={({ active, over }) => {
                    if (over && active.id !== over.id) {
                        const activeIndex = allRules.findIndex((r) => r.id === active.id)
                        const overIndex = allRules.findIndex((r) => r.id === over.id)
                        reorderLocalRules(arrayMove(allRules, activeIndex, overIndex))
                    }
                }}
            >
                <SortableContext items={allRules} strategy={verticalListSortingStrategy}>
                    <div className="flex flex-col mt-2">
                        {allRules.map((persistedRule) => {
                            const editingRule = localRules.find((r) => r.id === persistedRule.id) as T

                            const editing = !isReorderingRules && !!editingRule
                            const rule = editingRule ?? persistedRule
                            const disabled = isRuleDisabled(rule)

                            return (
                                <SortableRule key={rule.id} ruleId={rule.id} reorderable={isReorderingRules}>
                                    <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                                        {disabled && <DisabledBanner />}
                                        {children({ rule, editing, disabled })}
                                    </LemonCard>
                                </SortableRule>
                            )
                        })}
                    </div>
                </SortableContext>
            </DndContext>

            {false ? (
                <PageHeader
                    buttons={
                        <>
                            {allRules.length > 1 && <ReorderRules />}
                            <AddRule />
                        </>
                    }
                />
            ) : null}
        </BindLogic>
    )
}

const SortableRule = ({
    ruleId,
    reorderable,
    children,
}: PropsWithChildren<{ ruleId: ErrorTrackingRule['id']; reorderable: boolean }>): JSX.Element => {
    const { setNodeRef, attributes, transform, transition, listeners, active, isDragging } = useSortable({ id: ruleId })

    return (
        <div
            className={cn('flex space-y-2 mb-2', isDragging && 'z-[999999]')}
            ref={setNodeRef}
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
            {...attributes}
        >
            {reorderable && (
                <SortableDragIcon
                    className={cn('rotate-90 w-5 h-5 mt-2', active ? 'cursor-grabbing' : 'cursor-grab')}
                    {...listeners}
                />
            )}
            <LemonCard hoverEffect={false} className="flex flex-col flex-1 p-0">
                {children}
            </LemonCard>
        </div>
    )
}

const ReorderRules = (): JSX.Element | null => {
    const { localRules, isReorderingRules, rulesLoading } = useValues(errorTrackingRulesLogic)
    const { startReorderingRules, finishReorderingRules, cancelReorderingRules } = useActions(errorTrackingRulesLogic)

    return isReorderingRules ? (
        <>
            <LemonButton type="secondary" size="small" onClick={cancelReorderingRules}>
                Cancel
            </LemonButton>
            <LemonButton type="primary" size="small" onClick={finishReorderingRules} loading={rulesLoading}>
                Finish reordering
            </LemonButton>
        </>
    ) : (
        <div>
            <LemonButton
                type="secondary"
                size="small"
                onClick={startReorderingRules}
                disabledReason={localRules.length > 0 ? 'Finish editing all rules before reordering' : undefined}
            >
                Reorder rules
            </LemonButton>
        </div>
    )
}

const DisabledBanner = (): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <LemonBanner
            className="mx-2 mt-2"
            type="error"
            action={{
                onClick: () => openSidePanel(SidePanelTab.Support, 'bug:error_tracking'),
                children: 'Contact support',
            }}
        >
            This rule has been disabled due to an error and is being investigated by our team
        </LemonBanner>
    )
}

const AddRule = (): JSX.Element | null => {
    const { hasNewRule, isReorderingRules } = useValues(errorTrackingRulesLogic)
    const { addRule } = useActions(errorTrackingRulesLogic)

    return !hasNewRule && !isReorderingRules ? (
        <div>
            <LemonButton type="primary" size="small" onClick={addRule}>
                Add rule
            </LemonButton>
        </div>
    ) : null
}

const Actions = ({ rule, editing }: { rule: ErrorTrackingRule; editing: boolean }): JSX.Element => {
    const { isReorderingRules } = useValues(errorTrackingRulesLogic)
    const { saveRule, deleteRule, setRuleEditable, unsetRuleEditable } = useActions(errorTrackingRulesLogic)

    return (
        <div className="flex gap-1">
            {isReorderingRules ? null : editing ? (
                <>
                    {rule.id === 'new' ? null : (
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Delete rule',
                                    description:
                                        'Are you sure you want to delete this rule? This action cannot be undone',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Remove',
                                        onClick: () => deleteRule(rule.id),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }
                        />
                    )}
                    <LemonButton size="small" onClick={() => unsetRuleEditable(rule.id)}>
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" onClick={() => saveRule(rule.id)}>
                        Save
                    </LemonButton>
                </>
            ) : (
                <LemonButton size="small" icon={<IconPencil />} onClick={() => setRuleEditable(rule.id)} />
            )}
        </div>
    )
}

const Filters = ({
    rule,
    editing,
    taxonomicGroupTypes,
    ...props
}: Pick<PropertyFiltersProps, 'taxonomicGroupTypes' | 'propertyAllowList'> & {
    rule: ErrorTrackingRule
    editing: boolean
    taxonomicGroupTypes: PropertyFiltersProps['taxonomicGroupTypes']
    excludedProperties?: PropertyFiltersProps['excludedProperties']
}): JSX.Element => {
    const { updateLocalRule } = useActions(errorTrackingRulesLogic)

    return (
        <PropertyFilters
            editable={editing}
            propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(properties: AnyPropertyFilter[]) =>
                updateLocalRule({ ...rule, filters: { ...rule.filters, values: properties } })
            }
            pageKey={`error-tracking-rule-properties-${rule.id}`}
            buttonSize="small"
            propertyGroupType={rule.filters.type}
            hasRowOperator={false}
            disablePopover
            {...props}
        />
    )
}

const Assignee = ({ rule, editing }: { rule: ErrorTrackingAssignmentRule; editing: boolean }): JSX.Element => {
    const { updateLocalRule } = useActions(errorTrackingRulesLogic)

    return editing ? (
        <AssigneeSelect assignee={rule.assignee} onChange={(assignee) => updateLocalRule({ ...rule, assignee })}>
            {(displayAssignee) => (
                <LemonButton fullWidth type="secondary" size="small">
                    <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Choose user" />
                </LemonButton>
            )}
        </AssigneeSelect>
    ) : (
        <AssigneeResolver assignee={rule.assignee}>
            {({ assignee }) => (
                <>
                    <AssigneeIconDisplay assignee={assignee} />
                    <AssigneeLabelDisplay assignee={assignee} />
                </>
            )}
        </AssigneeResolver>
    )
}

const Operator = ({ rule, editing }: { rule: ErrorTrackingRule; editing: boolean }): JSX.Element => {
    const { updateLocalRule } = useActions(errorTrackingRulesLogic)

    const operator = rule.filters.type

    return editing ? (
        <LemonSelect
            size="small"
            value={operator}
            onChange={(type) => updateLocalRule({ ...rule, filters: { ...rule.filters, type } })}
            options={[
                { label: 'All', value: FilterLogicalOperator.And },
                { label: 'Any', value: FilterLogicalOperator.Or },
            ]}
        />
    ) : (
        <span className="font-semibold">{operator === FilterLogicalOperator.And ? 'all' : 'any'}</span>
    )
}

ErrorTrackingRules.Assignee = Assignee
ErrorTrackingRules.Filters = Filters
ErrorTrackingRules.Operator = Operator
ErrorTrackingRules.Actions = Actions

export default ErrorTrackingRules
