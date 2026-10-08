import { IconLock, IconRefresh, IconUnlock } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import {
    AIQueryPlanStatusEnumApi,
    type AIQueryPlanStatusEnumApi as AIQueryPlanStatus,
} from 'products/subscriptions/frontend/generated/api.schemas'

const AI_QUERY_PLAN_STATUSES = new Set<string>(Object.values(AIQueryPlanStatusEnumApi))

function isAIQueryPlanStatus(status: unknown): status is AIQueryPlanStatus {
    return typeof status === 'string' && AI_QUERY_PLAN_STATUSES.has(status)
}

export function SubscriptionQueryPlanStatus({
    status,
}: {
    status: AIQueryPlanStatus | null | undefined
}): JSX.Element | null {
    if (!isAIQueryPlanStatus(status)) {
        return null
    }

    let copy: string
    let icon: JSX.Element

    switch (status) {
        case AIQueryPlanStatusEnumApi.Frozen:
            copy =
                'Query plan locked for reuse. PostHog will reuse these queries until the prompt or query planner changes. Date ranges, results, and the written report still update.'
            icon = <IconLock aria-hidden="true" className="size-4" />
            break
        case AIQueryPlanStatusEnumApi.NotFrozen:
            copy =
                'Query plan not locked. PostHog will generate a new plan for the next delivery and automatically lock it once all queries succeed and it can be safely reused.'
            icon = <IconUnlock aria-hidden="true" className="size-4" />
            break
        case AIQueryPlanStatusEnumApi.PlannerUpdated:
            copy =
                'The query planner changed, so PostHog generated a new plan. The new plan was locked for future deliveries.'
            icon = <IconRefresh aria-hidden="true" className="size-4" />
            break
    }

    return (
        <Tooltip title={copy} delayMs={0}>
            <span
                role="img"
                aria-label={copy}
                tabIndex={0}
                className={`inline-flex cursor-help rounded-sm text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 ${
                    status === AIQueryPlanStatusEnumApi.NotFrozen
                        ? 'text-secondary'
                        : status === AIQueryPlanStatusEnumApi.PlannerUpdated
                          ? 'text-warning'
                          : ''
                }`}
            >
                {icon}
            </span>
        </Tooltip>
    )
}
