import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLabel,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Slider,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import {
    MINIMUM_DETECTABLE_EFFECT_MAX,
    MINIMUM_DETECTABLE_EFFECT_MIN,
    type DetectableEffectCheckpoint,
    ManualCalculatorMetricType,
    describeCheckpointDay,
    describeUseButton,
    formatDetectableEffect,
} from 'scenes/experiments/RunningTimeCalculator/calculations'
import { runningTimeLogic } from 'scenes/experiments/RunningTimeCalculator/runningTimeLogic'

import { Experiment } from '~/types'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'

import { formatCheckpointDate } from './DetectableEffectTable'
import {
    AUTOMATIC_MODE_DISABLED_REASON,
    EXPOSURES_PER_DAY_HELP,
    MANUAL_MODE_HELP,
    METRIC_TYPE_OPTIONS,
    MINIMUM_DETECTABLE_EFFECT_HELP,
    MINIMUM_DETECTABLE_EFFECT_RANGE_ERROR,
    NOT_ENOUGH_DATA_NOTE,
    OUT_OF_REACH_TOOLTIP,
    clampBaseline,
    detectableEffectFootnote,
    formatRunningTime,
    getBaselineHelp,
    getBaselineLabel,
    metricTypeChange,
    useMinimumDetectableEffectDraft,
} from './runningTimeConfigModel'

function QuillMinimumDetectableEffectField({
    value,
    onChange,
}: {
    value: number
    onChange: (value: number) => void
}): JSX.Element {
    const { draft, setDraftValue, commitDraft, outOfRange } = useMinimumDetectableEffectDraft(value, onChange)

    return (
        <Field data-invalid={outOfRange || undefined}>
            <FieldLabel htmlFor="experiment-running-time-mde">Minimum detectable effect</FieldLabel>
            <div className="flex items-center gap-3">
                <Slider
                    className="flex-[3]"
                    value={value}
                    min={MINIMUM_DETECTABLE_EFFECT_MIN}
                    max={MINIMUM_DETECTABLE_EFFECT_MAX}
                    step={1}
                    onValueChange={(next) => onChange(Array.isArray(next) ? next[0] : next)}
                    aria-label="Minimum detectable effect"
                />
                <span className="flex flex-1 items-center gap-1">
                    <Input
                        id="experiment-running-time-mde"
                        type="number"
                        value={draft ?? ''}
                        min={MINIMUM_DETECTABLE_EFFECT_MIN}
                        max={MINIMUM_DETECTABLE_EFFECT_MAX}
                        step={1}
                        aria-invalid={outOfRange || undefined}
                        onChange={(event) =>
                            setDraftValue(event.target.value === '' ? undefined : Number(event.target.value))
                        }
                        onBlur={commitDraft}
                        onKeyDown={(event) => event.key === 'Enter' && commitDraft()}
                        data-attr="experiment-running-time-mde-input"
                    />
                    <Text size="xs" variant="muted" render={<span />}>
                        %
                    </Text>
                </span>
            </div>
            {outOfRange && <FieldError>{MINIMUM_DETECTABLE_EFFECT_RANGE_ERROR}</FieldError>}
        </Field>
    )
}

function QuillDetectableEffectTable({ experiment: experimentProp }: { experiment: Experiment }): JSX.Element | null {
    const logic = runningTimeLogic({ experiment: experimentProp })
    const {
        outlook,
        currentExposures,
        isComplete,
        dailyExposureRate,
        estimateMetric,
        canIncludeMoreUsers,
        experiment,
    } = useValues(logic)
    const { selectCheckpoint } = useActions(logic)

    const startDate = experiment.start_date
    if (!outlook || currentExposures === null || dailyExposureRate === null || !startDate) {
        return null
    }

    const dateAt = (days: number): dayjs.Dayjs => dayjs(startDate).add(days * 24, 'hour')
    const footnote = detectableEffectFootnote({
        estimateMetric,
        dailyExposureRate,
        isOutOfReach: outlook.isOutOfReach,
        canIncludeMoreUsers,
    })

    const columns: DataTableProps<DetectableEffectCheckpoint, unknown>['columns'] = [
        {
            id: 'when',
            header: 'When',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) => (
                <span className="flex items-center gap-1.5 whitespace-nowrap">
                    {original.isTarget && isComplete && (
                        <IconCheck className="shrink-0 text-success-foreground" aria-label="Target reached" />
                    )}
                    {original.isTarget && outlook.isOutOfReach && (
                        <Tooltip>
                            <TooltipTrigger render={<span className="flex" tabIndex={0} />}>
                                <IconWarning className="shrink-0 text-warning-foreground" />
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">{OUT_OF_REACH_TOOLTIP}</TooltipContent>
                        </Tooltip>
                    )}
                    <span>{original.kind === 'now' ? 'Today' : formatCheckpointDate(dateAt(original.days))}</span>
                    <Text size="xs" variant="muted" render={<span className="font-normal" />}>
                        {`· ${describeCheckpointDay(original, {
                            startDate,
                            currentSampleSize: currentExposures,
                        })}`}
                    </Text>
                </span>
            ),
        },
        {
            id: 'exposures',
            header: 'Exposures',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) => original.exposures.toLocaleString(),
        },
        {
            id: 'detectable',
            header: 'Detectable effect',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) => formatDetectableEffect(original.detectableEffect),
        },
        {
            id: 'set-target',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) => {
                if (original.isTarget) {
                    return <Badge variant="info">Target</Badge>
                }
                const { effect, disabledReason, tooltip } = describeUseButton(original)
                return (
                    <Button
                        size="xs"
                        disabledReason={disabledReason}
                        tooltip={tooltip}
                        onClick={() => selectCheckpoint(original.key, effect)}
                        data-attr="experiment-running-time-set-target"
                    >
                        Use
                    </Button>
                )
            },
        },
    ]

    return (
        <Field data-attr="experiment-running-time-outlook">
            <FieldLabel>What the experiment can detect</FieldLabel>
            <DataTable
                columns={columns}
                data={outlook.checkpoints}
                fullWidth
                size="sm"
                getRowId={(row) => row.key}
                rowClassName={(row) => cn(row.isTarget && 'bg-accent-highlight font-semibold')}
            />
            <FieldDescription>
                Based on <span className="font-semibold">{footnote.metricName}</span>
                {footnote.rest}
            </FieldDescription>
        </Field>
    )
}

export function QuillRunningTimeConfigModal({ experiment: experimentProp }: { experiment: Experiment }): JSX.Element {
    const {
        config,
        manualFormPreview,
        isRunningTimeConfigModalOpen,
        experiment,
        isSaving,
        outlook,
        isCalculating,
        automaticTargetFailed,
        automaticTargetRequest,
    } = useValues(runningTimeLogic({ experiment: experimentProp }))
    const { setConfig, save, cancel, loadAutomaticTarget } = useActions(
        runningTimeLogic({ experiment: experimentProp })
    )

    const isPreLaunch = !isLaunched(experiment)
    const effectField = <QuillMinimumDetectableEffectField value={config.mde} onChange={(mde) => setConfig({ mde })} />

    return (
        <Dialog open={isRunningTimeConfigModalOpen} onOpenChange={(open: boolean) => !open && cancel()}>
            <DialogContent data-attr="experiment-running-time-modal">
                <DialogHeader>
                    <DialogTitle>{isPreLaunch ? 'Estimate running time' : 'Running time'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel>Calculation mode</FieldLabel>
                            <ToggleGroup
                                variant="outline"
                                className="w-full"
                                value={[config.mode]}
                                onValueChange={(next: string[]) =>
                                    next[0] && setConfig({ mode: next[0] as 'automatic' | 'manual' })
                                }
                            >
                                <ToggleGroupItem
                                    value="automatic"
                                    className="flex-1"
                                    disabledReason={isPreLaunch ? AUTOMATIC_MODE_DISABLED_REASON : undefined}
                                >
                                    Automatic
                                </ToggleGroupItem>
                                <ToggleGroupItem value="manual" className="flex-1">
                                    Manual
                                </ToggleGroupItem>
                            </ToggleGroup>
                            {config.mode === 'manual' && <FieldDescription>{MANUAL_MODE_HELP}</FieldDescription>}
                        </Field>

                        {config.mode === 'manual' ? (
                            <>
                                <Field>
                                    <FieldLabel>Metric type</FieldLabel>
                                    <ToggleGroup
                                        variant="outline"
                                        className="w-full"
                                        value={[config.metricType]}
                                        onValueChange={(next: string[]) =>
                                            next[0] &&
                                            setConfig(
                                                metricTypeChange(
                                                    next[0] as ManualCalculatorMetricType,
                                                    config.baselineValue
                                                )
                                            )
                                        }
                                    >
                                        {METRIC_TYPE_OPTIONS.map((option) => (
                                            <ToggleGroupItem key={option.value} value={option.value} className="flex-1">
                                                {option.label}
                                            </ToggleGroupItem>
                                        ))}
                                    </ToggleGroup>
                                </Field>
                                <Field>
                                    <FieldLabel htmlFor="experiment-running-time-baseline">
                                        {getBaselineLabel(config.metricType)}
                                    </FieldLabel>
                                    <span className="flex items-center gap-1">
                                        <Input
                                            id="experiment-running-time-baseline"
                                            type="number"
                                            value={config.baselineValue}
                                            min={0}
                                            max={config.metricType === 'funnel' ? 100 : undefined}
                                            step={config.metricType === 'funnel' ? 0.1 : 1}
                                            onChange={(event) =>
                                                setConfig({
                                                    baselineValue: clampBaseline(
                                                        config.metricType,
                                                        Number(event.target.value)
                                                    ),
                                                })
                                            }
                                        />
                                        {config.metricType === 'funnel' && (
                                            <Text size="xs" variant="muted" render={<span />}>
                                                %
                                            </Text>
                                        )}
                                    </span>
                                    <FieldDescription>{getBaselineHelp(config.metricType)}</FieldDescription>
                                </Field>
                                <div className="flex flex-col gap-1">
                                    {effectField}
                                    <Text size="xs" variant="muted">
                                        {MINIMUM_DETECTABLE_EFFECT_HELP}
                                    </Text>
                                </div>
                                <Field>
                                    <FieldLabel htmlFor="experiment-running-time-exposures">
                                        Expected exposures per day
                                    </FieldLabel>
                                    <Input
                                        id="experiment-running-time-exposures"
                                        type="number"
                                        value={config.exposureRate}
                                        min={0}
                                        step={100}
                                        className="w-32"
                                        onChange={(event) => setConfig({ exposureRate: Number(event.target.value) })}
                                    />
                                    <FieldDescription>{EXPOSURES_PER_DAY_HELP}</FieldDescription>
                                </Field>
                            </>
                        ) : (
                            <>
                                {effectField}
                                {!outlook && isCalculating ? (
                                    <span className="flex items-center gap-2">
                                        <Spinner />
                                        <Text size="xs" variant="muted" render={<span />}>
                                            Calculating the running time…
                                        </Text>
                                    </span>
                                ) : automaticTargetFailed ? (
                                    <Item variant="outline" size="sm" tone="destructive">
                                        <ItemMedia variant="icon" aria-hidden>
                                            <IconWarning />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemDescription className="line-clamp-none">
                                                Couldn't calculate the running time.
                                            </ItemDescription>
                                        </ItemContent>
                                        {automaticTargetRequest && (
                                            <ItemActions>
                                                <Button
                                                    variant="outline"
                                                    onClick={() => loadAutomaticTarget(automaticTargetRequest)}
                                                >
                                                    Try again
                                                </Button>
                                            </ItemActions>
                                        )}
                                    </Item>
                                ) : !outlook ? (
                                    <Item variant="outline" size="sm" tone="info">
                                        <ItemContent>
                                            <ItemDescription className="line-clamp-none">
                                                {NOT_ENOUGH_DATA_NOTE}
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                ) : (
                                    <QuillDetectableEffectTable experiment={experimentProp} />
                                )}
                                <Text size="xs" variant="muted">
                                    {MINIMUM_DETECTABLE_EFFECT_HELP}
                                </Text>
                            </>
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter className="flex-col items-stretch gap-3 sm:flex-col">
                    {config.mode === 'manual' && (
                        <div className="grid grid-cols-2 gap-4">
                            <span className="flex flex-col">
                                <Text size="xs" variant="muted" render={<span />}>
                                    Recommended sample size
                                </Text>
                                <Text size="sm" weight="semibold" render={<span />}>
                                    {manualFormPreview.sampleSize ? manualFormPreview.sampleSize.toLocaleString() : '—'}
                                </Text>
                            </span>
                            <span className="flex flex-col">
                                <Text size="xs" variant="muted" render={<span />}>
                                    Estimated running time
                                </Text>
                                <Text size="sm" weight="semibold" render={<span />}>
                                    {formatRunningTime(manualFormPreview.runningTime)}
                                </Text>
                            </span>
                        </div>
                    )}
                    <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={cancel} disabledReason={isSaving ? 'Saving…' : undefined}>
                            Cancel
                        </Button>
                        <Button variant="primary" onClick={save} loading={isSaving}>
                            Save
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
