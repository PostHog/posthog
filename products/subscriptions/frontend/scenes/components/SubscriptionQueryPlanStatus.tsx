import { IconPin, IconPinFilled, IconRefresh } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import {
    AiQueryPlanStatusEnumApi,
    type AiQueryPlanStatusEnumApi as AiQueryPlanStatus,
} from 'products/subscriptions/frontend/generated/api.schemas'

export function SubscriptionQueryPlanStatus({
    status,
}: {
    status: AiQueryPlanStatus | null | undefined
}): JSX.Element | null {
    let copy: string
    let icon: JSX.Element

    switch (status) {
        case AiQueryPlanStatusEnumApi.Frozen:
            copy =
                'Frozen query plan. PostHog will reuse these query definitions for each delivery. Date ranges, results, and the written report will still update. PostHog generates a new plan when you edit the prompt or when the query planner is updated.'
            icon = <IconPinFilled aria-hidden="true" />
            break
        case AiQueryPlanStatusEnumApi.NotFrozen:
            copy =
                'Query plan not frozen. No reusable plan is available yet. PostHog will freeze the plan when it can be safely reused.'
            icon = <IconPin aria-hidden="true" />
            break
        case AiQueryPlanStatusEnumApi.PlannerUpdated:
            copy =
                'Query plan will be regenerated. The query planner changed. The next successful delivery will freeze a new plan.'
            icon = <IconRefresh aria-hidden="true" />
            break
        default:
            return null
    }

    return (
        <Tooltip title={copy} delayMs={0}>
            <span
                role="img"
                aria-label={copy}
                tabIndex={0}
                data-attr={`query-plan-status-${status}`}
                className={`inline-flex cursor-help rounded-sm text-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 ${
                    status === AiQueryPlanStatusEnumApi.NotFrozen
                        ? 'text-secondary'
                        : status === AiQueryPlanStatusEnumApi.PlannerUpdated
                          ? 'text-warning'
                          : ''
                }`}
            >
                {icon}
            </span>
        </Tooltip>
    )
}
