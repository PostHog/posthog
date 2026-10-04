import { router } from 'kea-router'
import posthog from 'posthog-js'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

// pinned: analytics event names and `surface` values, renaming breaks dashboards
type TopicsUsageEvent =
    | 'messaging topic created'
    | 'messaging topic updated'
    | 'messaging topic deleted'
    | 'messaging customer.io import completed'
    | 'messaging preferences page opened'
    | 'messaging opt-outs exported'
    | 'messaging opt-outs imported'

type TopicsSurface = 'workflows' | 'broadcasts' | 'audience'

function currentTopicsSurface(): TopicsSurface {
    const path = removeProjectIdIfPresent(router.values.location.pathname)
    if (path.startsWith(urls.audience())) {
        return 'audience'
    }
    if (path.startsWith(urls.broadcasts())) {
        return 'broadcasts'
    }
    return 'workflows'
}

export function captureTopicsUsage(event: TopicsUsageEvent, properties: Record<string, string | number> = {}): void {
    posthog.capture(event, { ...properties, surface: currentTopicsSurface() })
}
