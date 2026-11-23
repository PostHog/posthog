import { render } from '@testing-library/react'

import { buildTheme } from 'lib/charts/utils/theme'

import { MetricTile, type MetricTileProps } from './MetricTile'

const TILE: MetricTileProps = {
    label: 'Tool calls',
    value: 42,
    formatValue: String,
    theme: buildTheme(),
    loading: false,
    hasValue: true,
    interval: 'day',
    restingSubtitle: 'Total',
    sparklineHeight: 50,
}

describe('MetricTile', () => {
    it.each([
        { part: 'label', text: 'Tool calls' },
        { part: 'resting subtitle', text: 'Total' },
    ])('shows its $part while loading', ({ text }) => {
        const { container } = render(<MetricTile {...TILE} loading hasValue={false} />)

        expect(container.textContent).toContain(text)
    })

    it.each([
        { shows: 'a skeleton', when: 'its new data has no value yet', hasValue: false, showsValue: false },
        { shows: 'the value', when: 'it refreshes a value it already has', hasValue: true, showsValue: true },
    ])('after showing a value, a reloading tile shows $shows when $when', ({ hasValue, showsValue }) => {
        const { container, rerender } = render(<MetricTile {...TILE} />)

        rerender(<MetricTile {...TILE} value={7} loading hasValue={hasValue} />)

        expect(container.textContent?.includes('7')).toBe(showsValue)
    })
})
