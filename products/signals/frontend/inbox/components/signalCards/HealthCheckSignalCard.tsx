import { Fragment } from 'react'

import { Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { HealthCheckSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { HealthCheckPayloadView, healthCheckBodyText, healthCheckPayloadView } from './signalCardParsing'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardProps } from './types'

/** A version or migration transition line, host chips, or a key-value list, as picked by `healthCheckPayloadView`. */
function HealthCheckPayload({ view }: { view: HealthCheckPayloadView }): JSX.Element | null {
    if (view.type === 'transition') {
        return (
            <div className="text-xs text-secondary">
                <span className="font-mono">{view.from}</span>
                <span className="text-tertiary"> → </span>
                <span className="font-mono">{view.to}</span>
            </div>
        )
    }
    if (view.type === 'hosts') {
        return (
            <div className="flex flex-wrap gap-1">
                {view.hosts.map((host) => (
                    <code key={host} className="text-xs px-1 py-0.5 rounded bg-surface-secondary font-mono">
                        {host}
                    </code>
                ))}
            </div>
        )
    }
    if (view.rows.length === 0) {
        return null
    }
    return (
        <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
            {view.rows.map(({ key, label, value }) => (
                <Fragment key={key}>
                    <span className="text-tertiary">{label}</span>
                    <span className="text-secondary">{value}</span>
                </Fragment>
            ))}
        </div>
    )
}

export function HealthCheckSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & HealthCheckSignalExtraApi

    const markdownText = healthCheckBodyText(signal, extra)

    return (
        <SignalCardShell signal={signal} label={extra.title}>
            <div className="flex flex-col gap-2">
                {markdownText && (
                    <LemonMarkdown className="text-sm text-secondary" disableImages>
                        {markdownText}
                    </LemonMarkdown>
                )}

                <HealthCheckPayload view={healthCheckPayloadView(extra.kind, extra.payload)} />

                <div className="flex items-center gap-2 pt-1">
                    <span className="flex-1" />
                    <Link to={extra.link} className="text-xs font-medium">
                        Open in PostHog
                    </Link>
                </div>
            </div>
        </SignalCardShell>
    )
}
