import { useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Input, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { GoalLine } from '~/queries/schema/schema-general'

export interface ChartGoalLineRowProps {
    goalLine: GoalLine
    /** The line's place in the list, counted from one, to tell the rows apart for a screen reader. */
    position: number
    onChange: (changes: Partial<GoalLine>) => void
    onRemove: () => void
}

export function ChartGoalLineRow({ goalLine, position, onChange, onRemove }: ChartGoalLineRowProps): JSX.Element {
    const [labelDraft, setLabelDraft] = useState(goalLine.label)
    const [valueDraft, setValueDraft] = useState(String(goalLine.value))

    useEffect(() => {
        setLabelDraft(goalLine.label)
    }, [goalLine.label])

    useEffect(() => {
        setValueDraft(String(goalLine.value))
    }, [goalLine.value])

    // Commit when a field is left, so the chart does not reload on every key press.
    const commitLabel = (): void => {
        if (labelDraft !== goalLine.label) {
            onChange({ label: labelDraft })
        }
    }
    const commitValue = (): void => {
        const parsed = valueDraft.trim() === '' ? 0 : Number(valueDraft)
        const value = Number.isFinite(parsed) ? parsed : goalLine.value
        setValueDraft(String(value))
        if (value !== goalLine.value) {
            onChange({ value })
        }
    }

    return (
        <li className="flex items-center gap-2" data-attr="quill-insight-chart-setting-goal-line">
            <Input
                className="min-w-0 flex-1"
                aria-label={`Label of goal line ${position}`}
                placeholder="Label"
                value={labelDraft}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => setLabelDraft(event.target.value)}
                onBlur={commitLabel}
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Enter') {
                        commitLabel()
                    }
                }}
                data-attr="quill-insight-chart-setting-goal-line-label"
            />
            <Input
                type="number"
                step="any"
                className="w-24 shrink-0"
                aria-label={`Value of goal line ${position}`}
                placeholder="Value"
                value={valueDraft}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => setValueDraft(event.target.value)}
                onBlur={commitValue}
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Enter') {
                        commitValue()
                    }
                }}
                data-attr="quill-insight-chart-setting-goal-line-value"
            />
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon"
                            aria-label={`Remove goal line ${position}`}
                            onClick={onRemove}
                            data-attr="quill-insight-chart-setting-goal-line-remove"
                        />
                    }
                >
                    <IconX />
                </TooltipTrigger>
                <TooltipContent>Remove goal line</TooltipContent>
            </Tooltip>
        </li>
    )
}
