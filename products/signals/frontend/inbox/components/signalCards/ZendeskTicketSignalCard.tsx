import type { ZendeskTicketSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import { cleanZendeskUrl } from './signalCardParsing'
import type { SignalCardProps } from './types'

export function ZendeskTicketSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & ZendeskTicketSignalExtraApi

    return (
        <ExternalSignalCard signal={signal} link={{ to: cleanZendeskUrl(extra.url), label: 'Open in Zendesk' }}>
            {signal.content}
        </ExternalSignalCard>
    )
}
