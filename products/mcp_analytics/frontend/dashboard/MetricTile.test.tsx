import { render } from '@testing-library/react'

import { buildTheme } from 'lib/charts/utils/theme'

import { MetricTile } from './MetricTile'

describe('MetricTile', () => {
    it('shows its label while loading', () => {
        const { container } = render(
            <MetricTile
                label="Tool calls"
                value={0}
                formatValue={String}
                theme={buildTheme()}
                loading
                interval="day"
                restingSubtitle="Total"
                sparklineHeight={50}
            />
        )

        expect(container.textContent).toContain('Tool calls')
    })
})
