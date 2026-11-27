import { ReactNode } from 'react'

import type { RecommendationCpaSummary } from './RecommendationCpa'

export function RecommendationCpaValues({
    summary,
    info,
}: {
    summary: RecommendationCpaSummary
    info: ReactNode
}): JSX.Element {
    return (
        <>
            {summary.cpa !== null && (
                <span className="tabular-nums" translate="no">
                    {summary.cpa}
                </span>
            )}
            <span className="inline-flex items-center gap-1">
                <span>
                    <span className="tabular-nums" translate="no">
                        {summary.benchmark}
                    </span>
                    <span>{summary.source}</span>
                </span>
                {info}
            </span>
        </>
    )
}
