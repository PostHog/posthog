import { Badge } from '@posthog/quill'

import { compactNumber, humanFriendlyNumber } from 'lib/utils/numbers'

export function QuillRecommendationCountBadge({
    count,
    maxDigits,
    showZero = false,
}: {
    count: number
    maxDigits: number
    showZero?: boolean
}): JSX.Element | null {
    if (count === 0 && !showZero) {
        return null
    }
    return (
        <Badge title={humanFriendlyNumber(count)} translate="no">
            {count < Math.pow(10, maxDigits) ? compactNumber(count) : `${'9'.repeat(maxDigits)}+`}
        </Badge>
    )
}
