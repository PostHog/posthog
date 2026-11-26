import { Badge } from '@posthog/quill'

import { compactNumber, humanFriendlyNumber } from 'lib/utils/numbers'

export function QuillRecommendationCountBadge({
    count,
    maxDigits,
    showZero = false,
    variant = 'default',
}: {
    count: number
    maxDigits: number
    showZero?: boolean
    variant?: 'default' | 'info'
}): JSX.Element | null {
    if (count === 0 && !showZero) {
        return null
    }
    return (
        <Badge variant={variant} title={humanFriendlyNumber(count)} translate="no">
            {count < Math.pow(10, maxDigits) ? compactNumber(count) : `${'9'.repeat(maxDigits)}+`}
        </Badge>
    )
}
