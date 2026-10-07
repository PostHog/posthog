import { Tooltip } from '@posthog/lemon-ui'

import type { WarehouseSuggestionApiEvidence } from '../generated/api.schemas'
import { surfaceBreakdown } from '../suggestionCopy'

export interface WhyThisSuggestionProps {
    evidence: WarehouseSuggestionApiEvidence
    windowDays: number
}

export function WhyThisSuggestion({ evidence, windowDays }: WhyThisSuggestionProps): JSX.Element {
    const breakdown = surfaceBreakdown(evidence)
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    {breakdown && <span>Reads by surface: {breakdown}</span>}
                    <span>{Number(evidence.human_users ?? 0)} people. Names are never shown.</span>
                    <span>
                        Read on {Number(evidence.human_days ?? 0)} of the last {windowDays} days.
                    </span>
                    <span>Counts come from the query log. Cached dashboard views are not counted.</span>
                </div>
            }
        >
            <span
                tabIndex={0}
                className="cursor-help text-xs text-secondary underline decoration-dotted"
                data-attr="warehouse-suggestions-why-this"
            >
                Why this?
            </span>
        </Tooltip>
    )
}
