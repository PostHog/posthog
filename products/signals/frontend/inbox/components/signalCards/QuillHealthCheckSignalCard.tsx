import { Badge, Text } from '@posthog/quill'

import type { HealthCheckSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { HealthCheckPayloadView, healthCheckBodyText, healthCheckPayloadView } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** A version or migration transition line, host badges, or a key-value list, as picked by `healthCheckPayloadView`. */
function QuillHealthCheckPayload({ view }: { view: HealthCheckPayloadView }): JSX.Element | null {
    if (view.type === 'transition') {
        return (
            <Text size="xs" variant="muted" className="m-0 break-words">
                <span className="font-mono">{view.from}</span>
                <span className="text-subtle-foreground"> → </span>
                <span className="font-mono">{view.to}</span>
            </Text>
        )
    }
    if (view.type === 'hosts') {
        return (
            <div className="flex min-w-0 flex-wrap gap-1">
                {view.hosts.map((host) => (
                    <Badge key={host} className="max-w-full font-mono">
                        <span className="truncate">{host}</span>
                    </Badge>
                ))}
            </div>
        )
    }
    if (view.rows.length === 0) {
        return null
    }
    return (
        <dl className="m-0 flex flex-col gap-0.5">
            {view.rows.map(({ key, label, value }) => (
                <Text key={key} size="xs" render={<div />} className="flex min-w-0 gap-2">
                    <dt className="w-1/3 shrink-0 break-words text-muted-foreground">{label}</dt>
                    <dd className="m-0 min-w-0 flex-1 break-words">{value}</dd>
                </Text>
            ))}
        </dl>
    )
}

export function QuillHealthCheckSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & HealthCheckSignalExtraApi

    const markdownText = healthCheckBodyText(signal, extra)

    return (
        <QuillSignalCardShell signal={signal} label={extra.title}>
            {markdownText && <QuillSignalCardMarkdown>{markdownText}</QuillSignalCardMarkdown>}

            <QuillHealthCheckPayload view={healthCheckPayloadView(extra.kind, extra.payload)} />

            <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                <QuillSignalCardLink to={extra.link}>Open in PostHog</QuillSignalCardLink>
            </div>
        </QuillSignalCardShell>
    )
}
