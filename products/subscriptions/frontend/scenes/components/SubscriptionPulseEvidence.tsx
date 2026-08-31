import { LemonButton } from '@posthog/lemon-ui'

import type { RunActionHistoryDTOApi } from 'products/subscriptions/frontend/generated/api.schemas'

function sourceUrl(value: string): string | null {
    try {
        const url = new URL(value)
        return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password ? value : null
    } catch {
        return null
    }
}

export function SubscriptionPulseEvidence({ action }: { action: RunActionHistoryDTOApi }): JSX.Element | null {
    if (action.evidence.length === 0 && action.citations.length === 0) {
        return null
    }
    const citations = action.citations
        .flatMap((citation) => {
            const safeUrl = sourceUrl(citation.canonical_url)
            return safeUrl ? [{ citation, safeUrl }] : []
        })
        .slice(0, 3)
    const unavailable = action.evidence.some((item) => item.error_class !== null)
    const truncated = action.evidence.some((item) => item.result_truncated)
    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-primary">{action.title}</span>
            {action.evidence.length > 0 ? (
                <span>
                    Evidence reviewed: {action.evidence.length} source{action.evidence.length === 1 ? '' : 's'}.
                </span>
            ) : null}
            {truncated ? <span>Some evidence was shortened.</span> : null}
            {unavailable ? <span>Some evidence was unavailable.</span> : null}
            {citations.map(({ citation, safeUrl }, index) => (
                <LemonButton key={citation.evidence_id} type="tertiary" size="xsmall" to={safeUrl} targetBlank>
                    {citation.title ?? `Source ${index + 1}`}
                </LemonButton>
            ))}
        </div>
    )
}
