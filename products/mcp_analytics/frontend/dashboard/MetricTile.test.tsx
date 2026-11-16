import { render } from '@testing-library/react'

import { buildTheme } from 'lib/charts/utils/theme'

import { MetricTile } from './MetricTile'

describe('MetricTile', () => {
    it.each([
        { state: 'loading', loading: true, failed: false },
        { state: 'failed', loading: false, failed: true },
    ])('shows its label while $state', ({ loading, failed }) => {
        const { container } = render(
            <MetricTile
                label="Tool calls"
                value={0}
                formatValue={String}
                theme={buildTheme()}
                loading={loading}
                failed={failed}
                interval="day"
                restingSubtitle="Total"
                sparklineHeight={50}
            />
        )

        expect(container.textContent).toContain('Tool calls')
    })
})
