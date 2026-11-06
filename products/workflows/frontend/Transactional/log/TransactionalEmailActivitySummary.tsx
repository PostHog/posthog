import { IconBolt } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { TransactionalEmailLogEventApi } from 'products/messaging/frontend/generated/api.schemas'

import { ActivityEvent, summarizeAfter } from './emailActivity'

/** How many custom events the summary names before it stops. */
const MAX_OUTCOMES = 4

export function TransactionalEmailActivitySummary({
    after,
    timeline,
}: {
    after: ActivityEvent[]
    timeline: readonly TransactionalEmailLogEventApi[]
}): JSX.Element | null {
    if (!after.length) {
        return null
    }
    const { comeback, eventCount, sessionCount, outcomes } = summarizeAfter(after, timeline)
    return (
        <div className="flex flex-wrap items-center gap-2 text-sm">
            {comeback && <LemonTag type="success">{comeback}</LemonTag>}
            <LemonTag type="muted">
                {pluralize(eventCount, 'event')} after the email
                {sessionCount > 0 ? ` across ${pluralize(sessionCount, 'session')}` : ''}
            </LemonTag>
            {outcomes.length > 0 && <span className="text-xs text-secondary">Then did</span>}
            {outcomes.slice(0, MAX_OUTCOMES).map((outcome) => (
                <LemonTag key={outcome} type="warning" icon={<IconBolt />}>
                    {outcome}
                </LemonTag>
            ))}
        </div>
    )
}
