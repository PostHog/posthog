import type { GithubIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to a GitHub issue payload. */
export function isGithubIssueExtra(value: unknown): value is Record<string, unknown> & GithubIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'html_url' in extra && 'number' in extra
}

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

export const githubIssueSignalCardEntry: SignalCardEntry = {
    key: 'github',
    matches: (signal) => signal.source_product === 'github' && isGithubIssueExtra(signal.extra),
    Component: GithubIssueSignalCard,
}
