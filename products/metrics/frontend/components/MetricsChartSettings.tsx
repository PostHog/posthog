import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect, LemonSwitch, Popover } from '@posthog/lemon-ui'

import { GoalLinesList } from 'lib/components/GoalLinesList'

import { metricsViewerLogic } from './metricsViewerLogic'

// An emptied number input reads as NaN, which the chart ignores while the settings count still
// sees a value — so it has to become undefined for the bound to be clearable.
const asBound = (value: number | undefined): number | undefined =>
    typeof value === 'number' && isFinite(value) ? value : undefined

export function MetricsChartSettings(): JSX.Element {
    const { displayType, goalLines, yAxisSettings } = useValues(metricsViewerLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine, setYAxisSetting } = useActions(metricsViewerLogic)
    const [open, setOpen] = useState(false)

    const [minDraft, setMinDraft] = useState(yAxisSettings.min)
    const [maxDraft, setMaxDraft] = useState(yAxisSettings.max)
    useEffect(() => setMinDraft(yAxisSettings.min), [yAxisSettings.min])
    useEffect(() => setMaxDraft(yAxisSettings.max), [yAxisSettings.max])

    const isLog = yAxisSettings.scale === 'log'
    // Bars encode magnitude as length from zero, so quill ignores a floated axis on them.
    const isBar = displayType === 'bar'
    const beginsAtZero = yAxisSettings.startAtZero !== false
    const boundsDisabledReason = isLog
        ? 'Not available on a logarithmic scale'
        : isBar
          ? 'Not available on a bar chart'
          : undefined
    const minDisabledReason =
        boundsDisabledReason ?? (beginsAtZero ? 'Turn off "Begin at zero" to set a minimum' : undefined)

    // Counts the persisted settings, not the drafts — a bound of 0 is still a bound.
    const changedCount =
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
                            disabledReason={isLog ? 'Not available on a logarithmic scale' : undefined}
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
                                    disabledReason={boundsDisabledReason}
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
