import type { GithubIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import type { SignalCardProps } from './types'

export function GithubIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & GithubIssueSignalExtraApi

    return (
        <ExternalSignalCard
            signal={signal}
            title={<span className="font-medium">#{extra.number}</span>}
            link={{ to: extra.html_url, label: 'View on GitHub' }}
        >
            {signal.content}
        </ExternalSignalCard>
    )
}
