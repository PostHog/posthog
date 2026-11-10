import { LemonTag } from '@posthog/lemon-ui'

import type { ReviewTriggerReviewModeEnumApi } from './generated/api.schemas'
import { REVIEW_MODE_LABEL } from './reviewDisplay'

export function ReviewModeTag({ mode }: { mode: ReviewTriggerReviewModeEnumApi | null }): JSX.Element | null {
    if (!mode) {
        return null
    }
    return (
        <LemonTag type="muted" size="small">
            {REVIEW_MODE_LABEL[mode]}
        </LemonTag>
    )
}
