import { useActions, useValues } from 'kea'
import { useId, useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Field,
    FieldDescription,
    FieldLabel,
    Heading,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { QuillAlertAdvancedOptions } from 'products/alerts/frontend/components/QuillAlertAdvancedOptions'
import { QuillQuietHoursFields } from 'products/alerts/frontend/components/QuillQuietHoursFields'
import { LogsAlertConfigurationThresholdOperatorEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertFormLogic } from './logsAlertFormLogic'
import { GROUPING_NEEDS_ABOVE } from './logsAlertGrouping'
import {
    applyEvaluationPeriods,
    buildCheckPattern,
    countEnabledAdvancedOptions,
    WINDOW_OPTIONS,
} from './logsAlertTriggerUtils'
import { QuillLogsAlertGroupByField } from './QuillLogsAlertGroupByField'

function QuillCheckDotsTooltip({ datapoints, periods }: { datapoints: number; periods: number }): JSX.Element {
    const checks = useMemo(() => buildCheckPattern(datapoints, periods), [datapoints, periods])

    return (
        <Tooltip>
            <TooltipTrigger
                render={<span className="inline-flex text-muted-foreground" />}
                aria-label={`${datapoints} of ${periods} checks must match to fire`}
            >
                <IconInfo className="size-4" />
            </TooltipTrigger>
            <TooltipContent>
                <div className="flex flex-col gap-1 py-0.5 text-start">
                    <span>
                        {datapoints} of {periods} checks must match to fire
                    </span>
                    <span className="flex items-center gap-1.5">
                        {checks.map((matched, i) => (
                            <span
                                key={i}
                                className={cn(
                                    'size-3 rounded-full border',
                                    matched
                                        ? 'border-destructive-foreground bg-destructive'
                                        : 'border-success-foreground bg-success'
                                )}
                                title={`Check ${i + 1}: ${matched ? 'matched' : 'ok'}`}
                            />
                        ))}
                        <span>→</span>
                        <span className="font-semibold">fires</span>
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1">
                            <span className="inline-block size-2 rounded-full border border-destructive-foreground bg-destructive" />
                            matched
                        </span>
                        <span className="inline-flex items-center gap-1">
                            <span className="inline-block size-2 rounded-full border border-success-foreground bg-success" />
                            OK
                        </span>
                    </span>
                </div>
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillLogsAlertTrigger(): JSX.Element {
    const { alertForm } = useValues(logsAlertFormLogic)
    const { timezone } = useValues(teamLogic)
    const { setAlertFormValue } = useActions(logsAlertFormLogic)
    const idPrefix = useId()
    const enabledAdvancedOptionsCount = countEnabledAdvancedOptions(alertForm)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h4 className="m-0" />}>
                    Trigger condition
                </Heading>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <Text size="xs" render={<span />}>
                        Alert if count goes
                    </Text>
                    <ToggleGroup
                        variant="outline"
                        aria-label="Alert if count goes"
                        value={[alertForm.thresholdOperator]}
                        onValueChange={(next: string[]) => {
                            const picked = next[0] as LogsAlertConfigurationThresholdOperatorEnumApi | undefined
                            if (picked) {
                                setAlertFormValue('thresholdOperator', picked)
                            }
                        }}
                    >
                        <ToggleGroupItem value={LogsAlertConfigurationThresholdOperatorEnumApi.Above}>
                            above
                        </ToggleGroupItem>
                        <ToggleGroupItem
                            value={LogsAlertConfigurationThresholdOperatorEnumApi.Below}
                            disabledReason={alertForm.groupBy === 'none' ? undefined : GROUPING_NEEDS_ABOVE}
                        >
                            below
                        </ToggleGroupItem>
                    </ToggleGroup>
                    <NumberFieldRoot
                        value={alertForm.thresholdCount}
                        onValueChange={(value: number | null) => setAlertFormValue('thresholdCount', value ?? 0)}
                        min={0}
                        className="w-24"
                    >
                        <NumberFieldGroup>
                            <NumberFieldInput aria-label="Log count" data-attr="logs-alert-threshold-count" />
                        </NumberFieldGroup>
                    </NumberFieldRoot>
                    <Text size="xs" render={<span />}>
                        in the last
                    </Text>
                    <Select
                        items={WINDOW_OPTIONS}
                        value={alertForm.windowMinutes}
                        onValueChange={(value) => setAlertFormValue('windowMinutes', value ?? 10)}
                    >
                        <SelectTrigger aria-label="Window">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {WINDOW_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            </div>
            <QuillLogsAlertGroupByField />
            <QuillAlertAdvancedOptions enabledCount={enabledAdvancedOptionsCount}>
                <Field>
                    <FieldLabel htmlFor={`${idPrefix}-datapoints`}>
                        <span className="inline-flex items-center gap-1">
                            Reduce noise
                            <Tooltip>
                                <TooltipTrigger
                                    render={<span className="inline-flex text-muted-foreground" />}
                                    aria-label="About reducing noise"
                                >
                                    <IconInfo className="size-4" />
                                </TooltipTrigger>
                                <TooltipContent className="max-w-80">
                                    Require the condition to be met multiple times before the alert fires. This prevents
                                    notifications on brief, one-off spikes.
                                </TooltipContent>
                            </Tooltip>
                        </span>
                    </FieldLabel>
                    <div className="flex flex-wrap items-center gap-2">
                        <NumberFieldRoot
                            value={alertForm.datapointsToAlarm}
                            onValueChange={(value: number | null) => setAlertFormValue('datapointsToAlarm', value ?? 1)}
                            min={1}
                            max={alertForm.evaluationPeriods}
                            className="w-16"
                        >
                            <NumberFieldGroup>
                                <NumberFieldInput id={`${idPrefix}-datapoints`} />
                            </NumberFieldGroup>
                        </NumberFieldRoot>
                        <Text size="xs" render={<span />}>
                            of
                        </Text>
                        <NumberFieldRoot
                            value={alertForm.evaluationPeriods}
                            onValueChange={(value: number | null) =>
                                applyEvaluationPeriods(alertForm, value ?? undefined, setAlertFormValue)
                            }
                            min={alertForm.datapointsToAlarm}
                            max={10}
                            className="w-16"
                        >
                            <NumberFieldGroup>
                                <NumberFieldInput aria-label="Checks" />
                            </NumberFieldGroup>
                        </NumberFieldRoot>
                        <Text size="xs" render={<span />}>
                            checks must match to fire
                        </Text>
                        <QuillCheckDotsTooltip
                            datapoints={alertForm.datapointsToAlarm}
                            periods={alertForm.evaluationPeriods}
                        />
                    </div>
                    <FieldDescription>The alert auto-resolves once the condition is no longer met.</FieldDescription>
                </Field>
                <Field>
                    <FieldLabel htmlFor={`${idPrefix}-cooldown`}>Notification cooldown</FieldLabel>
                    <div className="flex flex-wrap items-center gap-2">
                        <NumberFieldRoot
                            value={alertForm.cooldownMinutes}
                            onValueChange={(value: number | null) => setAlertFormValue('cooldownMinutes', value ?? 0)}
                            min={0}
                            className="w-24"
                        >
                            <NumberFieldGroup>
                                <NumberFieldInput id={`${idPrefix}-cooldown`} />
                            </NumberFieldGroup>
                        </NumberFieldRoot>
                        <Text size="xs" render={<span />}>
                            minutes
                        </Text>
                    </div>
                    <FieldDescription className="flex flex-col gap-1">
                        <span>Set to 0 for no minimum.</span>
                        <span>The alert notifies once when it starts firing, and once when it resolves.</span>
                        <span>It does not re-notify unless it resolves and then fires again.</span>
                        <span>
                            Cooldown sets the minimum time between notifications. No notifications are sent during
                            cooldown.
                        </span>
                        <span>Cooldown does not apply to PagerDuty incidents.</span>
                    </FieldDescription>
                </Field>
                <QuillQuietHoursFields
                    scheduleRestriction={alertForm.scheduleRestriction}
                    cadenceMinutes={5}
                    teamTimezone={timezone}
                    onChange={(next) => setAlertFormValue('scheduleRestriction', next)}
                />
            </QuillAlertAdvancedOptions>
        </div>
    )
}
