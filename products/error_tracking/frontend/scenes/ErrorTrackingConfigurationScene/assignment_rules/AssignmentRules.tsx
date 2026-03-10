import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { PropsWithChildren, useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from '../../../components/Assignee/AssigneeDisplay'
import { assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRule, ErrorTrackingRuleType } from '../rules/types'
import { AssignmentRuleModal } from './AssignmentRuleModal'
import { assignmentRuleModalLogic } from './assignmentRuleModalLogic'

function SortableRuleItem({
    ruleId,
    reorderable,
    children,
}: PropsWithChildren<{ ruleId: ErrorTrackingRule['id']; reorderable: boolean }>): JSX.Element {
    const { setNodeRef, attributes, transform, transition, listeners, active, isDragging } = useSortable({ id: ruleId })

    return (
        <div
            className={cn('flex gap-2', isDragging && 'z-[999999]')}
            ref={setNodeRef}
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
            {...attributes}
        >
            {reorderable && (
                <SortableDragIcon
                    className={cn('rotate-90 w-5 h-5 mt-4', active ? 'cursor-grabbing' : 'cursor-grab')}
                    {...listeners}
                />
            )}
            <div className="flex-1">{children}</div>
        </div>
    )
}

export function AssignmentRules(): JSX.Element {
    const ruleType = ErrorTrackingRuleType.Assignment
    const logic = rulesLogic({ ruleType })
    const { rules, allRules, isReorderingRules, rulesLoading, initialLoadComplete } = useValues(logic)
    const { loadRules, startReorderingRules, finishReorderingRules, cancelReorderingRules, reorderLocalRules } =
        useActions(logic)
    const { openModal } = useActions(assignmentRuleModalLogic)
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)

    useEffect(() => {
        loadRules()
        ensureAssigneeTypesLoaded()
    }, [loadRules, ensureAssigneeTypesLoaded])

    if (!initialLoadComplete) {
        return <Spinner />
    }

    const displayRules = (isReorderingRules ? allRules : rules) as ErrorTrackingAssignmentRule[]

    return (
        <>
            <AssignmentRuleModal />
            <p>
                Automatically assign newly created issues based on properties of the exception event the first time it
                was seen. The first rule that matches will be applied.
            </p>
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
                    ) : (
                        <>
                            {rules.length > 1 && (
                                <LemonButton type="secondary" size="small" onClick={startReorderingRules}>
                                    Reorder
                                </LemonButton>
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
                                <SortableRuleItem key={rule.id} ruleId={rule.id} reorderable={isReorderingRules}>
                                    <LemonCard
                                        hoverEffect={false}
                                        className={cn('flex flex-col p-0', !isReorderingRules && 'cursor-pointer')}
                                        onClick={isReorderingRules ? undefined : () => openModal(rule)}
                                    >
                                        <div className="flex items-center justify-between px-3 py-2">
                                            <div className="flex items-center gap-2">
                                                <span className="text-xs font-semibold uppercase text-secondary">
                                                    Match{' '}
                                                    {rule.filters.type === FilterLogicalOperator.And ? 'all' : 'any'}
                                                </span>
                                                <span className="text-xs text-muted">→</span>
                                                <AssigneeResolver assignee={rule.assignee}>
                                                    {({ assignee }) => (
                                                        <span className="flex items-center gap-1 text-xs">
                                                            <AssigneeIconDisplay assignee={assignee} size="xsmall" />
                                                            <AssigneeLabelDisplay assignee={assignee} />
                                                        </span>
                                                    )}
                                                </AssigneeResolver>
                                            </div>
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
                                            <PropertyFilters
                                                editable={false}
                                                propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                                onChange={() => {}}
                                                pageKey={`assignment-rule-${rule.id}`}
                                                buttonSize="small"
                                                propertyGroupType={rule.filters.type}
                                                hasRowOperator={false}
                                                disablePopover
                                            />
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
