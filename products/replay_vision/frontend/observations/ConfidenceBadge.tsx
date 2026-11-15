import { LemonTag } from '@posthog/lemon-ui'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { confidenceLevel, readConfidence } from '../utils/observation'

/** The model's confidence in an observation's result, as a colored tag. */
export function ConfidenceBadge({ observation }: { observation: ReplayObservationApi }): JSX.Element | null {
    const confidence = readConfidence(observation)
    if (confidence === null) {
        return null
    }
    const { type, label } = confidenceLevel(confidence)
    return (
        <LemonTag type={type} size="small" data-attr="vision-observation-confidence">
            {`${label} confidence · ${Math.round(confidence * 100)}%`}
        </LemonTag>
    )
}
