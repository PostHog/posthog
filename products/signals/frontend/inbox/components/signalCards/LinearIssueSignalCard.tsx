import type { LinearIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import type { SignalCardEntry, SignalCardProps } from './types'

/**
 * Linear has `url` + `priority` + `number`, but unlike GitHub it carries no `html_url`.
 * Requiring `identifier` and `priority_label` keeps this narrow enough not to match other issue sources.
 */
export function isLinearIssueExtra(value: unknown): value is Record<string, unknown> & LinearIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'identifier' in extra && 'priority_label' in extra && typeof extra.url === 'string'
}

export function LinearIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & LinearIssueSignalExtraApi

    const title = extra.identifier || `#${extra.number}`

    return (
        <ExternalSignalCard
            signal={signal}
            title={<span className="font-mono">{title}</span>}
            link={{ to: extra.url, label: 'View in Linear' }}
        >
            {signal.content}
        </ExternalSignalCard>
    )
}

export const linearIssueSignalCardEntry: SignalCardEntry = {
    key: 'linear',
    matches: (signal) => signal.source_product === 'linear' && isLinearIssueExtra(signal.extra),
    Component: LinearIssueSignalCard,
}
