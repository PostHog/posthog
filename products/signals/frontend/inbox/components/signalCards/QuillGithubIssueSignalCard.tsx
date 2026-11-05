import type { GithubIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { QuillExternalSignalCard } from './QuillExternalSignalCard'
import type { SignalCardProps } from './types'

export function QuillGithubIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & GithubIssueSignalExtraApi

    return (
        <QuillExternalSignalCard
            signal={signal}
            title={`#${extra.number}`}
            link={{ to: extra.html_url, label: 'View on GitHub' }}
        >
            {signal.content}
        </QuillExternalSignalCard>
    )
}
