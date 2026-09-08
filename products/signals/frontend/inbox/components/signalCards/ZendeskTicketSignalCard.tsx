import type { ZendeskTicketSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Guard for Zendesk ticket extras. Keys on `status` + `tags` so it doesn't collide with Linear, which also carries `url` + `priority`. */
export function isZendeskTicketExtra(value: unknown): value is Record<string, unknown> & ZendeskTicketSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.url === 'string' && 'status' in extra && 'tags' in extra
}

/** Strip Zendesk API artifacts so a raw API URL resolves to the user-facing ticket URL. */
function cleanZendeskUrl(url: string): string {
    return url.replace('/api/v2', '').replace('.json', '')
}

export function ZendeskTicketSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & ZendeskTicketSignalExtraApi

    return (
        <ExternalSignalCard signal={signal} link={{ to: cleanZendeskUrl(extra.url), label: 'Open in Zendesk' }}>
            {signal.content}
        </ExternalSignalCard>
    )
}

export const zendeskTicketSignalCardEntry: SignalCardEntry = {
    key: 'zendesk',
    matches: (signal) => signal.source_product === 'zendesk' && isZendeskTicketExtra(signal.extra),
    Component: ZendeskTicketSignalCard,
}
