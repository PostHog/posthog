import { Tooltip } from '@posthog/lemon-ui'

import type { WarehouseSuggestionEvidenceApi } from '../generated/api.schemas'
import { QUERY_LOG_CAVEAT, daysReadLabel, surfaceSegments } from '../suggestionCopy'
import { ReadsBySurfaceBar } from './ReadsBySurfaceBar'

export interface WhyThisSuggestionProps {
    evidence: WarehouseSuggestionEvidenceApi
    windowDays: number
    label: string
}

export function WhyThisSuggestion({ evidence, windowDays, label }: WhyThisSuggestionProps): JSX.Element {
    const segments = surfaceSegments(evidence)
    const daysRead = (evidence.human_days ?? 0) > 0 ? daysReadLabel(evidence, windowDays) : null

    return (
        <Tooltip
            title={
                <div className="flex w-64 max-w-full flex-col gap-2 py-0.5">
                    {segments.length > 0 && <ReadsBySurfaceBar segments={segments} />}
                    {daysRead && <span>{daysRead}</span>}
                    <span className="opacity-75">{QUERY_LOG_CAVEAT}</span>
                </div>
            }
        >
            <span
                tabIndex={0}
                className="cursor-help underline decoration-dotted underline-offset-2"
                data-attr="warehouse-suggestions-why-this"
            >
                <span translate="no">{label}</span>
                <span className="sr-only">
                    {[
                        segments.map((segment) => `${segment.label} ${segment.count}`).join(', '),
                        daysRead,
                        QUERY_LOG_CAVEAT,
                    ]
                        .filter(Boolean)
                        .map((part) => `. ${part}`)
                        .join('')}
                </span>
            </span>
        </Tooltip>
    )
}
