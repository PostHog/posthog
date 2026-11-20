import { BindLogic, useActions, useValues } from 'kea'
import type { ComponentProps } from 'react'

import type { LemonTagType } from '@posthog/lemon-ui'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Skeleton,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { AlertEvaluationHistoryChart } from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'
import {
    LogsAlertConfigurationApi,
    LogsAlertEventApi,
    LogsAlertEventKindEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { describeEvent, getHistoryPoints, getHistoryThresholds } from './logsAlertEventDescriptions'
import { LogsAlertEventHistoryLogicProps, logsAlertEventHistoryLogic } from './logsAlertEventHistoryLogic'

const BADGE_VARIANT_BY_TAG_TYPE: Partial<Record<LemonTagType, ComponentProps<typeof Badge>['variant']>> = {
    success: 'success',
    danger: 'destructive',
    warning: 'warning',
    caution: 'warning',
    info: 'info',
    primary: 'info',
    highlight: 'info',
    completion: 'completed',
}

export function QuillLogsAlertEventHistory({ alert }: { alert: LogsAlertConfigurationApi }): JSX.Element {
    const logicProps: LogsAlertEventHistoryLogicProps = { alertId: alert.id }

    return (
        <BindLogic logic={logsAlertEventHistoryLogic} props={logicProps}>
            <QuillLogsAlertEventTimeline alert={alert} />
        </BindLogic>
    )
}

function QuillLogsAlertEventTimeline({ alert }: { alert: LogsAlertConfigurationApi }): JSX.Element {
    const { eventsPage, eventsPageLoading } = useValues(logsAlertEventHistoryLogic)
    const { loadMore } = useActions(logsAlertEventHistoryLogic)
    const historyPoints = getHistoryPoints(eventsPage.results)
    const hasMore = eventsPage.next !== null
    const shownOf =
        eventsPage.count > eventsPage.results.length
            ? ` · Showing ${eventsPage.results.length} of ${eventsPage.count}`
            : ''

    return (
        <div className="flex flex-col gap-4">
            {historyPoints.length > 0 ? (
                <AlertEvaluationHistoryChart
                    points={historyPoints}
                    valueLabel="Matching logs"
                    thresholds={getHistoryThresholds(alert)}
                    historyLimit={Math.max(historyPoints.length, 1)}
                    evaluationNoun="evaluation"
                />
            ) : null}
            {eventsPageLoading && eventsPage.results.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                </div>
            ) : eventsPage.results.length === 0 ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>
                            No events yet. Evaluations, transitions, and user actions will appear here.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <div className="flex max-h-96 flex-col gap-1 overflow-y-auto scroll-mask-y-4 scroll-py-4">
                    {eventsPage.results.map((event) => (
                        <QuillLogsAlertEventRow key={event.id} event={event} />
                    ))}
                </div>
            )}
            {hasMore ? (
                <div className="flex justify-center">
                    <Button variant="outline" onClick={loadMore} loading={eventsPageLoading}>
                        <span>Load more</span>
                        {shownOf ? <span translate="no">{shownOf}</span> : null}
                    </Button>
                </div>
            ) : null}
        </div>
    )
}

function QuillLogsAlertEventRow({ event }: { event: LogsAlertEventApi }): JSX.Element {
    const { label, type, detail } = describeEvent(event)

    return (
        <Collapsible className="rounded-md border border-border p-2">
            <CollapsibleHeader className="flex-wrap">
                <CollapsibleTrigger iconOnly>{`Show details for ${label}`}</CollapsibleTrigger>
                <Badge variant={BADGE_VARIANT_BY_TAG_TYPE[type] ?? 'default'}>{label}</Badge>
                <Text size="xs" render={<span />}>
                    <TZLabel time={event.created_at} formatDate="MMM D" formatTime="HH:mm:ss" />
                </Text>
                {detail ? (
                    <Text size="xs" variant="muted" render={<span className="min-w-0 truncate" translate="no" />}>
                        {detail}
                    </Text>
                ) : null}
            </CollapsibleHeader>
            <CollapsibleContent>
                <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-2 pt-2 text-xs" translate="no">
                    <dt className="text-muted-foreground">Kind</dt>
                    <dd className="m-0 font-mono">{event.kind}</dd>
                    <dt className="text-muted-foreground">State</dt>
                    <dd className="m-0 font-mono">
                        {event.state_before} → {event.state_after}
                    </dd>
                    {event.kind === LogsAlertEventKindEnumApi.Check ? (
                        <>
                            <dt className="text-muted-foreground">Breached</dt>
                            <dd className="m-0 font-mono">{event.threshold_breached ? 'yes' : 'no'}</dd>
                        </>
                    ) : null}
                    {event.result_count !== null ? (
                        <>
                            <dt className="text-muted-foreground">Result count</dt>
                            <dd className="m-0 font-mono">{event.result_count}</dd>
                        </>
                    ) : null}
                    {event.query_duration_ms !== null ? (
                        <>
                            <dt className="text-muted-foreground">Query duration</dt>
                            <dd className="m-0 font-mono">{event.query_duration_ms} ms</dd>
                        </>
                    ) : null}
                    {event.error_message ? (
                        <>
                            <dt className="text-muted-foreground">Error</dt>
                            <dd className="m-0 font-mono break-words whitespace-pre-wrap">{event.error_message}</dd>
                        </>
                    ) : null}
                    <dt className="text-muted-foreground">Timestamp</dt>
                    <dd className="m-0 font-mono">
                        <TZLabel time={event.created_at} />
                    </dd>
                </dl>
            </CollapsibleContent>
        </Collapsible>
    )
}
