import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconTrash, IconWarning } from '@posthog/icons'
import { Badge, Button, Card, CardContent, CardHeader, Checkbox, Skeleton, Text } from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { QuillSortableRuleItem } from './QuillSortableRuleItem'
import { rulesLogic } from './rulesLogic'
import { ErrorTrackingRule, ErrorTrackingRuleType } from './types'

export interface QuillRuleListProps {
    ruleType: ErrorTrackingRuleType
    modalLogic: any
    modal: ReactNode
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    pageKeyPrefix: string
    description?: ReactNode
    renderCardHeaderExtra?: (rule: any) => ReactNode
    headerActions?: ReactNode
    onDeleteSelected: () => void
}

export function QuillRuleList({
    ruleType,
    modalLogic,
    modal,
    taxonomicGroupTypes,
    pageKeyPrefix,
    description,
    renderCardHeaderExtra,
    headerActions,
    onDeleteSelected,
}: QuillRuleListProps): JSX.Element {
    const logic = rulesLogic({ ruleType })
    const { rules, allRules, isReorderingRules, isSelectingRules, selectedRuleIds, rulesLoading, initialLoadComplete } =
        useValues(logic)
    const {
        startReorderingRules,
        finishReorderingRules,
        cancelReorderingRules,
        reorderLocalRules,
        startSelectingRules,
        cancelSelectingRules,
        toggleSelectedRule,
        setSelectedRuleIds,
    } = useActions(logic)
    const { openModal } = useActions(modalLogic)

    if (!initialLoadComplete) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-20 w-full" />
            </div>
        )
    }

    const displayRules = (isReorderingRules ? allRules : rules) as ErrorTrackingRule[]
    const selectedRuleCount = selectedRuleIds.length
    const allRulesSelected = rules.length > 0 && selectedRuleCount === rules.length
    const editDisabledReason = errorTrackingEditAccessDisabledReason() ?? undefined
    const rulesClickable = !isReorderingRules && !isSelectingRules

    return (
        <div className="flex flex-col gap-2">
            {modal}
            {description}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" render={<span className="m-0" />} translate="no">
                    <span className="font-semibold">{rules.length}</span>{' '}
                    <span className="text-muted-foreground">{rules.length === 1 ? 'rule' : 'rules'}</span>
                </Text>
                <div className="flex flex-wrap gap-2">
                    {isReorderingRules ? (
                        <>
                            <Button variant="outline" onClick={cancelReorderingRules}>
                                Cancel
                            </Button>
                            <Button variant="primary" onClick={finishReorderingRules} loading={rulesLoading}>
                                Finish reordering
                            </Button>
                        </>
                    ) : isSelectingRules ? (
                        <>
                            <Button
                                variant="outline"
                                onClick={() => setSelectedRuleIds(allRulesSelected ? [] : rules.map((rule) => rule.id))}
                            >
                                {allRulesSelected ? 'Deselect all' : 'Select all'}
                            </Button>
                            <Button variant="outline" onClick={cancelSelectingRules}>
                                Cancel
                            </Button>
                            <Button
                                variant="destructive"
                                disabledReason={selectedRuleCount === 0 ? 'Select at least one rule' : undefined}
                                loading={rulesLoading}
                                onClick={onDeleteSelected}
                            >
                                <IconTrash />
                                Delete{selectedRuleCount > 0 ? ` ${selectedRuleCount}` : ''}
                            </Button>
                        </>
                    ) : (
                        <>
                            {headerActions}
                            {rules.length > 1 && (
                                <>
                                    <Button
                                        variant="outline"
                                        onClick={startSelectingRules}
                                        disabledReason={editDisabledReason}
                                    >
                                        Select
                                    </Button>
                                    <Button
                                        variant="outline"
                                        onClick={startReorderingRules}
                                        disabledReason={editDisabledReason}
                                    >
                                        Reorder
                                    </Button>
                                </>
                            )}
                            <Button variant="primary" onClick={() => openModal()} disabledReason={editDisabledReason}>
                                Add rule
                            </Button>
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
                    <div className="flex flex-col gap-2">
                        {displayRules.map((rule) => {
                            const disabled = !!rule.disabled_data
                            const matchLabel = rule.filters.type === FilterLogicalOperator.And ? 'all' : 'any'
                            const filterValues = (rule.filters.values as AnyPropertyFilter[]) ?? []

                            const header = (
                                <>
                                    <span className="flex flex-wrap items-center gap-2">
                                        <Text
                                            size="xxs"
                                            weight="semibold"
                                            variant="muted"
                                            className="uppercase"
                                            render={<span className="m-0" />}
                                        >
                                            Match {matchLabel}
                                        </Text>
                                        {renderCardHeaderExtra?.(rule)}
                                    </span>
                                    <Text
                                        size="xs"
                                        variant="muted"
                                        className="flex flex-wrap items-center gap-1"
                                        render={<span className="m-0" />}
                                    >
                                        {disabled && (
                                            <Badge variant="warning">
                                                <IconWarning />
                                                Disabled
                                            </Badge>
                                        )}
                                        {rule.updated_at && rule.updated_at !== rule.created_at ? (
                                            <>
                                                <span>Updated</span>
                                                <TZLabel time={rule.updated_at} />
                                            </>
                                        ) : rule.created_at ? (
                                            <>
                                                <span>Created</span>
                                                <TZLabel time={rule.created_at} />
                                            </>
                                        ) : null}
                                    </Text>
                                </>
                            )

                            return (
                                <QuillSortableRuleItem
                                    key={rule.id}
                                    ruleId={rule.id}
                                    reorderable={isReorderingRules}
                                    leading={
                                        isSelectingRules ? (
                                            <Checkbox
                                                checked={selectedRuleIds.includes(rule.id)}
                                                onCheckedChange={() => toggleSelectedRule(rule.id)}
                                                aria-label="Select rule"
                                            />
                                        ) : null
                                    }
                                >
                                    <Card size="sm">
                                        <CardHeader>
                                            {rulesClickable ? (
                                                <button
                                                    type="button"
                                                    className="flex w-full cursor-pointer flex-wrap items-center justify-between gap-2 rounded-sm text-left hover:bg-fill-hover"
                                                    onClick={() => openModal(rule)}
                                                >
                                                    {header}
                                                </button>
                                            ) : (
                                                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                                                    {header}
                                                </div>
                                            )}
                                        </CardHeader>
                                        <CardContent>
                                            {filterValues.length > 0 ? (
                                                <QuillSurfaceContext.Provider value={true}>
                                                    <PropertyFilters
                                                        editable={false}
                                                        propertyFilters={filterValues}
                                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                                        onChange={() => {}}
                                                        pageKey={`${pageKeyPrefix}-${rule.id}`}
                                                        buttonSize="small"
                                                        propertyGroupType={rule.filters.type}
                                                        hasRowOperator={false}
                                                        disablePopover
                                                    />
                                                </QuillSurfaceContext.Provider>
                                            ) : (
                                                <Text
                                                    size="xs"
                                                    variant="muted"
                                                    className="italic"
                                                    render={<span className="m-0" />}
                                                >
                                                    Matches all exceptions
                                                </Text>
                                            )}
                                        </CardContent>
                                    </Card>
                                </QuillSortableRuleItem>
                            )
                        })}
                    </div>
                </SortableContext>
            </DndContext>
        </div>
    )
}
