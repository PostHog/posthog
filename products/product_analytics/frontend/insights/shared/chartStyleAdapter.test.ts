import type { ChartStyle } from '~/queries/schema/schema-general'

import { chartStyleCurve } from './chartStyleAdapter'

describe('chartStyleCurve', () => {
    it.each<[string, ChartStyle | null | undefined, 'linear' | 'monotone' | undefined]>([
        ['smooth maps to monotone', { curve: 'smooth' }, 'monotone'],
        ['linear stays linear', { curve: 'linear' }, 'linear'],
        ['undefined falls through to app default', undefined, undefined],
        ['null falls through to app default', null, undefined],
        ['empty style falls through to app default', {}, undefined],
    ])('%s', (_name, input, expected) => {
        expect(chartStyleCurve(input)).toBe(expected)
    })
})
