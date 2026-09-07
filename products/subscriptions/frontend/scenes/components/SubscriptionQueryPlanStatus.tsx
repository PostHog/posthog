import { Snowflake } from 'lucide-react'

import { IconRefresh } from '@posthog/icons'
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
                "This delivery's query plan was frozen for reuse. PostHog will reuse it for future deliveries until the prompt or query planner changes. Date ranges, results, and the written report still update."
            icon = <Snowflake aria-hidden="true" className="size-4" />
            break
        case AIQueryPlanStatusEnumApi.NotFrozen:
            copy =
                "This delivery's query plan was not frozen for reuse. PostHog will generate a new plan for the next delivery."
            icon = (
                <span className="relative inline-flex size-4 items-center justify-center">
                    <Snowflake aria-hidden="true" className="size-4" />
                    <span aria-hidden="true" className="absolute h-0.5 w-[1.1rem] -rotate-45 rounded bg-current" />
                </span>
            )
            break
        case AIQueryPlanStatusEnumApi.PlannerUpdated:
            copy =
                'The query planner changed, so this delivery generated a new plan. The new plan was frozen for future deliveries.'
            icon = <IconRefresh aria-hidden="true" />
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
