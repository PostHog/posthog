import { IconPin, IconPinFilled, IconRefresh } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import {
    AIQueryPlanStatusEnumApi,
    type AIQueryPlanStatusEnumApi as AIQueryPlanStatus,
} from 'products/subscriptions/frontend/generated/api.schemas'

const AI_QUERY_PLAN_STATUSES = new Set<string>(Object.values(AIQueryPlanStatusEnumApi))

export function isAIQueryPlanStatus(status: unknown): status is AIQueryPlanStatus {
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
                'Frozen query plan. PostHog will reuse these query definitions for each delivery. Date ranges, results, and the written report will still update. PostHog generates a new plan when you edit the prompt or when the query planner is updated.'
            icon = <IconPinFilled aria-hidden="true" />
            break
        case AIQueryPlanStatusEnumApi.NotFrozen:
            copy =
                'Query plan not frozen. No reusable plan is available yet. PostHog will freeze the plan when it can be safely reused.'
            icon = <IconPin aria-hidden="true" />
            break
        case AIQueryPlanStatusEnumApi.PlannerUpdated:
            copy =
                'Query plan will be regenerated. The query planner changed. The next successful delivery will freeze a new plan.'
            icon = <IconRefresh aria-hidden="true" />
            break
    }

    return (
        <Tooltip title={copy} delayMs={0}>
            <span
                role="img"
                aria-label={copy}
                tabIndex={0}
                className={`inline-flex cursor-help rounded-sm text-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 ${
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
