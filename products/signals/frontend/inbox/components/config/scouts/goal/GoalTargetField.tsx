import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import { shortDate } from '../../../../utils/goal/format'
import { formatMeasure } from '../../../../utils/goal/insightMetric'

const LIFTS = [0.1, 0.25, 0.5]

const rounded = (value: number): string => String(Number(value.toPrecision(3)))

export function GoalTargetField(): JSX.Element {
    const {
        goalForm,
        reading,
        display,
        previewLoading,
        unit,
        targetChange,
        direction,
        needsDirection,
        fieldErrors,
        locked,
    } = useValues(goalScoutFormLogic)
    const { setGoalFormValue, touchGoalFormField } = useActions(goalScoutFormLogic)
    const prefix = goalForm.goal_insight ? display.prefix : ''
    const changeText =
        targetChange === null
            ? undefined
            : `${new Intl.NumberFormat('en-US', {
                  style: 'percent',
                  maximumFractionDigits: Math.abs(targetChange) < 0.1 ? 1 : 0,
              }).format(
                  Math.abs(targetChange)
              )} ${targetChange > 0 ? 'higher' : 'lower'} than ${reading?.stale ? 'the last value' : 'now'}`
    const suggestions =
        reading !== null && reading.value > 0 && !goalForm.target.trim()
            ? LIFTS.map((lift) => ({ lift, value: rounded(reading.value * (1 + lift)) }))
            : []

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
                <div className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">
                        {reading?.stale ? `Last value, ${shortDate(reading.date)}` : 'Now'}
                    </span>
                    <div className="flex h-8 items-center" aria-live="polite">
                        {previewLoading ? (
                            <LemonSkeleton className="h-5 w-16" />
                        ) : reading === null ? (
                            <span className="text-sm text-secondary">No value yet</span>
                        ) : (
                            <span className="text-lg font-semibold tabular-nums">
                                {formatMeasure(reading.value, display)}
                            </span>
                        )}
                    </div>
                </div>
                <IconArrowRight className="mb-2 size-4 text-tertiary" />
                <div className="flex flex-col gap-1">
                    <label htmlFor="goal-target" className="text-xs font-semibold text-secondary">
                        Target
                    </label>
                    <LemonInput
                        id="goal-target"
                        className="w-36"
                        size="small"
                        inputMode="decimal"
                        autoComplete="off"
                        value={goalForm.target}
                        status={fieldErrors.target ? 'danger' : 'default'}
                        onChange={(value) => setGoalFormValue('target', value.replace(',', '.'))}
                        onBlur={() => touchGoalFormField('target')}
                        placeholder="Value to reach"
                        prefix={prefix ? <span className="text-secondary">{prefix}</span> : undefined}
                        suffix={unit ? <span className="text-secondary">{unit}</span> : undefined}
                        data-attr="goal-scout-form-target"
                    />
                </div>
                {needsDirection && !locked && (
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold text-secondary">Should it go</span>
                        <LemonSegmentedButton
                            size="small"
                            value={direction}
                            onChange={(value) => setGoalFormValue('direction', value)}
                            options={[
                                { value: 'increase', label: 'Up' },
                                { value: 'decrease', label: 'Down' },
                            ]}
                            data-attr="goal-scout-form-direction"
                        />
                    </div>
                )}
                {changeText && !fieldErrors.target && <span className="mb-2 text-xs text-secondary">{changeText}</span>}
            </div>
            {fieldErrors.target ? (
                <span className="text-xs text-danger">{fieldErrors.target}</span>
            ) : (
                suggestions.length > 0 && (
                    <span className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                        Try
                        {suggestions.map(({ lift, value }) => (
                            <LemonButton
                                key={lift}
                                size="xsmall"
                                type="secondary"
                                onClick={() => {
                                    setGoalFormValue('target', value)
                                    touchGoalFormField('target')
                                }}
                                data-attr="goal-scout-form-target-suggestion"
                            >
                                {formatMeasure(Number(value), display)} (+{lift * 100}%)
                            </LemonButton>
                        ))}
                    </span>
                )
            )}
        </div>
    )
}
