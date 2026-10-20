import { useActions } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { insightDataChecksLogic } from './insightDataChecksLogic'

export function FixWithPostHogAIButton({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const { fixWithPostHogAI } = useActions(insightDataChecksLogic(insightProps))
    return (
        <Button
            variant="outline"
            size="sm"
            onClick={() => fixWithPostHogAI(check)}
            data-attr="insight-data-check-fix-with-ai"
        >
            <IconSparkles />
            {check.key === 'duplicate_events' ? 'Investigate with PostHog AI' : 'Fix with PostHog AI'}
        </Button>
    )
}
