import { IconGear, IconTrash } from '@posthog/icons'
import { LemonColorGlyph, LemonColorPicker } from '@posthog/lemon-ui'
import { Button, Input, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { getSeriesColorPalette } from 'lib/colors'
import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import { QuillChartOptionToggleGroup } from 'lib/components/ChartOptions/QuillChartOptionToggleGroup'
import { useChartOptionNumberDraft } from 'lib/components/ChartOptions/useChartOptionNumberDraft'

import { GoalLine } from '~/queries/schema/schema-general'

interface QuillGoalLineRowProps {
    goalLine: GoalLine
    index: number
    updateGoalLine: (index: number, key: keyof GoalLine, value: NonNullable<string | number | boolean>) => void
    removeGoalLine: (index: number) => void
}

export function QuillGoalLineRow({
    goalLine: { label, value = 0, displayLabel = true, position, borderColor },
    index,
    updateGoalLine,
    removeGoalLine,
}: QuillGoalLineRowProps): JSX.Element {
    const valueDraft = useChartOptionNumberDraft(value, (next) => updateGoalLine(index, 'value', next ?? 0))

    return (
        <div className="flex w-full items-center gap-1">
            <LemonColorPicker
                colors={getSeriesColorPalette()}
                selectedColor={borderColor || undefined}
                onSelectColor={(color) => updateGoalLine(index, 'borderColor', color)}
                showCustomColor
                customButton={
                    <Button size="icon" aria-label="Goal line color" className="shrink-0">
                        <LemonColorGlyph color={borderColor} size="small" />
                    </Button>
                }
            />
            <Input
                size="sm"
                placeholder="Label"
                aria-label="Goal line label"
                className="min-w-0 flex-1"
                value={label}
                onChange={(event) => updateGoalLine(index, 'label', event.target.value)}
            />
            <Input
                size="sm"
                type="text"
                inputMode="decimal"
                placeholder="Value"
                aria-label="Goal line value"
                className="w-20 shrink-0"
                value={valueDraft.draft}
                onChange={(event) => valueDraft.setDraft(event.target.value)}
                onBlur={valueDraft.commit}
                onKeyDown={(event) => event.key === 'Enter' && valueDraft.commit()}
            />
            <Popover>
                <PopoverTrigger
                    render={
                        <Button
                            size="icon"
                            aria-label="Goal line settings"
                            tooltip="Label settings"
                            className="shrink-0"
                        >
                            <IconGear />
                        </Button>
                    }
                />
                <PopoverContent align="end" className="w-60 gap-3">
                    <QuillChartOptionSwitch
                        label="Show label"
                        checked={displayLabel}
                        onChange={(checked) => updateGoalLine(index, 'displayLabel', checked)}
                        data-attr="goal-line-show-label-switch"
                    />
                    <QuillChartOptionToggleGroup
                        label="Label position"
                        value={position ?? 'end'}
                        options={[
                            { value: 'start', label: 'Start' },
                            { value: 'end', label: 'End' },
                        ]}
                        onChange={(next) => updateGoalLine(index, 'position', next)}
                        disabledReason={displayLabel ? undefined : 'Turn on the label to change its position.'}
                        data-attr="goal-line-position-selector"
                    />
                </PopoverContent>
            </Popover>
            <Button
                size="icon"
                aria-label="Delete goal line"
                tooltip="Delete goal line"
                className="shrink-0"
                onClick={() => removeGoalLine(index)}
            >
                <IconTrash />
            </Button>
        </div>
    )
}
