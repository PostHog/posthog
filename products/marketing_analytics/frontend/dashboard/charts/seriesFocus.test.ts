import { focusedSeries } from './seriesFocus'

describe('focusedSeries', () => {
    it('can focus an empty breakdown key without treating it as no selection', () => {
        const theme = { colors: ['#123456', '#654321'] }

        expect(focusedSeries('', '', 0, theme)).toEqual({ color: '#123456' })
        expect(focusedSeries('', 'organic', 1, theme)).toEqual({ color: 'rgba(101, 67, 33, 0.18)' })
        expect(focusedSeries(null, 'organic', 1, theme)).toBeNull()
    })
})
