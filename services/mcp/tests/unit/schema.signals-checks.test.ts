import { describe, expect, it } from 'vitest'

import { SignalsReportChecksReplaceCreateBody } from '@/generated/signals/api'

describe('Signals metric check replacement inputs', () => {
    it('leaves omitted display fields available for the referenced metric to supply', () => {
        const result = SignalsReportChecksReplaceCreateBody().parse({
            title: 'Checkout conversion improves',
            config: {
                metric_id: 'checkout-conversion',
                comparison: { operator: 'gte', value: 0.8 },
                monitoring: { reference_period_minutes: 1440, threshold_scaling: 'fixed' },
            },
        })
        expect(result.config.metric_kind).toBeUndefined()
        expect(result.config.value_format).toBeUndefined()
        expect(result.config.unit).toBeUndefined()
    })
})
