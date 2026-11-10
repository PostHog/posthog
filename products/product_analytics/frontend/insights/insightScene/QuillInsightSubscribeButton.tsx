import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { InsightShortId } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

export function QuillInsightSubscribeButton({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element {
    const { push } = useActions(router)
    const { subscriptions } = useValues(subscriptionsLogic({ insightShortId }))
    const subscriptionCount = subscriptions?.length ?? 0
    const label = subscriptionCount
        ? `Subscribe (${subscriptionCount} ${subscriptionCount === 1 ? 'subscription' : 'subscriptions'})`
        : 'Subscribe'
    return (
        <Button
            variant="outline"
            indicator={subscriptionCount ? 'default' : undefined}
            aria-label={label}
            data-attr="insight-subscribe-prominent-button"
            onClick={() => {
                posthog.capture('insight subscribe prominent button clicked', {
                    insight_short_id: insightShortId,
                })
                push(urlForSubscriptions({ insightShortId }))
            }}
        >
            <IconBell />
            Subscribe
        </Button>
    )
}
