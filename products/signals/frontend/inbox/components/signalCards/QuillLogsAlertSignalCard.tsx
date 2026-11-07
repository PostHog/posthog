import { Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import type { LogsAlertStateChangeSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { isLogsAlertStateChangeExtra } from './signalCardMatchers'
import { logsAlertFilterSummary } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Compact rendering of the alert's log filters: services, severities, and a count of remaining conditions. */
function QuillFiltersBlock({ filters }: { filters: Record<string, unknown> }): JSX.Element {
    const { serviceNames, severityLevels, filterGroupCount } = logsAlertFilterSummary(filters)

    if (serviceNames.length === 0 && severityLevels.length === 0 && filterGroupCount === 0) {
        return (
            <Text size="xs" variant="muted" className="m-0">
                All logs
            </Text>
        )
    }

    return (
        <div className="flex flex-col gap-0.5">
            {serviceNames.length > 0 && (
                <Text size="xs" className="m-0 break-words">
                    <span className="text-muted-foreground">Services </span>
                    <span className="font-mono">{serviceNames.join(', ')}</span>
                </Text>
            )}
            {severityLevels.length > 0 && (
                <Text size="xs" className="m-0 break-words">
                    <span className="text-muted-foreground">Severities </span>
                    <span className="font-mono">{severityLevels.join(', ')}</span>
                </Text>
            )}
            {filterGroupCount > 0 && (
                <Text size="xs" variant="muted" className="m-0">
                    + {filterGroupCount} filter {filterGroupCount === 1 ? 'condition' : 'conditions'}
                </Text>
            )}
        </div>
    )
}

/** Firing body: threshold sentence plus a compact observed / threshold pair. */
function QuillFiringBody({ extra }: { extra: LogsAlertStateChangeSignalExtraApi }): JSX.Element {
    const observed = extra.result_count === null ? 'No result' : extra.result_count

    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" className="m-0">
                Result count {observed} is {extra.threshold_operator} threshold {extra.threshold_count} over the last{' '}
                {extra.window_minutes} minutes
            </Text>
            <div className="flex flex-wrap items-baseline gap-x-2">
                <Text size="lg" weight="semibold" render={<span />}>
                    <span className="text-destructive-foreground">
                        {extra.result_count === null ? 'N/A' : extra.result_count}
                    </span>
                    {' / '}
                    {extra.threshold_count}
                </Text>
                <Text size="xs" variant="muted" render={<span />}>
                    observed / threshold
                </Text>
            </div>
        </div>
    )
}

/** Broken body: auto-disable sentence plus a muted line describing what was being checked. */
function QuillBrokenBody({ extra }: { extra: LogsAlertStateChangeSignalExtraApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Text size="xs" className="m-0">
                Alert auto-disabled after{' '}
                <span className="font-semibold text-warning-foreground">{extra.consecutive_failures}</span> consecutive
                failed checks
            </Text>
            <Text size="xs" variant="muted" className="m-0">
                Was checking result count {extra.threshold_operator} {extra.threshold_count} over {extra.window_minutes}
                m
            </Text>
        </div>
    )
}

/** Quill sibling of `LogsAlertSignalCard` (firing / broken). */
export function QuillLogsAlertSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!isLogsAlertStateChangeExtra(signal.extra)) {
        return <QuillSignalCardShell signal={signal}>{null}</QuillSignalCardShell>
    }
    const extra = signal.extra

    return (
        <QuillSignalCardShell signal={signal} label={extra.alert_name}>
            {extra.action === 'firing' ? <QuillFiringBody extra={extra} /> : <QuillBrokenBody extra={extra} />}

            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            <QuillFiltersBlock filters={extra.filters} />

            <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                <QuillSignalCardLink to={urls.logsAlertDetail(extra.alert_id)}>View alert</QuillSignalCardLink>
            </div>
        </QuillSignalCardShell>
    )
}
