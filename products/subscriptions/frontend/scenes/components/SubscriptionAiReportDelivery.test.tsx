import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type {
    AIReportQueryDiagnosticApi,
    SubscriptionDeliveryApi,
} from 'products/subscriptions/frontend/generated/api.schemas'
import {
    AIQueryPlanStatusEnumApi,
    SubscriptionDeliveryStatusEnumApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

import {
    ExpandedDeliveryRow,
    isPartialDelivery,
    queryFailureReason,
    queryStatusLabel,
} from './SubscriptionAiReportDelivery'
import { MOCK_SUBSCRIPTION_DELIVERIES } from './subscriptionStoryFixtures'

const diagnostic = (ok: boolean): AIReportQueryDiagnosticApi => ({
    description: 'q',
    hogql: 'SELECT 1',
    ok,
    error_type: ok ? null : 'ResolutionError',
})

describe('SubscriptionAiReportDelivery helpers', () => {
    afterEach(() => {
        cleanup()
    })

    describe('isPartialDelivery', () => {
        it.each<[string, SubscriptionDeliveryApi['status'], AIReportQueryDiagnosticApi[] | null, boolean]>([
            // A completed delivery that couldn't run some queries is "partial", not a clean success.
            [
                'completed with a failed query',
                SubscriptionDeliveryStatusEnumApi.Completed,
                [diagnostic(true), diagnostic(false)],
                true,
            ],
            ['completed with all queries ok', SubscriptionDeliveryStatusEnumApi.Completed, [diagnostic(true)], false],
            // A fully-failed delivery is its own "Failed" state, never "partial".
            ['failed status', SubscriptionDeliveryStatusEnumApi.Failed, [diagnostic(false)], false],
            // Scrubbed/absent diagnostics (query-restricted caller, or a non-AI delivery) → not partial.
            ['completed with scrubbed diagnostics', SubscriptionDeliveryStatusEnumApi.Completed, null, false],
        ])('%s', (_name, status, diagnostics, expected) => {
            expect(isPartialDelivery({ status, ai_report_diagnostics: diagnostics })).toBe(expected)
        })
    })

    describe('queryStatusLabel', () => {
        it.each<[string, boolean, string | null, string | null, string]>([
            ['succeeded query', true, null, null, 'OK'],
            // A resolution/exposed error (message present) surfaces its specific type.
            [
                'failed with a surfaceable error',
                false,
                'ResolutionError',
                "Unable to resolve field 'x'",
                'ResolutionError',
            ],
            // A generic internal exception (no message) collapses to "Failed", not a cryptic class name.
            ['failed with an internal exception', false, 'Exception', null, 'Failed'],
        ])('%s', (_name, ok, error_type, human_readable_error, expected) => {
            expect(queryStatusLabel({ ok, error_type, human_readable_error })).toBe(expected)
        })
    })

    describe('queryFailureReason', () => {
        it.each<[string, boolean, string | null, string | null]>([
            ['succeeded query has no reason', true, null, null],
            [
                'surfaceable error shows its message',
                false,
                "Unable to resolve field 'x'",
                "Unable to resolve field 'x'",
            ],
            ['internal error shows a generic note', false, null, 'This query failed to run due to an internal error.'],
        ])('%s', (_name, ok, human_readable_error, expected) => {
            expect(queryFailureReason({ ok, human_readable_error })).toBe(expected)
        })
    })

    it('shows the plan status beside the generated query diagnostics', () => {
        const row = MOCK_SUBSCRIPTION_DELIVERIES.find((delivery) => delivery.id === 'del-ai-report')
        if (!row) {
            throw new Error('Missing AI report delivery fixture')
        }

        render(<ExpandedDeliveryRow row={row} />)

        expect(screen.getByText('Generated queries')).toBeInTheDocument()
        expect(screen.getByText('Generated queries').parentElement).toContainElement(
            screen.getByLabelText(/^Query plan locked for reuse\./)
        )
    })

    it('explains that a plan automatically locks once its queries succeed', () => {
        const row = MOCK_SUBSCRIPTION_DELIVERIES.find((delivery) => delivery.id === 'del-ai-report')
        if (!row) {
            throw new Error('Missing AI report delivery fixture')
        }

        render(<ExpandedDeliveryRow row={{ ...row, ai_query_plan_status: AIQueryPlanStatusEnumApi.NotFrozen }} />)

        expect(
            screen.getByLabelText(/automatically lock it once all queries succeed and it can be safely reused\./)
        ).toBeInTheDocument()
    })

    it('leaves the query heading unadorned when an older delivery has no recorded plan state', () => {
        const row = MOCK_SUBSCRIPTION_DELIVERIES.find((delivery) => delivery.id === 'del-ai-report')
        if (!row) {
            throw new Error('Missing AI report delivery fixture')
        }

        render(<ExpandedDeliveryRow row={{ ...row, ai_query_plan_status: null }} />)

        expect(screen.getByText('Generated queries')).toBeInTheDocument()
        expect(screen.queryByLabelText(/query plan/i)).not.toBeInTheDocument()
    })

    it('shows the planner-update outcome recorded for that delivery', () => {
        const row = MOCK_SUBSCRIPTION_DELIVERIES.find((delivery) => delivery.id === 'del-ai-report')
        if (!row) {
            throw new Error('Missing AI report delivery fixture')
        }

        render(<ExpandedDeliveryRow row={{ ...row, ai_query_plan_status: AIQueryPlanStatusEnumApi.PlannerUpdated }} />)

        expect(
            screen.getByLabelText(/^The query planner changed, so PostHog generated a new plan\./)
        ).toBeInTheDocument()
    })
})
