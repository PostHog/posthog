import type { HogFlowEditorActionMetrics } from '../../hogFlowEditorLogic'

export const TRIAL_TO_PAID_METRICS: Record<string, HogFlowEditorActionMetrics> = Object.fromEntries(
    (
        [
            ['trigger_node', 4800, 0, 0],
            ['wait_ten_days', 4790, 0, 10],
            ['by_activation', 4790, 0, 0],
            ['upgrade', 3120, 12, 48],
            ['by_seats', 1610, 0, 0],
            ['sales_slack', 210, 0, 0],
            ['help', 1380, 8, 12],
            ['wait_upgrade', 4790, 0, 0],
            ['exit_converted', 960, 0, 0],
            ['last_day', 3790, 20, 20],
            ['mark_churn_risk', 3830, 0, 0],
            ['exit_node', 3830, 0, 0],
        ] as const
    ).map(([actionId, succeeded, failed, filtered]) => [actionId, { actionId, succeeded, failed, filtered }])
)
