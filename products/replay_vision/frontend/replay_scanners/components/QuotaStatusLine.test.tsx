import { render } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

import type { QuotaProjection } from '../../utils/quotaProjection'
import { QuotaStatusLine } from './QuotaStatusLine'

const base: QuotaProjection = {
    status: 'safe',
    exhausted: false,
    capReachDate: null,
    percentLabel: 0,
    resetsOn: null,
    usedPct: 0,
    usedFreePct: 0,
    projectedPct: 0,
}

describe('QuotaStatusLine', () => {
    it.each([
        {
            name: 'renders nothing on a bare warning with no forecast date',
            projection: { ...base, status: 'warning' as const },
            text: null,
            color: null,
        },
        {
            name: 'reached, in red, when the backend blocks spend',
            projection: { ...base, exhausted: true, usedPct: 100 },
            text: 'Spend limit reached',
            color: 'text-danger',
        },
        {
            // The startup-cap clamp can put spend past the displayed limit while the backend still allows scans;
            // this must stay a visible red line, not disappear.
            name: 'exceeded, in red, when spend passed the displayed limit without backend exhaustion',
            projection: { ...base, status: 'danger' as const, usedPct: 104 },
            text: 'Monthly spend limit exceeded',
            color: 'text-danger',
        },
        {
            // A forecast must read as amber, never as a red breach at low usage.
            name: 'projected reach date, in amber, when on track to hit the limit',
            projection: { ...base, status: 'warning' as const, usedPct: 3, capReachDate: dayjs('2026-07-21') },
            text: 'July 21',
            color: 'text-warning',
        },
    ])('$name', ({ projection, text, color }) => {
        const { container } = render(<QuotaStatusLine projection={projection} onFreePlan={false} />)

        if (text === null) {
            expect(container.textContent).toBe('')
        } else {
            expect(container.textContent).toContain(text)
            expect(container.querySelector(`.${color}`)).not.toBeNull()
        }
    })
})
