import type { IndexedTrendResult } from 'scenes/trends/types'

import { getTrendsSeriesDisplayLabel, type TrendsSeriesLabelDeps } from './getTrendsSeriesDisplayLabel'

const NO_BREAKDOWN_DEPS: TrendsSeriesLabelDeps = {
    breakdownFilter: null,
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
}

const makeResult = (overrides: Partial<IndexedTrendResult>): IndexedTrendResult =>
    ({ id: 0, label: '$pageview', data: [], ...overrides }) as IndexedTrendResult

describe('getTrendsSeriesDisplayLabel', () => {
    // Guards the legend regression: the in-chart legend must show the series' custom name, not the
    // raw event/action name. A revert to `humanizeSeriesLabel(r.label)` would fail the custom-name case.
    it.each([
        ['custom name wins over the event name', { action: { name: '$pageview', custom_name: 'Signups' } }, 'Signups'],
        ['humanizes the event name when no custom name', { action: { name: '$pageview' } }, 'Pageview'],
        ['uses the action name when not a built-in event', { action: { name: 'purchase' } }, 'purchase'],
        [
            'falls back to the humanized label when there is no action (formula row)',
            { action: null, label: 'A + B' },
            'A + B',
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(
            getTrendsSeriesDisplayLabel(makeResult(overrides as Partial<IndexedTrendResult>), NO_BREAKDOWN_DEPS)
        ).toBe(expected)
    })

    it('resolves to the breakdown value, not the custom name, for breakdown series', () => {
        // The action (and its custom_name) is shared across every breakdown band, so the breakdown
        // value must win — otherwise all bands collapse onto one label.
        const result = makeResult({
            action: { custom_name: 'Signups' } as IndexedTrendResult['action'],
            breakdown_value: 'Chrome',
        })
        const deps: TrendsSeriesLabelDeps = {
            breakdownFilter: { breakdown_type: 'event', breakdown: '$browser' },
            cohorts: undefined,
            formatPropertyValueForDisplay: undefined,
        }
        expect(getTrendsSeriesDisplayLabel(result, deps)).toBe('Chrome')
    })
})
