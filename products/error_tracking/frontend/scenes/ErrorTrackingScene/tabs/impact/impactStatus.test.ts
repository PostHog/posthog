import { type ImpactLensProgress, impactTabStatus, impactViewStatus } from './impactStatus'

const lens = (overrides: Partial<ImpactLensProgress> = {}): ImpactLensProgress => ({
    computing: false,
    calculated: true,
    evaluable: true,
    ...overrides,
})

describe('impact status', () => {
    test.each([
        ['lenses loaded', { lensCount: 3, loading: false, loadFailed: false }, 'ready'],
        ['stale lenses while a reload fails', { lensCount: 3, loading: false, loadFailed: true }, 'ready'],
        ['first load in flight', { lensCount: 0, loading: true, loadFailed: false }, 'loading'],
        ['first load failed', { lensCount: 0, loading: false, loadFailed: true }, 'error'],
        ['loaded without lenses', { lensCount: 0, loading: false, loadFailed: false }, 'off'],
    ])('tab: %s', (_, input, expected) => {
        expect(impactTabStatus(input)).toEqual(expected)
    })

    test.each([
        [
            'items found while other lenses still calculate',
            [lens(), lens({ calculated: false, computing: true })],
            1,
            'ready',
        ],
        [
            'no items yet while a lens calculates',
            [lens(), lens({ calculated: false, computing: true })],
            0,
            'calculating',
        ],
        ['no items and a lens never calculated', [lens(), lens({ calculated: false })], 0, 'not_calculated'],
        [
            'no items and every lens unable to run',
            [lens({ evaluable: false }), lens({ evaluable: false })],
            0,
            'unavailable',
        ],
        ['no items from calculated lenses', [lens(), lens({ evaluable: false })], 0, 'empty'],
        ['no items while recalculating earlier results', [lens({ computing: true })], 0, 'empty'],
    ])('view: %s', (_, lenses, itemCount, expected) => {
        expect(impactViewStatus(lenses, itemCount)).toEqual(expected)
    })
})
