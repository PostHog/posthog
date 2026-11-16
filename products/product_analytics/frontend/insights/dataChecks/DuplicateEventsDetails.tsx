import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { repeatedEventsTextOf } from './dataCheckText'
import { FixWithPostHogAIButton } from './FixWithPostHogAIButton'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import { repeatedEventsQueryOf } from './repeatedEventsQuery'

export function DuplicateEventsDetails({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { lastResult } = useValues(logic)
    const { reportButtonClicked } = useActions(logic)
    const coverage = lastResult?.coverage
    const text = repeatedEventsTextOf(check)
    const repeatedEventsUrl =
        coverage &&
        urls.sqlEditor({
            query: repeatedEventsQueryOf({
                events: check.top_events,
                dateFrom: coverage.checked_date_from,
                dateTo: coverage.checked_date_to,
                sampleRate: coverage.sample?.rate ?? 1,
            }),
        })
    return (
        <div className="flex flex-col items-start gap-3">
            <div className="flex flex-col gap-1.5">
                <Text size="xs" variant="muted">
                    {text.found}
                </Text>
                <Text size="xs" variant="muted">
                    {text.causes}
                </Text>
            </div>
            <div className="flex flex-wrap gap-2">
                {repeatedEventsUrl && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="no-underline"
                        render={<LinkPrimitive to={repeatedEventsUrl} target="_blank" />}
                        onClick={() => reportButtonClicked('see_repeated_events', check.key)}
                        data-attr="insight-data-check-see-repeated-events"
                    >
                        See these events
                    </Button>
                )}
                <FixWithPostHogAIButton insightProps={insightProps} check={check} />
            </div>
        </div>
    )
}
