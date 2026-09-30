import type { TrialVerdictCounts } from './scoutTrialPresentation'

export function ScoutTrialVerdictSummary({ counts }: { counts: TrialVerdictCounts }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm font-normal">
            <span>{`${counts.passed} passed`}</span>
            <span className={counts.failed > 0 ? 'text-danger' : undefined}>{`${counts.failed} failed`}</span>
            {counts.unknown > 0 && <span className="text-warning">{`${counts.unknown} not enough evidence`}</span>}
            {counts.not_applicable > 0 && (
                <span className="text-muted">{`${counts.not_applicable} not applicable`}</span>
            )}
        </div>
    )
}
