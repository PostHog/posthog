import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber, inStorybook, inStorybookTestRunner } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CurrencyCode, RevenueAnalyticsGoal } from '~/queries/schema/schema-general'
import { AccessControlResourceType } from '~/types'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

type Mode = 'display' | 'edit'
type ColumnProps<T extends string | number> = {
    mode: Mode
    value: T
    onChange: (value: T) => void
}

function GoalNameColumn({ mode, value, onChange }: ColumnProps<string>): JSX.Element {
    if (mode === 'edit') {
        return <LemonInput value={value} onChange={onChange} placeholder="Goal name" size="small" autoFocus />
    }

    return <span>{value}</span>
}

function DueDateColumn({ mode, value, onChange }: ColumnProps<string>): JSX.Element {
    if (mode === 'edit') {
        return (
            <LemonCalendarSelectInput
                value={value ? dayjs(value) : null}
                onChange={(date) => onChange(date?.format('YYYY-MM-DD') || '')}
                placeholder="Select date"
                format="YYYY-MM-DD"
                granularity="day"
                buttonProps={{ size: 'small', fullWidth: true }}
            />
        )
    }

    return <span>{value ? dayjs(value).format('YYYY-MM-DD') : ''}</span>
}

function GoalAmountColumn({
    mode,
    value,
    onChange,
    baseCurrency,
}: ColumnProps<number> & { baseCurrency: CurrencyCode }): JSX.Element {
    const { symbol, isPrefix } = getCurrencySymbol(baseCurrency ?? CurrencyCode.USD)

    if (mode === 'edit') {
        return (
            <LemonInput
                type="number"
                value={value}
                onChange={(newValue) => onChange(newValue ?? 0)}
                placeholder="0"
                size="small"
                prefix={<span className="text-xs">{symbol}</span>}
            />
        )
    }

    return (
        <span>
            <span>{isPrefix ? symbol : ''}</span>
            {humanFriendlyNumber(value, 2, 2)}
            <span>{isPrefix ? '' : ' ' + symbol}</span>
        </span>
    )
}

function ActionsColumn({
    mode,
    onSave,
    onCancel,
    onEdit,
    onDelete,
    canSave,
    canEdit,
}: {
    mode: 'display' | 'edit'
    onSave?: () => void
    onCancel?: () => void
    onEdit?: () => void
    onDelete?: () => void
    canSave?: boolean
    canEdit?: boolean
}): JSX.Element {
    if (mode === 'edit') {
        return (
            <div className="my-2 flex gap-2 justify-end">
                <AccessControlAction resourceType={AccessControlResourceType.RevenueAnalytics} minAccessLevel="editor">
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={onSave}
                        disabledReason={!canSave ? 'All fields are required' : undefined}
                    >
                        Save
                    </LemonButton>
                </AccessControlAction>

                <LemonButton type="secondary" size="small" onClick={onCancel}>
                    Cancel
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="my-2 flex gap-2 justify-end">
            <AccessControlAction resourceType={AccessControlResourceType.RevenueAnalytics} minAccessLevel="editor">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onEdit}
                    disabledReason={!canEdit ? 'Finish editing current goal first' : undefined}
                >
                    Edit
                </LemonButton>
            </AccessControlAction>

            <AccessControlAction resourceType={AccessControlResourceType.RevenueAnalytics} minAccessLevel="editor">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconTrash />}
                    onClick={onDelete}
                    tooltip="Delete goal"
                    disabledReason={!canEdit ? 'Finish editing current goal first' : undefined}
                />
            </AccessControlAction>
        </div>
    )
}

// This is computed only once when component is loaded,
// but this isn't a big deal because this is just here to present
// a nice placeholder for the user to edit
//
// NOTE: Some extra handling if we're in storybook to avoid flappy snapshots
const nextQuarterDate = inStorybook() || inStorybookTestRunner() ? dayjs('2025-01-01') : dayjs().add(1, 'quarter')
const nextQuarter = nextQuarterDate.quarter()
const nextQuarterYear = nextQuarterDate.year()
const EMPTY_GOAL = {
    name: `Q${nextQuarter} ${nextQuarterYear}`,
    due_date: nextQuarterDate.endOf('quarter').format('YYYY-MM-DD'),
    goal: 1_000_000, // Nice round $1M MRR goal
    mrr_or_gross: 'mrr' as const,
}

export function GoalsConfiguration(): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { revenueAnalyticsConfig, goals } = useValues(revenueAnalyticsSettingsLogic)
    const { addGoal, updateGoal, deleteGoal } = useActions(revenueAnalyticsSettingsLogic)

    // It's not adding by default, but we want to show the form in storybook and test runner
    // so that they show up in the snapshots
    const [isAdding, setIsAdding] = useState(() => inStorybook() || inStorybookTestRunner())
    const [editingIndex, setEditingIndex] = useState<number | null>(null)
    const [temporaryGoal, setTemporaryGoal] = useState<RevenueAnalyticsGoal>(EMPTY_GOAL)
    const handleAddGoal = (): void => {
        if (temporaryGoal.name && temporaryGoal.due_date && temporaryGoal.goal) {
            addGoal(temporaryGoal)
            setTemporaryGoal(EMPTY_GOAL)
            setIsAdding(false)
        }
    }

    const handleEditGoal = (index: number): void => {
        const goal = goals[index]
        setEditingIndex(index)
        setTemporaryGoal(goal)
    }

    const handleSaveEdit = (): void => {
        if (editingIndex !== null && temporaryGoal.name && temporaryGoal.due_date && temporaryGoal.goal) {
            updateGoal(editingIndex, temporaryGoal)
            setEditingIndex(null)
            setTemporaryGoal(EMPTY_GOAL)
        }
    }

    const handleCancelEdit = (): void => {
        setEditingIndex(null)
        setTemporaryGoal(EMPTY_GOAL)
    }

    const handleDeleteGoal = (index: number): void => {
        deleteGoal(index)
    }

    const handleCancelAdd = (): void => {
        setIsAdding(false)
        setTemporaryGoal(EMPTY_GOAL)
    }

    // Figure out what's the "current" goal by finding the first goal in the future
    const firstGoalInFutureIndex = goals.findIndex((goal) => dayjs(goal.due_date).isSameOrAfter(dayjs()))
    const firstGoalInFutureDate = firstGoalInFutureIndex !== -1 ? goals[firstGoalInFutureIndex].due_date : null

    const getIndexInformation = useCallback(
        (index: number) => {
            const isEditingRow = editingIndex === index
            const isAddingRow = index === goals.length && isAdding
            const mode: Mode = isEditingRow || isAddingRow ? 'edit' : 'display'
            return { isEditingRow, isAddingRow, mode }
        },
        [editingIndex, goals.length, isAdding]
    )

    const columns: LemonTableColumns<RevenueAnalyticsGoal> = [
        {
            key: 'badge',
            title: '',
            width: 0,
            render: (_, goal, index) => {
                const { isEditingRow, isAddingRow } = getIndexInformation(index)
                if (isEditingRow || isAddingRow) {
                    return null
                }

                if (dayjs(goal.due_date).isBefore(dayjs())) {
                    return <LemonTag type="danger">Past</LemonTag>
                }

                // There might be more than one current since they might be for same day
                // but one for MRR and another one for gross, so compare against the date
                if (goal.due_date === firstGoalInFutureDate) {
                    return <LemonTag type="success">Current</LemonTag>
                }

                return <LemonTag type="default">Future</LemonTag>
            },
        },
        {
            key: 'name',
            title: 'Goal Name',
            render: (_, goal, index) => {
                const { isEditingRow, isAddingRow, mode } = getIndexInformation(index)
                const value = isEditingRow || isAddingRow ? temporaryGoal.name : goal.name

                return (
                    <GoalNameColumn
                        mode={mode}
                        value={value}
                        onChange={(value) => setTemporaryGoal({ ...temporaryGoal, name: value })}
                    />
                )
            },
        },
        {
            key: 'due_date',
            title: 'Due Date',
            tooltip: 'Date when this goal should be achieved',
            render: (_, goal, index) => {
                const { isEditingRow, isAddingRow, mode } = getIndexInformation(index)
                const value = isEditingRow || isAddingRow ? temporaryGoal.due_date : goal.due_date

                return (
                    <DueDateColumn
                        mode={mode}
                        value={value}
                        onChange={(value) => setTemporaryGoal({ ...temporaryGoal, due_date: value })}
                    />
                )
            },
        },
        {
            key: 'goal',
            title: `Target Amount (${baseCurrency})`,
            tooltip: 'The revenue target amount for this goal',
            render: (_, goal, index) => {
                const { isEditingRow, isAddingRow, mode } = getIndexInformation(index)
                const value = isEditingRow || isAddingRow ? temporaryGoal.goal : goal.goal

                return (
                    <GoalAmountColumn
                        mode={mode}
                        value={value}
                        onChange={(value) => setTemporaryGoal({ ...temporaryGoal, goal: value })}
                        baseCurrency={baseCurrency}
                    />
                )
            },
        },
        {
            key: 'mrr_or_gross',
            title: `MRR or Gross Revenue`,
            tooltip: 'Are you tracking MRR or gross revenue?',
            render: (_, goal, index) => {
                const { isEditingRow, isAddingRow } = getIndexInformation(index)
                const goalValue = isEditingRow || isAddingRow ? temporaryGoal.mrr_or_gross : goal.mrr_or_gross
                const checked = goalValue === 'gross' // 'gross' is to the right, therefore checked

                return (
                    <span className="flex gap-2">
                        <span className="text-sm">MRR</span>
                        <LemonSwitch
                            checked={checked}
                            onChange={(checked) =>
                                setTemporaryGoal({ ...temporaryGoal, mrr_or_gross: checked ? 'gross' : 'mrr' })
                            }
                            disabledReason={
                                !isAddingRow && !isEditingRow ? 'Only enabled when editing this goal' : undefined
                            }
                            sliderColorOverrideChecked="accent"
                            sliderColorOverrideUnchecked="accent"
                        />
                        <span className="text-sm">Gross revenue</span>
                    </span>
                )
            },
        },
        {
            key: 'actions',
            fullWidth: true,
            render: (_, __, index) => {
                const isEditingRow = editingIndex === index
                const isAddingRow = index === goals.length && isAdding
                const mode = isEditingRow || isAddingRow ? 'edit' : 'display'

                return (
                    <ActionsColumn
                        mode={mode}
                        onSave={isAddingRow ? handleAddGoal : handleSaveEdit}
                        onCancel={isAddingRow ? handleCancelAdd : handleCancelEdit}
                        onEdit={() => handleEditGoal(index)}
                        onDelete={() => handleDeleteGoal(index)}
                        canSave={!!(temporaryGoal.name && temporaryGoal.due_date && temporaryGoal.goal)}
                        canEdit={!isAddingRow && editingIndex === null}
                    />
                )
            },
        },
    ]

    // Add a row for the new goal form when adding
    const dataSource = isAdding ? [...goals, EMPTY_GOAL] : goals

    return (
        <SceneSection
            title="Goals"
            description="Set revenue targets for specific dates to track your progress. You can track goals based on your monthly/quarterly/yearly targets. These can be displayed either on your MRR/ARR or gross revenue charts on the revenue analytics dashboard!"
        >
            <div className={cn('flex flex-col items-end w-full')}>
                <AccessControlAction resourceType={AccessControlResourceType.RevenueAnalytics} minAccessLevel="editor">
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        onClick={() => setIsAdding(true)}
                        disabledReason={
                            isAdding
                                ? 'Finish adding current goal first'
                                : editingIndex !== null
                                  ? 'Finish editing current goal first'
                                  : undefined
                        }
                    >
                        Add Goal
                    </LemonButton>
                </AccessControlAction>
            </div>

            <LemonTable<RevenueAnalyticsGoal>
                columns={columns}
                dataSource={dataSource}
                loading={revenueAnalyticsConfig === null}
                onRow={(_, index) => ({
                    className: index === goals.length && isAdding ? 'my-2' : '',
                })}
                size="small"
                rowKey={(record) => `${record.name}-${record.due_date}`}
                emptyState="No goals configured yet"
            />
        </SceneSection>
    )
}
