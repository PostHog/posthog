import type { LinearIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { QuillExternalSignalCard } from './QuillExternalSignalCard'
import { linearIssueTitle } from './signalCardParsing'
import type { SignalCardProps } from './types'

export function QuillLinearIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & LinearIssueSignalExtraApi

    return (
        <QuillExternalSignalCard
            signal={signal}
            title={<span className="font-mono">{linearIssueTitle(extra)}</span>}
            link={{ to: extra.url, label: 'View in Linear' }}
        >
            {signal.content}
        </QuillExternalSignalCard>
    )
}
