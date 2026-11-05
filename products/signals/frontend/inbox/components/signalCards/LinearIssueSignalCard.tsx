import type { LinearIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import { linearIssueTitle } from './signalCardParsing'
import type { SignalCardProps } from './types'

export function LinearIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & LinearIssueSignalExtraApi

    const title = linearIssueTitle(extra)

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
