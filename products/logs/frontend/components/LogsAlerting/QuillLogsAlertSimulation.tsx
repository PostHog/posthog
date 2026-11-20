import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Card,
    CardContent,
    Heading,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { LogsAlertSimulateResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertFormLogic } from './logsAlertFormLogic'
import { LogsAlertSimulationChart } from './LogsAlertSimulationChart'
import { extractIncidents, Incident, SIMULATION_RANGE_OPTIONS } from './logsAlertSimulationIncidents'

function QuillHelpLabel({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="cursor-help" />}>{label}</TooltipTrigger>
            <TooltipContent className="max-w-80">{help}</TooltipContent>
        </Tooltip>
    )
}

function QuillSimulationStat({
    label,
    help,
    value,
    highlight = false,
}: {
    label: string
    help: string
    value: string | number
    highlight?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col">
            <Text size="xs" variant="muted" render={<span />}>
                <QuillHelpLabel label={label} help={help} />
            </Text>
            <Text
                size="lg"
                weight="semibold"
                variant={highlight ? 'destructive' : 'default'}
                render={<span translate="no" />}
            >
                {value}
            </Text>
        </div>
    )
}

function QuillSimulationIncidents({ incidents, threshold }: { incidents: Incident[]; threshold: number }): JSX.Element {
    return (
        <div className="max-h-70 overflow-y-auto rounded-md border border-border">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>
                            <QuillHelpLabel
                                label="Started"
                                help="When the alert first breached the threshold and sent a notification"
                            />
                        </TableHead>
                        <TableHead>
                            <QuillHelpLabel label="Duration" help="How long the alert remained in a firing state" />
                        </TableHead>
                        <TableHead>
                            <QuillHelpLabel
                                label="Peak / threshold"
                                help="Highest rolling window count during this alert vs your configured threshold"
                            />
                        </TableHead>
                        <TableHead>
                            <QuillHelpLabel
                                label="Outcome"
                                help="Whether the alert resolved or is still active at the end of the simulation window"
                            />
                        </TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {incidents.map((incident, i) => {
                        const peakRatio = incident.peakCount / threshold

                        return (
                            <TableRow key={i}>
                                <TableCell className="font-medium">
                                    <TZLabel time={incident.firedAt} timestampStyle="absolute" />
                                </TableCell>
                                <TableCell>
                                    <span translate="no">{humanFriendlyDuration(incident.durationMinutes * 60)}</span>
                                </TableCell>
                                <TableCell translate="no">
                                    <span
                                        className={cn(
                                            peakRatio >= 2 ? 'text-destructive-foreground' : 'text-warning-foreground',
                                            peakRatio >= 5 && 'font-semibold'
                                        )}
                                    >
                                        {incident.peakCount.toLocaleString()}
                                    </span>
                                    <span className="text-muted-foreground"> / {threshold.toLocaleString()}</span>
                                </TableCell>
                                <TableCell>
                                    {incident.stillFiring ? (
                                        <Badge variant="destructive">Still firing</Badge>
                                    ) : (
                                        <span className="text-muted-foreground">
                                            Resolved at{' '}
                                            <TZLabel time={incident.resolvedAt!} timestampStyle="absolute" />
                                        </span>
                                    )}
                                </TableCell>
                            </TableRow>
                        )
                    })}
                </TableBody>
            </Table>
        </div>
    )
}

function QuillSimulationResults({ result }: { result: LogsAlertSimulateResponseApi }): JSX.Element {
    const incidents = extractIncidents(result.buckets)
    const op = result.threshold_operator === 'above' ? '>' : '<'
    const totalFiringSeconds = incidents.reduce((sum, inc) => sum + inc.durationMinutes * 60, 0)

    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Simulated with current form settings: {op} {result.threshold_count} logs in window. Edit the form and
                re-run to compare.
            </Text>
            <LogsAlertSimulationChart result={result} />
            <div className="flex flex-wrap gap-6">
                <QuillSimulationStat
                    label="Alerts"
                    help="Number of times this alert would have fired and sent a notification"
                    value={result.fire_count}
                    highlight={result.fire_count > 0}
                />
                <QuillSimulationStat
                    label="Total firing time"
                    help="Total time the alert would have been in a firing state"
                    value={totalFiringSeconds > 0 ? humanFriendlyDuration(totalFiringSeconds) : '0m'}
                />
                <QuillSimulationStat
                    label="Resolutions"
                    help="Number of times the alert resolved after firing"
                    value={result.resolve_count}
                />
            </div>
            {incidents.length > 0 ? (
                <QuillSimulationIncidents incidents={incidents} threshold={result.threshold_count} />
            ) : null}
        </div>
    )
}

export function QuillLogsAlertSimulation({ embedded = false }: { embedded?: boolean }): JSX.Element {
    const { simulationResult, simulationResultLoading, simulationDateFrom, simulationDisabledReason } =
        useValues(logsAlertFormLogic)
    const { simulateAlert, setSimulationDateFrom } = useActions(logsAlertFormLogic)

    const simulation = (
        <div className="flex flex-col gap-4">
            {embedded ? (
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h4 className="m-0" />}>
                        Preview
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Check how this alert would behave on historical data.
                    </Text>
                </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
                <Select
                    items={SIMULATION_RANGE_OPTIONS}
                    value={simulationDateFrom}
                    onValueChange={(value) => {
                        if (value) {
                            setSimulationDateFrom(value)
                        }
                    }}
                >
                    <SelectTrigger aria-label="Simulation range">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {SIMULATION_RANGE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Button
                    variant="primary"
                    onClick={simulateAlert}
                    loading={simulationResultLoading}
                    disabledReason={simulationDisabledReason}
                >
                    Run simulation
                </Button>
            </div>

            {simulationResultLoading && !simulationResult && (
                <div className="flex flex-col gap-3">
                    <Skeleton className="h-56" />
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                </div>
            )}

            {simulationResult && <QuillSimulationResults result={simulationResult} />}

            {!simulationResult && !simulationResultLoading && (
                <div className="flex h-56 flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border p-4 text-center">
                    <Text size="sm" weight="medium" render={<span />}>
                        {simulationDisabledReason ?? 'Select a time range, then run a simulation'}
                    </Text>
                    {simulationDisabledReason ? null : (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Historical log counts and alert outcomes will appear here.
                        </Text>
                    )}
                </div>
            )}
        </div>
    )

    if (embedded) {
        return (
            <Card size="sm">
                <CardContent>{simulation}</CardContent>
            </Card>
        )
    }

    return <div className="p-4">{simulation}</div>
}
