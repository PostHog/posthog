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
    ])('$name', ({ projection, text }) => {
        const { container } = render(<QuotaStatusLine projection={projection} onFreePlan={false} />)

        if (text === null) {
            expect(container.textContent).toBe('')
        } else {
            expect(container.textContent).toContain(text)
        }
    })
})
