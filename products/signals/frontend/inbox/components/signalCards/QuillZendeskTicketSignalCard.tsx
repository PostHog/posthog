import type { ZendeskTicketSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { QuillExternalSignalCard } from './QuillExternalSignalCard'
import { cleanZendeskUrl } from './signalCardParsing'
import type { SignalCardProps } from './types'

export function QuillZendeskTicketSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & ZendeskTicketSignalExtraApi

    return (
        <QuillExternalSignalCard signal={signal} link={{ to: cleanZendeskUrl(extra.url), label: 'Open in Zendesk' }}>
            {signal.content}
        </QuillExternalSignalCard>
    )
}
