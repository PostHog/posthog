import { Meta, StoryObj } from '@storybook/react'
import { useMemo, useState } from 'react'

import type {
    OutcomeReadoutHistoryDTOApi,
    PaginatedSubscriptionDeliveryListApi,
    PulseRunHistoryDTOApi,
    RunActionHistoryDTOApi,
    SubscriptionsDeliveriesListStatus,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionDeliveryHistory } from './SubscriptionDeliveryHistory'
import { SubscriptionPulseDelivery } from './SubscriptionPulseDelivery'
import { MOCK_PULSE_RUNS, MOCK_SUBSCRIPTION_DELIVERIES } from './subscriptionStoryFixtures'

const noopLoadPage = (): void => undefined
const noopTestDelivery = (): void => undefined
const noopPulseDecision = (): void => undefined

const meta: Meta<typeof SubscriptionDeliveryHistory> = {
    component: SubscriptionDeliveryHistory,
    title: 'Products/Subscriptions/Subscription delivery history',
    parameters: {
        mockDate: '2026-04-07',
    },
}

export default meta

type Story = StoryObj<typeof SubscriptionDeliveryHistory>

const pageWithRows: PaginatedSubscriptionDeliveryListApi = {
    results: MOCK_SUBSCRIPTION_DELIVERIES,
    next: null,
    previous: null,
}

const pulsePageWithRows: PaginatedSubscriptionDeliveryListApi = {
    ...pageWithRows,
    results: pageWithRows.results.map((delivery) => ({
        ...delivery,
        target_value: 'pm@example.com',
    })),
}

const pulseRunsByDelivery = Object.fromEntries(MOCK_PULSE_RUNS.map((run) => [run.delivery_id, run]))

const combinedPartialPulseRun: PulseRunHistoryDTOApi = {
    ...MOCK_PULSE_RUNS[0],
    id: '00000000-0000-4000-8000-000000000105',
    delivery_id: 'del-skipped',
    status: 'partial',
    failure_code: 'publication_blocked',
    actions: [
        {
            ...MOCK_PULSE_RUNS[0].actions[0],
            id: '00000000-0000-4000-8000-000000000304',
            action_key: 'combined-checkout-follow-up',
            kind: 'combined',
            title: 'Improve checkout recovery and measure it',
            status: 'failed',
            artifacts: [
                {
                    ...MOCK_PULSE_RUNS[0].actions[0].artifacts[0],
                    status: 'publication_unknown',
                    external_url: null,
                    external_state: 'publication_unknown',
                },
                MOCK_PULSE_RUNS[0].actions[1].artifacts[0],
            ],
        },
    ],
}

const preparationFailurePulseRun: PulseRunHistoryDTOApi = {
    ...combinedPartialPulseRun,
    id: '00000000-0000-4000-8000-000000000106',
    actions: [
        {
            ...MOCK_PULSE_RUNS[0].actions[0],
            id: '00000000-0000-4000-8000-000000000305',
            title: 'Draft pull request without an artifact',
            kind: 'draft_pr',
            status: 'failed',
            artifacts: [],
        },
        {
            ...MOCK_PULSE_RUNS[0].actions[1],
            id: '00000000-0000-4000-8000-000000000306',
            title: 'Experiment preparation failure',
            kind: 'experiment_draft',
            status: 'failed',
            artifacts: [
                {
                    kind: 'experiment_draft',
                    status: 'failed',
                    external_url: null,
                    external_state: null,
                    failure_code: 'publication_blocked',
                    task_id: null,
                    execution_task_run_id: null,
                    experiment_id: null,
                },
            ],
        },
        {
            ...MOCK_PULSE_RUNS[0].actions[0],
            id: '00000000-0000-4000-8000-000000000307',
            title: 'Mixed pull request and experiment preparation',
            kind: 'combined',
            status: 'failed',
            artifacts: [
                {
                    kind: 'draft_pr',
                    status: 'verified',
                    external_url: 'https://github.com/example/example.com/pull/42',
                    external_state: 'open',
                    failure_code: null,
                    task_id: null,
                    execution_task_run_id: null,
                    experiment_id: null,
                },
                {
                    kind: 'experiment_draft',
                    status: 'failed',
                    external_url: null,
                    external_state: null,
                    failure_code: 'publication_blocked',
                    task_id: null,
                    execution_task_run_id: null,
                    experiment_id: null,
                },
            ],
        },
    ],
}

const mixedOutcomeReadout: OutcomeReadoutHistoryDTOApi = {
    id: '00000000-0000-4000-8000-000000000501',
    plan_id: '00000000-0000-4000-8000-000000000502',
    action_id: '00000000-0000-4000-8000-000000000390',
    recommendation_title: 'Add retry backoff telemetry',
    metric_name: 'Metric checkout-completion',
    metric_unit: 'count',
    baseline_value: '40',
    baseline_from: '2026-03-01T00:00:00Z',
    baseline_to: '2026-03-07T00:00:00Z',
    observed_value: '20',
    observed_from: '2026-03-08T00:00:00Z',
    observed_to: '2026-03-14T00:00:00Z',
    absolute_delta: '-20',
    relative_delta: '-50',
    status: 'measured',
    verdict: 'improved',
    confidence: '0.9',
    failure_code: null,
    artifacts: [
        {
            kind: 'draft_pr',
            status: 'verified',
            external_url: 'https://github.com/example/example.com/pull/42',
            external_state: 'merged',
            failure_code: null,
            task_id: null,
            execution_task_run_id: null,
            experiment_id: null,
        },
    ],
}

const mixedPulseActions: RunActionHistoryDTOApi[] = [
    {
        ...MOCK_PULSE_RUNS[0].actions[0],
        why_now: 'Retry failures doubled in the latest complete weekly window.',
        confidence: '0.85',
        effort: 'small',
        metric_name: 'Checkout retry rate',
        metric_unit: 'percent',
        metric_direction: 'decrease',
        expected_change_type: 'relative_percent',
        expected_change_lower: '20',
        expected_change_upper: '30',
        readout_after_days: 7,
        plan_id: '00000000-0000-4000-8000-000000000401',
        baseline_value: '0.04',
        baseline_from: '2026-03-22T00:00:00Z',
        baseline_to: '2026-03-28T00:00:00Z',
        adoption_status: 'pending',
        adoption_source: null,
        readout_status: 'waiting',
    },
    {
        ...MOCK_PULSE_RUNS[0].actions[1],
        why_now: 'Recovery has stayed flat for three complete comparison windows.',
        confidence: '0.75',
        effort: 'medium',
        metric_name: 'Checkout recovery rate',
        metric_unit: 'percent',
        metric_direction: 'increase',
        expected_change_type: 'absolute',
        expected_change_lower: '2',
        expected_change_upper: '4',
        readout_after_days: 14,
        plan_id: '00000000-0000-4000-8000-000000000402',
        baseline_value: '12',
        baseline_from: '2026-03-15T00:00:00Z',
        baseline_to: '2026-03-28T00:00:00Z',
        adoption_status: 'adopted',
        adoption_source: 'experiment_launched',
        adopted_at: '2026-04-03T10:00:00Z',
        readout_status: 'scheduled',
        next_readout_at: '2026-04-17T10:00:00Z',
    },
    {
        ...MOCK_PULSE_RUNS[0].actions[2],
        why_now: 'The last regression was detected after the weekly report arrived.',
        confidence: '0.7',
        effort: 'small',
        metric_name: 'Time to detect retry failures',
        metric_unit: 'duration',
        metric_direction: 'decrease',
        expected_change_type: 'absolute',
        expected_change_lower: '10',
        expected_change_upper: '20',
        readout_after_days: 7,
        plan_id: '00000000-0000-4000-8000-000000000403',
        baseline_value: '45',
        baseline_from: '2026-03-22T00:00:00Z',
        baseline_to: '2026-03-28T00:00:00Z',
        adoption_status: 'pending',
        adoption_source: null,
        readout_status: 'waiting',
    },
]

function pulseStory(deliveryId: string): Story {
    return {
        args: {
            deliveriesPage: pulsePageWithRows,
            deliveriesPageLoading: false,
            loadDeliveriesPage: noopLoadPage,
            onTestDelivery: noopTestDelivery,
            pulseRunsByDelivery,
            onPulseActionDecision: noopPulseDecision,
            __storyOnlyInitiallyExpandedDeliveryIds: new Set([deliveryId]),
        },
    }
}

export const WithDeliveries: Story = {
    render: () => {
        const [deliveryStatusFilter, setDeliveryStatusFilter] = useState<SubscriptionsDeliveriesListStatus | null>(null)
        const results = useMemo(
            () =>
                deliveryStatusFilter
                    ? MOCK_SUBSCRIPTION_DELIVERIES.filter((d) => d.status === deliveryStatusFilter)
                    : MOCK_SUBSCRIPTION_DELIVERIES,
            [deliveryStatusFilter]
        )
        return (
            <SubscriptionDeliveryHistory
                deliveriesPage={{ ...pageWithRows, results }}
                deliveriesPageLoading={false}
                loadDeliveriesPage={noopLoadPage}
                deliveryStatusFilter={deliveryStatusFilter}
                onDeliveryStatusFilterChange={setDeliveryStatusFilter}
                onTestDelivery={noopTestDelivery}
            />
        )
    },
}

// Covers both expand states for one PR-specific feature: the expand affordance on a collapsed row with a summary,
// and the rendered summary content inside an expanded row.
const EXPANDED_SUMMARY_STORY_IDS: ReadonlySet<string> = new Set(['del-1'])

export const WithExpandedSummary: Story = {
    args: {
        deliveriesPage: pageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        __storyOnlyInitiallyExpandedDeliveryIds: EXPANDED_SUMMARY_STORY_IDS,
    },
}

// AI-prompt delivery expanded: the rendered report markdown plus the per-query accordion (the failed query open).
const EXPANDED_AI_REPORT_STORY_IDS: ReadonlySet<string> = new Set(['del-ai-report'])

export const WithExpandedAiReport: Story = {
    args: {
        deliveriesPage: pageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        __storyOnlyInitiallyExpandedDeliveryIds: EXPANDED_AI_REPORT_STORY_IDS,
    },
}

export const PulseSuccessWithThreeActions: Story = pulseStory('del-ai-report')

export const PulseMixedOutcomesAndRecommendations: Story = {
    args: {
        deliveriesPage: pulsePageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        pulseRunsByDelivery: {
            ...pulseRunsByDelivery,
            'del-ai-report': {
                ...MOCK_PULSE_RUNS[0],
                actions: mixedPulseActions,
                readouts: [mixedOutcomeReadout],
            },
        },
        onPulseActionDecision: noopPulseDecision,
        __storyOnlyInitiallyExpandedDeliveryIds: new Set(['del-ai-report']),
    },
}

export const PulseNoDueOutcomes: Story = pulseStory('del-manual-ok')

export const PulsePermissionLossInconclusive: Story = {
    args: {
        ...PulseMixedOutcomesAndRecommendations.args,
        pulseRunsByDelivery: {
            ...pulseRunsByDelivery,
            'del-ai-report': {
                ...MOCK_PULSE_RUNS[0],
                actions: mixedPulseActions,
                readouts: [
                    {
                        ...mixedOutcomeReadout,
                        id: '00000000-0000-4000-8000-000000000503',
                        verdict: 'inconclusive',
                        observed_value: null,
                        failure_code: 'permissions_lost',
                    },
                ],
            },
        },
    },
}

export const PulseRetryExhaustion: Story = {
    args: {
        ...PulsePermissionLossInconclusive.args,
        pulseRunsByDelivery: {
            ...pulseRunsByDelivery,
            'del-ai-report': {
                ...MOCK_PULSE_RUNS[0],
                actions: mixedPulseActions,
                readouts: [
                    {
                        ...mixedOutcomeReadout,
                        id: '00000000-0000-4000-8000-000000000504',
                        verdict: 'inconclusive',
                        observed_value: null,
                        failure_code: 'retry_exhausted',
                    },
                ],
            },
        },
    },
}

export const PulseNarrowContainer: Story = {
    render: () => (
        <div className="w-[26rem] max-w-full">
            <SubscriptionPulseDelivery
                run={{ ...MOCK_PULSE_RUNS[0], actions: mixedPulseActions, readouts: [mixedOutcomeReadout] }}
                decisionLoadingIds={{}}
                onDecision={noopPulseDecision}
            />
        </div>
    ),
}

export const PulsePartial: Story = pulseStory('del-1')

export const PulseTimedOut: Story = pulseStory('del-sched-fail')

export const PulseNoActions: Story = pulseStory('del-manual-ok')

export const PulseCombinedPartial: Story = {
    args: {
        deliveriesPage: pulsePageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        pulseRunsByDelivery: {
            ...pulseRunsByDelivery,
            [combinedPartialPulseRun.delivery_id]: combinedPartialPulseRun,
        },
        onPulseActionDecision: noopPulseDecision,
        __storyOnlyInitiallyExpandedDeliveryIds: new Set([combinedPartialPulseRun.delivery_id]),
    },
}

export const PulsePreparationFailures: Story = {
    args: {
        deliveriesPage: pulsePageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        pulseRunsByDelivery: {
            ...pulseRunsByDelivery,
            [preparationFailurePulseRun.delivery_id]: preparationFailurePulseRun,
        },
        onPulseActionDecision: noopPulseDecision,
        __storyOnlyInitiallyExpandedDeliveryIds: new Set([preparationFailurePulseRun.delivery_id]),
    },
}

export const PulseHistoryUnavailable: Story = {
    args: {
        deliveriesPage: pulsePageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        pulseHistoryLoadFailed: true,
        onRetryPulseHistory: noopLoadPage,
    },
}

export const Empty: Story = {
    args: {
        deliveriesPage: { results: [], next: null, previous: null },
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        testDeliveryLoading: false,
    },
}
