import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect, LemonSwitch, Popover } from '@posthog/lemon-ui'

import { GoalLinesList } from 'lib/components/GoalLinesList'

import type { MetricsReducer } from '~/queries/schema/schema-general'

import { METRICS_PANELS } from '../panels/registry'
import { DEFAULT_REDUCER, metricsViewerLogic } from './metricsViewerLogic'

const REDUCER_OPTIONS: { value: MetricsReducer; label: string }[] = [
    { value: 'last', label: 'Latest' },
    { value: 'mean', label: 'Average' },
    { value: 'min', label: 'Minimum' },
    { value: 'max', label: 'Maximum' },
    { value: 'sum', label: 'Total' },
    { value: 'delta', label: 'Change' },
]

// An emptied number input reads as NaN, which the chart ignores while the settings count still
// sees a value — so it has to become undefined for the bound to be clearable.
const asBound = (value: number | undefined): number | undefined =>
    typeof value === 'number' && isFinite(value) ? value : undefined

export function MetricsChartSettings(): JSX.Element {
    const { displayType, goalLines, yAxisSettings, reduce } = useValues(metricsViewerLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine, setYAxisSetting, setReduce } = useActions(metricsViewerLogic)
    const [open, setOpen] = useState(false)

    const [minDraft, setMinDraft] = useState(yAxisSettings.min)
    const [maxDraft, setMaxDraft] = useState(yAxisSettings.max)
    useEffect(() => setMinDraft(yAxisSettings.min), [yAxisSettings.min])
    useEffect(() => setMaxDraft(yAxisSettings.max), [yAxisSettings.max])

    const showsReducer = !!METRICS_PANELS[displayType]?.reducesSeries
    const isLog = yAxisSettings.scale === 'log'
    // Bars encode magnitude as length from zero, so quill ignores both a floated baseline and pinned
    // bounds on them. The settings stay persisted and apply again on a line or area chart.
    const isBar = displayType === 'bar'
    const beginsAtZero = yAxisSettings.startAtZero !== false
    const rangeDisabledReason = isLog
        ? 'Not available on a logarithmic scale'
        : isBar
          ? 'Not available on a bar chart'
          : undefined
    const minDisabledReason =
        rangeDisabledReason ?? (beginsAtZero ? 'Turn off "Begin at zero" to set a minimum' : undefined)

    // Counts the persisted settings, not the drafts — a bound of 0 is still a bound.
    const changedCount =
        (showsReducer && reduce !== DEFAULT_REDUCER ? 1 : 0) +
        goalLines.length +
        (yAxisSettings.scale ? 1 : 0) +
        (beginsAtZero ? 0 : 1) +
        (yAxisSettings.min !== undefined ? 1 : 0) +
        (yAxisSettings.max !== undefined ? 1 : 0)

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="flex flex-col gap-3 p-2 w-72">
                    {showsReducer && (
                        <div className="flex flex-col gap-1">
                            <LemonLabel info="How each series becomes one number over the selected time range. Change is the latest value minus the first.">
                                Value
                            </LemonLabel>
                            <LemonSelect
                                size="small"
                                value={reduce}
                                onChange={setReduce}
                                options={REDUCER_OPTIONS}
                                data-attr="metrics-value-reducer"
                            />
                        </div>
                    )}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Goal lines</LemonLabel>
                        <GoalLinesList
                            goalLines={goalLines}
                            updateGoalLine={updateGoalLine}
                            removeGoalLine={removeGoalLine}
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlusSmall />}
                            onClick={addGoalLine}
                            data-attr="metrics-add-goal-line"
                            className="self-start"
                        >
                            Add goal line
                        </LemonButton>
                    </div>
                    <div className="flex flex-col gap-2">
                        <LemonLabel>Y axis</LemonLabel>
                        <LemonSelect
                            size="small"
                            value={yAxisSettings.scale ?? 'linear'}
                            onChange={(value) => setYAxisSetting('scale', value === 'linear' ? undefined : value)}
                            options={[
                                { value: 'linear', label: 'Linear' },
                                { value: 'log', label: 'Logarithmic' },
                            ]}
                            data-attr="metrics-y-axis-scale"
                        />
                        <LemonSwitch
                            label="Begin at zero"
                            tooltip="When off, the axis starts just below your lowest value, so small changes are easier to see."
                            checked={beginsAtZero}
                            disabledReason={rangeDisabledReason}
                            onChange={(checked) => setYAxisSetting('startAtZero', checked ? undefined : false)}
                            data-attr="metrics-y-axis-start-at-zero"
                        />
                        <div className="flex gap-2">
                            <div className="flex-1 flex flex-col gap-1">
                                <LemonLabel>Minimum</LemonLabel>
                                <LemonInput
                                    type="number"
                                    size="small"
                                    placeholder="Auto"
                                    value={minDraft}
                                    disabledReason={minDisabledReason}
                                    onChange={setMinDraft}
                                    // Commit on blur, not on change: a number input reads as empty
                                    // mid-entry, so every keystroke would clear the bound.
                                    onBlur={() => setYAxisSetting('min', asBound(minDraft))}
                                    onPressEnter={() => setYAxisSetting('min', asBound(minDraft))}
                                    data-attr="metrics-y-axis-min"
                                />
                            </div>
                            <div className="flex-1 flex flex-col gap-1">
                                <LemonLabel>Maximum</LemonLabel>
                                <LemonInput
                                    type="number"
                                    size="small"
                                    placeholder="Auto"
                                    value={maxDraft}
                                    disabledReason={rangeDisabledReason}
                                    onChange={setMaxDraft}
                                    onBlur={() => setYAxisSetting('max', asBound(maxDraft))}
                                    onPressEnter={() => setYAxisSetting('max', asBound(maxDraft))}
                                    data-attr="metrics-y-axis-max"
                                />
                            </div>
                        </div>
                        <span className="text-xs text-secondary">
                            {yAxisSettings.min !== undefined && yAxisSettings.max !== undefined
                                ? 'Setting both bounds hides a goal line that falls outside them.'
                                : 'Leave blank for an automatic bound.'}
                        </span>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconGear />}
                onClick={() => setOpen(!open)}
                active={open}
                sideIcon={changedCount > 0 ? <span className="text-xs text-secondary">{changedCount}</span> : undefined}
                data-attr="metrics-chart-settings"
            >
                Options
            </LemonButton>
        </Popover>
    )
}
