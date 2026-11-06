import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGraph, IconPencil, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import type { GoalInsightOption } from '../../../../utils/goal/form'

export interface GoalInsightPickerProps {
    buttonId?: string
    value: string
    options: GoalInsightOption[]
    placeholder: string
    invalid?: boolean
    compact?: boolean
    onSelect: (insight: string) => void
    onClose?: () => void
    onDescribe?: () => void
}

export function GoalInsightPicker({
    buttonId,
    value,
    options,
    placeholder,
    invalid = false,
    compact = false,
    onSelect,
    onClose,
    onDescribe,
}: GoalInsightPickerProps): JSX.Element {
    const { insightSearch, insightsLoading, insightNames } = useValues(goalScoutFormLogic)
    const { setInsightSearch } = useActions(goalScoutFormLogic)
    const [open, setOpen] = useState(false)
    const label = value ? (insightNames[value] ?? value) : ''
    const choose = (insight: string): void => {
        setOpen(false)
        onSelect(insight)
    }

    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={(next) => {
                setOpen(next)
                if (next) {
                    setInsightSearch('')
                } else {
                    onClose?.()
                }
            }}
            closeOnClickInside={false}
            matchWidth={!compact}
            placement="bottom-start"
            overlay={
                <div className="flex max-w-[calc(100vw-2rem)] min-w-72 flex-col gap-1">
                    <LemonInput
                        type="search"
                        size="small"
                        autoFocus
                        fullWidth
                        placeholder="Search insights"
                        value={insightSearch}
                        onChange={setInsightSearch}
                        onPressEnter={() => {
                            const first = options.find((option) => !option.disabledReason)
                            if (first) {
                                choose(first.value)
                            }
                        }}
                    />
                    <div className="flex max-h-72 flex-col overflow-y-auto">
                        {options.length === 0 ? (
                            <span className="p-2 text-sm text-secondary">
                                {insightsLoading ? 'Loading insights…' : 'No saved insights match.'}
                            </span>
                        ) : (
                            options.map((option) => (
                                <LemonButton
                                    key={option.value}
                                    size="small"
                                    fullWidth
                                    active={option.value === value}
                                    disabledReason={option.disabledReason ?? undefined}
                                    onClick={() => choose(option.value)}
                                >
                                    <span className="truncate">{option.label}</span>
                                </LemonButton>
                            ))
                        )}
                    </div>
                    {onDescribe && (
                        <div className="border-t border-primary pt-1">
                            <LemonButton
                                size="small"
                                fullWidth
                                icon={<IconPencil />}
                                onClick={() => {
                                    setOpen(false)
                                    onDescribe()
                                }}
                                data-attr="goal-scout-form-describe-goal"
                            >
                                None fits? Describe how to measure it
                            </LemonButton>
                        </div>
                    )}
                </div>
            }
        >
            <LemonButton
                id={buttonId}
                type="secondary"
                size={compact ? 'xsmall' : 'medium'}
                status={invalid ? 'danger' : 'default'}
                icon={compact ? <IconPlus /> : <IconGraph />}
                fullWidth={!compact}
            >
                <span className={label || compact ? 'truncate' : 'truncate text-secondary'}>
                    {label || (insightsLoading && !compact ? 'Loading insights…' : placeholder)}
                </span>
            </LemonButton>
        </LemonDropdown>
    )
}
