import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { AlertAdvancedOptions } from 'products/alerts/frontend/components/AlertAdvancedOptions'
import { AlertDefinitionRow } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertEditorSection } from 'products/alerts/frontend/components/AlertEditor'
import { QuietHoursFields } from 'products/alerts/frontend/components/QuietHoursFields'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { SeverityLevelsFilter } from 'products/logs/frontend/components/LogsViewer/Filters/SeverityLevelsFilter'
import { LogsAlertConfigurationThresholdOperatorEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { AlertFilterGroup } from './LogsAlertFilterGroup'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { LogsAlertGroupByField } from './LogsAlertGroupByField'
import { GROUPING_NEEDS_ABOVE } from './logsAlertGrouping'
import {
    applyEvaluationPeriods,
    buildCheckPattern,
    countEnabledAdvancedOptions,
    WINDOW_OPTIONS,
} from './logsAlertTriggerUtils'

function CheckDots({ checks }: { checks: boolean[] }): JSX.Element {
    return (
        <>
            {checks.map((matched, i) => (
                <div
                    key={i}
                    className={`w-3 h-3 rounded-full border ${
                        matched ? 'bg-danger-highlight border-danger' : 'bg-success-highlight border-success'
                    }`}
                    title={`Check ${i + 1}: ${matched ? 'matched' : 'ok'}`}
                />
            ))}
        </>
    )
}

function CheckDotsTooltip({ datapoints, periods }: { datapoints: number; periods: number }): JSX.Element {
    const checks = useMemo(() => buildCheckPattern(datapoints, periods), [datapoints, periods])

    return (
        <Tooltip
            title={
                <div className="space-y-1 py-0.5">
                    <div className="text-xs">
                        {datapoints} of {periods} checks must match to fire
                    </div>
                    <div className="flex items-center gap-1.5">
                        <CheckDots checks={checks} />
                        <span className="text-xs">→</span>
                        <span className="text-xs font-semibold text-danger">fires</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-secondary">
                        <span className="inline-flex items-center gap-1">
                            <span className="inline-block w-2 h-2 rounded-full bg-danger-highlight border border-danger" />
                            matched
                        </span>
                        <span className="inline-flex items-center gap-1">
                            <span className="inline-block w-2 h-2 rounded-full bg-success-highlight border border-success" />
                            OK
                        </span>
                    </div>
                </div>
            }
        >
            <IconInfo className="text-base text-secondary" />
        </Tooltip>
    )
}

export function LogsAlertForm(): JSX.Element {
    return (
        <div className="space-y-6 max-w-2xl">
            <AlertEditorSection
                title="Definition"
                description="Checks run every 5 minutes. Each check queries logs matching these filters."
            >
                <div className="space-y-5">
                    <LogsAlertFilters />
                    <LogsAlertTrigger />
                </div>
            </AlertEditorSection>
        </div>
    )
}

export function LogsAlertFilters({ filterError }: { filterError?: string }): JSX.Element {
    const { alertForm } = useValues(logsAlertFormLogic)
    const { setAlertFormValue } = useActions(logsAlertFormLogic)
    const handleFilterGroupChange = useCallback(
        (group: UniversalFiltersGroup) => setAlertFormValue('filterGroup', group),
        [setAlertFormValue]
    )

    return (
        <div className="space-y-3">
            <h4 className="m-0">Filters</h4>
            {filterError ? <LemonField.Error error={filterError} /> : null}
            <div className="grid max-w-3xl gap-3 md:grid-cols-2">
                <LemonField name="severityLevels" label="Severity">
                    <SeverityLevelsFilter
                        value={alertForm.severityLevels}
                        onChange={(levels) => setAlertFormValue('severityLevels', levels)}
                        showBulkActions
                    />
                </LemonField>
                <LemonField.Pure label="Service">
                    <ServiceFilter
                        value={alertForm.serviceNames}
                        onChange={(names) => setAlertFormValue('serviceNames', names)}
                    />
                </LemonField.Pure>
            </div>
            <LemonField name="filterGroup" label="Attributes">
                <AlertFilterGroup filterGroup={alertForm.filterGroup} onChange={handleFilterGroupChange} />
            </LemonField>
        </div>
    )
}

export function LogsAlertTrigger(): JSX.Element {
    const { alertForm } = useValues(logsAlertFormLogic)
    const { timezone } = useValues(teamLogic)
    const { setAlertFormValue } = useActions(logsAlertFormLogic)
    const enabledAdvancedOptionsCount = countEnabledAdvancedOptions(alertForm)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <h4 className="m-0">Trigger condition</h4>
                <AlertDefinitionRow label="Alert if count goes">
                    <LemonSegmentedButton
                        value={alertForm.thresholdOperator}
                        onChange={(value) => setAlertFormValue('thresholdOperator', value)}
                        options={[
                            { value: LogsAlertConfigurationThresholdOperatorEnumApi.Above, label: 'above' },
                            {
                                value: LogsAlertConfigurationThresholdOperatorEnumApi.Below,
                                label: 'below',
                                disabledReason: alertForm.groupBy === 'none' ? undefined : GROUPING_NEEDS_ABOVE,
                            },
                        ]}
                        size="small"
                    />
                    <LemonInput
                        type="number"
                        min={0}
                        value={alertForm.thresholdCount}
                        onChange={(value) => setAlertFormValue('thresholdCount', value ?? 0)}
                        className="w-24"
                        size="small"
                        data-attr="logs-alert-threshold-count"
                    />
                    <span className="text-sm">in the last</span>
                    <LemonSelect
                        value={alertForm.windowMinutes}
                        onChange={(value) => setAlertFormValue('windowMinutes', value ?? 10)}
                        options={WINDOW_OPTIONS}
                        size="small"
                    />
                </AlertDefinitionRow>
            </div>
            <LogsAlertGroupByField />
            <AlertAdvancedOptions enabledCount={enabledAdvancedOptionsCount}>
                <LemonField.Pure
                    label={
                        <span className="inline-flex items-center gap-1">
                            Reduce noise
                            <Tooltip title="Require the condition to be met multiple times before the alert fires. This prevents notifications on brief, one-off spikes.">
                                <IconInfo className="text-base text-secondary" />
                            </Tooltip>
                        </span>
                    }
                >
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 flex-wrap">
                            <LemonInput
                                type="number"
                                min={1}
                                max={alertForm.evaluationPeriods}
                                value={alertForm.datapointsToAlarm}
                                onChange={(value) => setAlertFormValue('datapointsToAlarm', value ?? 1)}
                                className="w-16"
                                size="small"
                            />
                            <span className="text-sm">of</span>
                            <LemonInput
                                type="number"
                                min={alertForm.datapointsToAlarm}
                                max={10}
                                value={alertForm.evaluationPeriods}
                                onChange={(value) => applyEvaluationPeriods(alertForm, value, setAlertFormValue)}
                                className="w-16"
                                size="small"
                            />
                            <span className="text-sm">checks must match to fire</span>
                            <CheckDotsTooltip
                                datapoints={alertForm.datapointsToAlarm}
                                periods={alertForm.evaluationPeriods}
                            />
                        </div>
                        <p className="text-xs text-secondary m-0">
                            The alert auto-resolves once the condition is no longer met.
                        </p>
                    </div>
                </LemonField.Pure>
                <LemonField.Pure
                    label="Notification cooldown"
                    help={
                        <div className="flex flex-col gap-1">
                            <span>Set to 0 for no minimum.</span>
                            <span>The alert notifies once when it starts firing, and once when it resolves.</span>
                            <span>It does not re-notify unless it resolves and then fires again.</span>
                            <span>
                                Cooldown sets the minimum time between notifications. No notifications are sent during
                                cooldown.
                            </span>
                            <span>Cooldown does not apply to PagerDuty incidents.</span>
                        </div>
                    }
                >
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            min={0}
                            value={alertForm.cooldownMinutes}
                            onChange={(value) => setAlertFormValue('cooldownMinutes', value ?? 0)}
                            className="w-24"
                            size="small"
                        />
                        <span className="text-sm">minutes</span>
                    </div>
                </LemonField.Pure>
                <QuietHoursFields
                    scheduleRestriction={alertForm.scheduleRestriction}
                    cadenceMinutes={5}
                    teamTimezone={timezone}
                    onChange={(next) => setAlertFormValue('scheduleRestriction', next)}
                />
            </AlertAdvancedOptions>
        </div>
    )
}
