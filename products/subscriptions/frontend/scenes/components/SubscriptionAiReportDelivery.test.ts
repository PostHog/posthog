import type {
    AIReportQueryDiagnosticApi,
    SubscriptionDeliveryApi,
} from 'products/subscriptions/frontend/generated/api.schemas'
import { SubscriptionDeliveryStatusEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

import {
    isPartialDelivery,
    partialDeliveryTooltip,
    queryFailureReason,
    queryStatusLabel,
} from './SubscriptionAiReportDelivery'

const diagnostic = (ok: boolean): AIReportQueryDiagnosticApi => ({
    description: 'q',
    hogql: 'SELECT 1',
    ok,
    error_type: ok ? null : 'ResolutionError',
})

describe('SubscriptionAiReportDelivery helpers', () => {
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

        it('marks a completed delivery with a partial recipient result as partial', () => {
            expect(
                isPartialDelivery({
                    status: SubscriptionDeliveryStatusEnumApi.Completed,
                    ai_report_diagnostics: [],
                    recipient_results: [{ recipient: 'C123|#reports', status: 'partial', error: null }],
                })
            ).toBe(true)
        })
    })

    describe('partialDeliveryTooltip', () => {
        it('describes recipient-only partials without referring to AI queries', () => {
            const tooltip = partialDeliveryTooltip({
                status: SubscriptionDeliveryStatusEnumApi.Completed,
                ai_report_diagnostics: [],
                recipient_results: [
                    {
                        recipient: 'C123|#reports',
                        status: 'partial',
                        error: null,
                        human_readable_error: '2 images could not be attached',
                    },
                ],
            })

            expect(tooltip).toBe('2 images could not be attached')
            expect(tooltip).not.toContain('queries')
        })

        it('describes both query and recipient partials', () => {
            expect(
                partialDeliveryTooltip({
                    status: SubscriptionDeliveryStatusEnumApi.Completed,
                    ai_report_diagnostics: [diagnostic(true), diagnostic(false)],
                    recipient_results: [
                        {
                            recipient: 'C123|#reports',
                            status: 'partial',
                            error: null,
                            human_readable_error: '1 image could not be attached',
                        },
                    ],
                })
            ).toBe('1 of 2 queries failed; those metrics are missing from the report. 1 image could not be attached')
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
})
