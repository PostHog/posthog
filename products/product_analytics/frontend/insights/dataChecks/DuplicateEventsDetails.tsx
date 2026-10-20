import { useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { repeatedEventsTextOf } from './dataCheckText'
import { FixWithPostHogAIButton } from './FixWithPostHogAIButton'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import { repeatedEventsQueryOf } from './repeatedEventsQuery'

const MAX_CHECKED_DAYS = 7

export function DuplicateEventsDetails({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const { lastResult } = useValues(insightDataChecksLogic(insightProps))
    const days = lastResult?.coverage?.days_checked || MAX_CHECKED_DAYS
    const text = repeatedEventsTextOf(check)
    return (
        <div className="flex flex-col items-start gap-1.5">
            <Text size="xs" variant="muted">
                {text.found}
            </Text>
            <Text size="xs" variant="muted">
                {text.causes}
            </Text>
            <div className="flex flex-wrap gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    className="no-underline"
                    render={
                        // Lemon's Link adds its own link styles over the button's, so a plain anchor opens the editor.
                        // eslint-disable-next-line react/forbid-elements
                        <a
                            href={urls.sqlEditor({ query: repeatedEventsQueryOf(check.top_events, days) })}
                            target="_blank"
                            rel="noopener noreferrer"
                        />
                    }
                    data-attr="insight-data-check-see-repeated-events"
                >
                    See these events
                </Button>
                <FixWithPostHogAIButton insightProps={insightProps} check={check} />
            </div>
        </div>
    )
}
