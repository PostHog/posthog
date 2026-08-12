import { render } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

import type { QuotaProjection } from '../../utils/quotaProjection'
import { QuotaStatusLine } from './QuotaStatusLine'

const base: QuotaProjection = {
    status: 'safe',
    exhausted: false,
    capReachDate: null,
    resetsOn: null,
    usedPct: 0,
    usedFreePct: 0,
    projectedPct: 0,
}

describe('QuotaStatusLine', () => {
    it.each([
        { name: 'renders nothing below danger', projection: { ...base, status: 'warning' as const }, text: null },
        {
            // A draft scanner spends nothing yet, so the overshoot is conditional on enabling it. Stating it as a
            // projection in flight reads as spend already happening, which is what sent one user to their billing page.
            name: 'conditional reach date for a draft scanner',
            projection: { ...base, status: 'danger' as const, usedPct: 80, capReachDate: dayjs('2026-07-21') },
            draft: true,
            text: 'Would reach your spend limit on July 21',
        },
        {
            name: 'conditional overshoot for a draft scanner with no reach date',
            projection: { ...base, status: 'danger' as const, usedPct: 80 },
            draft: true,
            text: 'Would exceed the monthly spend limit',
        },
        {
            // Spend already on the clock is a fact regardless of the draft, so this one must not go conditional.
            name: 'reached stays stated as fact for a draft scanner',
            projection: { ...base, exhausted: true, usedPct: 100 },
            draft: true,
            text: 'Spend limit reached',
        },
        {
            name: 'reached when the backend blocks spend',
            projection: { ...base, exhausted: true, usedPct: 100 },
            text: 'Spend limit reached',
        },
        {
            // The startup-cap clamp can put spend past the displayed limit while the backend still allows scans;
            // this must stay a visible red line, not disappear.
            name: 'exceeded when spend passed the displayed limit without backend exhaustion',
            projection: { ...base, status: 'danger' as const, usedPct: 104 },
            text: 'Monthly spend limit exceeded',
        },
        {
            name: 'projected reach date when on track to hit the limit',
            projection: { ...base, status: 'danger' as const, usedPct: 80, capReachDate: dayjs('2026-07-21') },
            text: 'July 21',
        },
    ])('$name', ({ projection, text, draft }) => {
        const { container } = render(<QuotaStatusLine projection={projection} onFreePlan={false} draft={draft} />)

        if (text === null) {
            expect(container.textContent).toBe('')
        } else {
            expect(container.textContent).toContain(text)
        }
    })
})
