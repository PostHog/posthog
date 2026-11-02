import { LemonButton } from '@posthog/lemon-ui'

import type { _LogsNaturalLanguageCandidateApi } from 'products/logs/frontend/generated/api.schemas'

export const LogsNaturalLanguageCandidates = ({
    candidates,
    onApply,
}: {
    candidates: _LogsNaturalLanguageCandidateApi[]
    onApply: (candidate: _LogsNaturalLanguageCandidateApi, rank: number) => void
}): JSX.Element => {
    return (
        <div className="flex flex-col gap-1">
            <div className="text-xs text-secondary px-2">Pick the closest match</div>
            {candidates.map((candidate, rank) => (
                <LemonButton
                    key={rank}
                    fullWidth
                    size="small"
                    onClick={() => onApply(candidate, rank)}
                    data-attr="logs-natural-language-candidate"
                    sideIcon={
                        candidate.probability !== null ? (
                            <span className="text-xs text-secondary tabular-nums">
                                {Math.round(candidate.probability * 100)}%
                            </span>
                        ) : undefined
                    }
                >
                    <span className="truncate">{candidate.label}</span>
                </LemonButton>
            ))}
        </div>
    )
}
